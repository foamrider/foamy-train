import copy
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("train_fetch", Path(__file__).parents[1] / "train_fetch.py")
train = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(train)
ROUTE = {"from": {"id": "NSR:StopPlace:1", "name": "Central"}, "to": {"id": "NSR:StopPlace:2", "name": "Airport"}}
NOW = train.timestamp("2026-09-26T09:04:00+02:00")


def leg(**changes):
    value = {"id": "train-1", "mode": "rail", "aimedStartTime": "2026-09-26T09:12:00+02:00",
             "expectedStartTime": "2026-09-26T09:15:00+02:00", "aimedEndTime": "2026-09-26T09:22:00+02:00",
             "expectedEndTime": "2026-09-26T09:25:00+02:00", "line": {"publicCode": "R10"},
             "fromEstimatedCall": {"cancellation": False, "realtime": True, "quay": {"publicCode": "11"}},
             "toEstimatedCall": {"cancellation": False}, "situations": []}
    value.update(changes)
    return value


def response(*legs):
    return {"data": {"trip": {"tripPatterns": [{"legs": [value]} for value in legs]}}}


def notice(identifier="n1", **changes):
    value = {"id": identifier, "reportType": "incident", "summary": [{"language": "en", "value": "Signal fault"}, {"language": "nb", "value": "Signalfeil"}],
             "description": [{"language": "en", "value": "Allow more time."}], "affects": [{"__typename": "AffectedServiceJourney"}]}
    value.update(changes)
    return value


class ParserTests(unittest.TestCase):
    def parse(self, data, language="en"):
        return train.parse_response(data, ROUTE, language, NOW)

    def test_window_uses_expected_time_and_includes_the_boundary(self):
        boundary = leg(expectedStartTime="2026-09-26T10:04:00+02:00")
        delayed_outside = leg(id="later", expectedStartTime="2026-09-26T10:04:01+02:00")
        data = train.parse_response(response(boundary, delayed_outside), ROUTE, "en", NOW, 1)
        self.assertEqual(len(data["departures"]), 1)
        self.assertEqual(data["departures"][0]["expected"], NOW + 3600)
        self.assertEqual(len(train.parse_response(response(boundary, delayed_outside), ROUTE, "en", NOW, 2)["departures"]), 2)

    def test_delay_arrival_platform_and_journey(self):
        d = self.parse(response(leg()))["departures"][0]
        self.assertEqual((d["delay"], d["duration"], d["platform"], d["arrivalTime"]), (3, 10, "11", "09:25"))
        self.assertTrue(d["realtime"])

    def test_filters_transfer_walk_and_bus(self):
        data = response(leg(), leg(mode="bus"))
        data["data"]["trip"]["tripPatterns"] += [{"legs": [leg(), leg(id="other")]}, {"legs": [{"mode": "foot"}, leg()]}]
        self.assertEqual(len(self.parse(data)["departures"]), 1)

    def test_cancellation_at_either_end(self):
        d = leg(toEstimatedCall={"cancellation": True})
        self.assertTrue(self.parse(response(d))["departures"][0]["cancelled"])

    def test_repeated_notice_does_not_imply_route_scope(self):
        data = self.parse(response(leg(situations=[notice()]), leg(id="train-2", situations=[notice()])))
        self.assertEqual(data["routeNotices"], [])
        self.assertTrue(all(len(d["notices"]) == 1 for d in data["departures"]))

    def test_explicit_broad_notice_is_deduplicated_and_labelled(self):
        n = notice(affects=[{"__typename": "AffectedLine", "line": {"publicCode": "R10"}}])
        data = self.parse(response(leg(situations=[n]), leg(id="train-2", situations=[n])))
        self.assertEqual(len(data["routeNotices"]), 1)
        self.assertEqual(data["routeNotices"][0]["scopeLabel"], "R10")
        self.assertEqual(data["departures"][0]["notices"], [])

    def test_mixed_scope_remains_on_departure(self):
        n = notice(affects=[{"__typename": "AffectedLine"}, {"__typename": "AffectedServiceJourney"}])
        self.assertEqual(len(self.parse(response(leg(situations=[n])))["departures"][0]["notices"]), 1)

    def test_info_without_delay_and_localization(self):
        d = self.parse(response(leg(situations=[notice(reportType="general")], expectedStartTime="2026-09-26T09:12:00+02:00")), "nb")["departures"][0]
        self.assertEqual(d["delay"], 0)
        self.assertEqual(d["notices"][0]["kind"], "info")
        self.assertEqual(d["notices"][0]["summary"], "Signalfeil")

    def test_empty_and_malformed_are_distinct(self):
        self.assertEqual(self.parse(response())["status"], "ok")
        for data in ({}, {"errors": [{"message": "bad"}]}, response(leg(expectedStartTime="bad")), response(leg(expectedStartTime="2026-09-26T09:12:00"))):
            with self.assertRaises(train.TrainError):
                self.parse(data)

    def test_duplicate_and_expired_departures_removed(self):
        self.assertEqual(len(self.parse(response(leg(), leg()))["departures"]), 1)
        d = leg(aimedStartTime="2026-09-26T08:00:00+02:00", expectedStartTime="2026-09-26T08:00:00+02:00")
        self.assertEqual(self.parse(response(d))["departures"], [])

    def test_missing_platform_and_realtime_are_explicit(self):
        d = self.parse(response(leg(fromEstimatedCall={})))["departures"][0]
        self.assertEqual(d["platform"], "—")
        self.assertFalse(d["realtime"])


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.env = patch.dict(os.environ, {key: self.temp.name + "/" + key for key in ("XDG_CONFIG_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME")})
        self.env.start()
        self.addCleanup(self.env.stop)

    def test_neutral_first_run(self):
        with patch.object(train, "request_json") as request:
            self.assertEqual(train.fetch(None, "en")["status"], "unconfigured")
            request.assert_not_called()

    def test_route_validation_sanitizes_station_labels(self):
        route = copy.deepcopy(ROUTE)
        route["from"]["name"] = " Central "
        route["from"]["label"] = "Search-only label"
        self.assertEqual(train.validate_route(route), ROUTE)

    def test_route_validation_rejects_invalid_pairs(self):
        for route in ({}, {"from": ROUTE["from"], "to": ROUTE["from"]},
                      {"from": {"id": "bad", "name": "Central"}, "to": ROUTE["to"]}):
            with self.assertRaises(train.TrainError):
                train.validate_route(route)

    def test_failed_refresh_retains_original_snapshot_time(self):
        with patch.object(train.time, "time", return_value=NOW), patch.object(train, "request_json", return_value=response(leg())):
            original = train.fetch(ROUTE, "en", force=True)
        self.assertEqual(stat.S_IMODE(train.cache_path(ROUTE, "en").stat().st_mode), 0o600)
        with patch.object(train.time, "time", return_value=NOW+120), patch.object(train, "request_json", side_effect=train.TrainError("network_error", "Unavailable")):
            stale = train.fetch(ROUTE, "en", force=True)
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["updatedAt"], original["updatedAt"])
        self.assertEqual(stale["status"], "stale")

    def test_cache_isolated_by_route_and_language(self):
        reverse = {"from": ROUTE["to"], "to": ROUTE["from"]}
        self.assertNotEqual(train.cache_path(ROUTE, "en"), train.cache_path(reverse, "en"))
        self.assertNotEqual(train.cache_path(ROUTE, "en"), train.cache_path(ROUTE, "nb"))

    def test_changing_hours_fetches_a_new_window_instead_of_reusing_short_cache(self):
        with patch.object(train.time, "time", return_value=NOW), patch.object(train, "request_json", return_value=response(leg())) as request:
            train.fetch(ROUTE, "en", look_ahead_hours=1)
            self.assertEqual(request.call_args.args[1]["variables"]["searchWindow"], 60)
            train.fetch(ROUTE, "en", look_ahead_hours=24)
            self.assertEqual(request.call_count, 2)
            self.assertEqual(request.call_args.args[1]["variables"]["searchWindow"], 1440)
            train.fetch(ROUTE, "en", look_ahead_hours=24)
            self.assertEqual(request.call_count, 2)
        self.assertNotEqual(train.cache_path(ROUTE, "en", 1), train.cache_path(ROUTE, "en", 24))

    def test_invalid_hours_are_rejected_before_network_or_cache(self):
        with patch.object(train, "request_json") as request:
            for hours in (0, 25, 1.5, "3", True):
                with self.assertRaises(train.TrainError):
                    train.fetch(ROUTE, "en", look_ahead_hours=hours)
            request.assert_not_called()

    def test_offline_never_requests_network(self):
        with patch.object(train, "request_json") as request:
            self.assertEqual(train.fetch(ROUTE, "en", offline=True)["status"], "error")
            request.assert_not_called()

    def test_cache_expiry_and_corruption_do_not_block_refresh(self):
        train.atomic_json(train.cache_path(ROUTE, "en"), {"bad": 1})
        with patch.object(train.time, "time", return_value=NOW), patch.object(train, "request_json", return_value=response(leg())):
            self.assertEqual(train.fetch(ROUTE, "en")["status"], "ok")
        with patch.object(train.time, "time", return_value=NOW+86401):
            self.assertEqual(train.fetch(ROUTE, "en", offline=True)["status"], "error")

    def test_search_validates_and_deduplicates_stations(self):
        good = {"properties": {"id": "NSR:StopPlace:12", "names": {"default": "Central", "display": "Central, City"}, "stopPlaceTypes": ["railStation"]}}
        bad = {"properties": {"id": "not-an-id", "stopPlaceTypes": ["railStation"]}}
        with patch.object(train, "request_json", return_value={"features": [good, good, bad]}):
            self.assertEqual(train.search("Central"), [{"id": "NSR:StopPlace:12", "name": "Central", "label": "Central, City"}])


if __name__ == "__main__":
    unittest.main()
