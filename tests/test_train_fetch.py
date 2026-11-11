"""Black-box tests of the departure helper: it runs as a process against a
local fake Entur (tests/fake_entur.py) with temporary HOME/XDG directories
and an empty PATH. Nothing here contacts Entur.

FOAMY_HELPER selects the helper (a JSON argv prefix); see fake_entur.py.
"""
import copy
import json
import stat
import tempfile
import time
import unittest

from fake_entur import (API_PATH, CLIENT, DEPARTURE_KEYS, GEOCODER_PATH, QUERY, REPORT_KEYS, ROUTE, CertAuthority,
                        FakeEntur, FakeProxy, Helper, Reply, base_time, basic, busy, cache_name, feature, hm, iso, leg,
                        notice, on_time, python_json, temporary, trips)

INVALID = "Entur returned an invalid response. Try Refresh."


class Case(unittest.TestCase):
    def setUp(self):
        self.temp = temporary()
        self.addCleanup(self.temp.cleanup)
        self.entur = FakeEntur()
        self.addCleanup(self.entur.close)
        self.helper = Helper(self.temp.name, self.entur.url)

    def fetch(self, *args, **kwargs):
        return self.helper.fetch(*args, **kwargs)

    def plan(self, *replies, args=("--force", "--hours", "3"), **kwargs):
        """The report for queued planner answers, 3-hour look-ahead (one request)."""
        self.entur.plan(*replies)
        return self.fetch(*args, **kwargs)

    def refused(self):
        """A helper whose endpoint refuses connections."""
        return Helper(tempfile.mkdtemp(dir=self.temp.name), "http://127.0.0.1:9")


class ParserTests(Case):
    def test_window_uses_expected_time_and_includes_the_boundary(self):
        now = int(time.time())
        inside = on_time(now + 1800, expectedStartTime=iso(now + 3580))
        outside = on_time(now + 1800, id="later", expectedStartTime=iso(now + 3640))
        self.entur.fallback[API_PATH] = Reply(trips(inside, outside))
        data = self.fetch("--force", "--hours", "1")
        self.assertEqual(len(data["departures"]), 1)
        self.assertEqual(data["departures"][0]["expected"], now + 3580)
        self.assertEqual(len(self.fetch("--force", "--hours", "2")["departures"]), 2)
        self.assertEqual(self.entur.windows(), [60, 120])

    def test_departure_fields_and_report_shape(self):
        start = base_time()
        data = self.plan(trips(leg(start)))
        self.assertEqual(list(data), REPORT_KEYS + ["searchHours"])
        self.assertEqual((data["status"], data["route"], data["routeNotices"], data["stale"], data["error"],
                          data["errorCode"], data["searchHours"]), ("ok", ROUTE, [], False, "", "", 3))
        self.assertLessEqual(abs(data["updatedAt"] - time.time()), 5)
        d = data["departures"][0]
        self.assertEqual(list(d), DEPARTURE_KEYS)
        self.assertEqual(d, {"id": f"train-1:{start}", "line": "R10", "aimed": start, "expected": start + 180,
                             "arrival": start + 780, "aimedTime": hm(start), "expectedTime": hm(start + 180),
                             "arrivalTime": hm(start + 780), "delay": 3, "duration": 10, "platform": "11",
                             "realtime": True, "cancelled": False, "notices": []})

    def test_times_are_oslo_wall_clock_whatever_the_offset_or_tz(self):
        start = base_time()
        utc = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(start))
        fraction = time.strftime("%Y-%m-%dT%H:%M:%S.250+00:00", time.gmtime(start + 180))
        data = self.plan(trips(leg(start, aimedStartTime=utc, expectedStartTime=fraction)), env={"TZ": "Asia/Tokyo"})
        d = data["departures"][0]
        self.assertEqual((d["aimed"], d["expected"], d["aimedTime"], d["expectedTime"]),
                         (start, start + 180, hm(start), hm(start + 180)))

    def test_filters_transfer_walk_and_bus(self):
        start = base_time()
        data = trips(leg(start), leg(start, mode="bus"))
        data["data"]["trip"]["tripPatterns"] += [{"legs": [leg(start), leg(start, id="other")]},
                                                 {"legs": [{"mode": "foot"}, leg(start)]}, {"legs": []}]
        self.assertEqual(len(self.plan(data)["departures"]), 1)

    def test_cancellation_at_either_end(self):
        start = base_time()
        data = self.plan(trips(leg(start, toEstimatedCall={"cancellation": True}),
                               leg(start + 60, id="b", fromEstimatedCall={"cancellation": True}),
                               leg(start + 120, id="c", fromEstimatedCall={"cancellation": "yes"})))
        self.assertEqual([d["cancelled"] for d in data["departures"]], [True, True, False])

    def test_repeated_notice_does_not_imply_route_scope(self):
        start = base_time()
        data = self.plan(trips(leg(start, situations=[notice()]), leg(start + 60, id="train-2", situations=[notice()])))
        self.assertEqual(data["routeNotices"], [])
        self.assertTrue(all(len(d["notices"]) == 1 for d in data["departures"]))
        self.assertEqual(data["departures"][0]["notices"][0], {"id": "n1", "summary": "Signal fault",
                                                               "detail": "Allow more time.", "kind": "warning",
                                                               "scopeLabel": ""})

    def test_explicit_broad_notice_is_deduplicated_and_labelled(self):
        start = base_time()
        n = notice(affects=[{"__typename": "AffectedLine", "line": {"publicCode": "R10"}},
                            {"__typename": "AffectedStopPlace", "stopPlace": {"name": "Oslo S"}},
                            {"__typename": "AffectedStopPlaceOnLine", "line": {"publicCode": "R10"}, "stopPlace": {}}])
        data = self.plan(trips(leg(start, situations=[n]), leg(start + 60, id="train-2", situations=[n])))
        self.assertEqual(len(data["routeNotices"]), 1)
        self.assertEqual(data["routeNotices"][0]["scopeLabel"], "R10 · Oslo S")
        self.assertEqual(data["departures"][0]["notices"], [])

    def test_mixed_scope_remains_on_departure(self):
        start = base_time()
        n = notice(affects=[{"__typename": "AffectedLine"}, {"__typename": "AffectedServiceJourney"}])
        self.assertEqual(len(self.plan(trips(leg(start, situations=[n])))["departures"][0]["notices"]), 1)

    def test_notices_from_the_leg_and_both_calls_are_merged_and_deduplicated(self):
        start = base_time()
        late = notice("c", summary=[], advice=[{"value": "Walk"}])
        data = self.plan(trips(leg(start, situations=[notice("a")],
                                   fromEstimatedCall={"situations": [notice("b"), notice("a")]},
                                   toEstimatedCall={"situations": [late]})))
        notices = data["departures"][0]["notices"]
        self.assertEqual([n["id"] for n in notices], ["a", "b", "c"])
        self.assertEqual((notices[2]["summary"], notices[2]["detail"]), ("Allow more time.", "Walk"))

    def test_info_without_delay_and_localization(self):
        start = base_time()
        n = notice(reportType="general", advice=[{"language": "no", "value": " Gå "}, {"language": "en", "value": "Walk"}])
        args = ("--force", "--hours", "3", "--language", "nb")
        d = self.plan(trips(on_time(start, situations=[n])), args=args)["departures"][0]
        self.assertEqual(d["delay"], 0)
        self.assertEqual(d["notices"][0]["kind"], "info")
        self.assertEqual(d["notices"][0]["summary"], "Signalfeil")
        self.assertEqual(d["notices"][0]["detail"], "Allow more time.\n\nGå")

    def test_notice_text_falls_back_and_identity_defaults_to_text(self):
        start = base_time()
        anonymous = {"summary": [{"language": "de", "value": "Störung"}], "description": [{"value": 5}, {"value": "Störung"}]}
        empty = {"id": "e", "summary": [], "description": "text"}
        d = self.plan(trips(leg(start, situations=[anonymous, empty, "x", None])))["departures"][0]
        self.assertEqual(d["notices"], [{"id": "Störung", "summary": "Störung", "detail": "", "kind": "warning",
                                         "scopeLabel": ""}])

    def test_empty_and_malformed_are_distinct(self):
        # Failures write no cache, so each report is an error rather than stale.
        start = base_time()
        line_code = notice(affects=[{"__typename": "AffectedLine", "line": {"publicCode": 5}}])
        malformed = [{}, {"data": None}, {"data": {"trip": {"tripPatterns": {}}}}, trips(leg(start, expectedStartTime="bad")),
                     trips(leg(start, expectedStartTime=iso(start)[:19])), trips(leg(start, aimedStartTime=None)),
                     {"data": {"trip": {"tripPatterns": ["x"]}}}, {"data": {"trip": {"tripPatterns": [{"legs": ["x"]}]}}},
                     trips(leg(start, situations={"a": 1})), trips(leg(start, line="R10")),
                     trips(leg(start, situations=[line_code])), trips(leg(start, situations=[notice(affects=7)]))]
        for data in malformed:
            with self.subTest(data=data):
                report = self.plan(data)
                self.assertEqual((report["status"], report["errorCode"], report["error"]), ("error", "invalid_response", INVALID))
                self.assertEqual(report["route"], ROUTE)
        for errors in ([{"message": "bad"}], "bad", {"a": 1}):
            report = self.plan({"errors": errors, "data": {"trip": {"tripPatterns": []}}})
            self.assertEqual((report["errorCode"], report["error"]), ("api_error", "Entur could not find departures. Try Refresh."))
        self.assertEqual(self.plan({"errors": [], "data": {"trip": {"tripPatterns": []}}})["status"], "ok")
        self.assertEqual(self.plan(trips())["status"], "ok")

    def test_odd_but_valid_shapes_are_tolerated(self):
        start = base_time()
        data = self.plan(trips(leg(start, serviceJourney={"id": 42}, line=None, situations=None, fromEstimatedCall=None),
                               leg(start + 60, id="b", situations=[notice(affects="AffectedLine")])))
        first, second = data["departures"]
        self.assertEqual((first["id"], first["line"], first["platform"], first["realtime"]), (f"42:{start}", "—", "—", False))
        self.assertEqual(second["notices"][0]["scopeLabel"], "")

    def test_duplicate_and_expired_departures_removed(self):
        start = base_time()
        self.assertEqual(len(self.plan(trips(leg(start), leg(start)))["departures"]), 1)
        now = int(time.time())
        expired = on_time(now - 120)
        recent = on_time(now - 30, id="recent")
        self.assertEqual([d["id"] for d in self.plan(trips(expired, recent))["departures"]], [f"recent:{now - 30}"])

    def test_sorted_by_expected_then_aimed_and_capped(self):
        start = base_time()
        legs = [on_time(start + 600, id="late"), leg(start, id="delayed", expectedStartTime=iso(start + 300)),
                on_time(start + 300, id="early")] + [on_time(start + 900 + i * 60, id=f"x{i}") for i in range(5)]
        data = self.plan(trips(*legs))
        self.assertEqual([d["id"].split(":")[0] for d in data["departures"]], ["delayed", "early", "late", "x0", "x1", "x2"])

    def test_ten_thousand_notices_below_the_byte_cap_keep_three(self):
        # The marketplace review's shape: one valid rail leg, 10,000 unique situations.
        situations = [{"id": f"n{i}", "summary": [{"language": "en", "value": "x"}]} for i in range(10_000)]
        data = trips(leg(base_time(), situations=[notice("n0"), *situations]))
        self.assertLess(len(json.dumps(data)), 2_000_000)
        report = self.plan(data)
        self.assertEqual([n["id"] for n in report["departures"][0]["notices"]], ["n0", "n1", "n2"])
        self.assertEqual(report["departures"][0]["notices"][1]["summary"], "x")
        self.assertEqual(list(report), REPORT_KEYS + ["noticesOmitted", "searchHours"])
        self.assertIs(report["noticesOmitted"], True)
        self.assertEqual(self.helper.read_cache(hours=3), report)

    def test_route_notices_are_counted_across_departures_after_deduplication(self):
        start = base_time()

        def wide(identifier):
            return {"id": identifier, "summary": [{"value": "x"}], "affects": [{"__typename": "AffectedLine"}]}
        # The same five route-wide notices on every departure: all of them, none left out.
        same = [on_time(start + i * 60, id=f"t{i}", situations=[wide(f"w{n}") for n in range(5)]) for i in range(6)]
        report = self.plan(trips(*same))
        self.assertEqual([n["id"] for n in report["routeNotices"]], ["w0", "w1", "w2", "w3", "w4"])
        self.assertNotIn("noticesOmitted", report)
        # 1,500 distinct ones on each of six departures: the first five overall.
        distinct = [on_time(start + i * 60, id=f"t{i}", situations=[wide(f"w{i}-{n}") for n in range(1500)])
                    for i in range(6)]
        data = trips(*distinct)
        self.assertLess(len(json.dumps(data)), 2_000_000)
        report = self.plan(data)
        self.assertEqual([n["id"] for n in report["routeNotices"]], ["w0-0", "w0-1", "w0-2", "w0-3", "w0-4"])
        self.assertTrue(all(d["notices"] == [] for d in report["departures"]))
        self.assertIs(report["noticesOmitted"], True)

    def test_a_notice_left_out_on_a_later_departure_only_is_not_reported(self):
        start = base_time()
        legs = [on_time(start + i * 60, id=f"t{i}") for i in range(6)]
        legs.append(on_time(start + 3600, id="later", situations=[notice(f"n{i}") for i in range(10)]))
        report = self.plan(trips(*legs))
        self.assertEqual(len(report["departures"]), 6)
        self.assertNotIn("noticesOmitted", report)

    def test_oversized_notice_text_is_cut_with_an_ellipsis(self):
        long = "ø" * 20_000
        stops = [{"__typename": "AffectedStopPlace", "stopPlace": {"name": f"Stop {i}"}} for i in range(5000)]
        situations = [notice(long, summary=[{"value": long}], description=[{"value": "d" + long}],
                             advice=[{"value": "a" + long}]),
                      notice("wide", affects=stops)]
        data = trips(leg(base_time(), situations=situations, line={"publicCode": long}, serviceJourney={"id": long},
                         fromEstimatedCall={"quay": {"publicCode": long}}))
        self.assertLess(len(json.dumps(data)), 2_000_000)
        report = self.plan(data)
        d = report["departures"][0]
        n, scope = d["notices"][0], report["routeNotices"][0]["scopeLabel"]
        for text, limit in ((n["id"], 100), (n["summary"], 200), (n["detail"], 600), (scope, 100), (d["id"], 100),
                            (d["line"], 20), (d["platform"], 20)):
            self.assertEqual((len(text), text[-1]), (limit, "…"), text)
        self.assertTrue(scope.startswith("Stop 0 · Stop 1 · Stop 2"))
        self.assertTrue(n["detail"].startswith("d" + "ø" * 10))
        self.assertNotIn("noticesOmitted", report)

    def test_missing_platform_and_realtime_are_explicit(self):
        d = self.plan(trips(leg(base_time(), fromEstimatedCall={})))["departures"][0]
        self.assertEqual(d["platform"], "—")
        self.assertFalse(d["realtime"])


class StorageTests(Case):
    def test_neutral_first_run(self):
        for args in ((), ("--force",), ("--offline",)):
            self.assertEqual(self.helper.json(*args), {"status": "unconfigured", "route": None, "departures": [],
                                                       "routeNotices": [], "updatedAt": 0, "stale": False,
                                                       "error": "", "errorCode": ""})
        self.assertEqual(self.entur.requests, [])

    def test_route_validation_sanitizes_station_labels(self):
        route = copy.deepcopy(ROUTE)
        route["from"]["name"] = " Central "
        route["from"]["label"] = "Search-only label"
        route["extra"] = True
        self.assertEqual(self.fetch("--offline", route=route)["route"], ROUTE)

    def test_route_validation_rejects_invalid_pairs(self):
        select = "Select both stations from search results."
        name = "Invalid station name."
        cases = [({}, select), ([], select), ({"from": ROUTE["from"], "to": ROUTE["from"]}, "Choose two different stations."),
                 ({"from": {"id": "bad", "name": "Central"}, "to": ROUTE["to"]}, select),
                 ({"from": {"id": "NSR:StopPlace:1x", "name": "Central"}, "to": ROUTE["to"]}, select),
                 ({"from": ROUTE["from"], "to": {"id": 2, "name": "Airport"}}, select),
                 ({"from": ROUTE["from"], "to": "NSR:StopPlace:2"}, select),
                 ({"from": {"id": "NSR:StopPlace:1", "name": " \t "}, "to": ROUTE["to"]}, name),
                 ({"from": {"id": "NSR:StopPlace:1", "name": "x" * 161}, "to": ROUTE["to"]}, name),
                 ({"from": {"id": "NSR:StopPlace:1", "name": "Oslo\nS"}, "to": ROUTE["to"]}, name),
                 ({"from": {"id": "NSR:StopPlace:1"}, "to": ROUTE["to"]}, name)]
        for route, message in cases:
            with self.subTest(route=route):
                report = self.fetch("--force", route=route)
                self.assertEqual(report, {"status": "error", "route": None, "departures": [], "routeNotices": [],
                                          "updatedAt": 0, "stale": False, "error": message, "errorCode": "invalid_route"})
        longest = {"from": {"id": "NSR:StopPlace:1", "name": "ø" * 160}, "to": ROUTE["to"]}
        self.assertEqual(self.fetch("--offline", route=longest)["errorCode"], "offline")
        self.assertEqual(self.entur.requests, [])

    def test_failed_refresh_retains_original_snapshot_time(self):
        self.entur.plan(busy(base_time()))
        original = self.fetch("--force")
        path = self.helper.cache_file()
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
        self.assertEqual(path.read_text(), python_json(original))
        aged = dict(original, updatedAt=original["updatedAt"] - 120)
        self.helper.write_cache(aged)
        self.entur.plan(Reply({"error": "down"}, status=503))
        stale = self.fetch()
        self.assertEqual(stale, dict(aged, status="stale", stale=True, error="Entur is unavailable. Try Refresh.",
                                     errorCode="http_error"))
        self.assertEqual(self.helper.read_cache(), aged)
        refused = self.refused()
        refused.write_cache(aged)
        report = refused.fetch("--force")
        self.assertEqual((report["status"], report["errorCode"], report["error"], report["updatedAt"]),
                         ("stale", "network_error", "Cannot reach Entur. Check your connection and try Refresh.",
                          aged["updatedAt"]))

    def test_cache_path_is_isolated_by_route_language_and_hours(self):
        reverse = {"from": ROUTE["to"], "to": ROUTE["from"]}
        names = {cache_name(ROUTE), cache_name(reverse), cache_name(ROUTE, "nb"), cache_name(ROUTE, "en", 1)}
        self.assertEqual(len(names), 4)
        self.fetch("--force")
        self.fetch("--force", route=reverse)
        self.fetch("--force", "--language", "nb")
        self.fetch("--force", "--hours", "1")
        self.assertEqual({p.name for p in self.helper.cache_dir.iterdir()}, names)

    def test_cache_directory_follows_xdg_cache_home_only_when_absolute(self):
        self.fetch("--force", env={"XDG_CACHE_HOME": "relative/cache"})
        fallback = self.helper.home / ".cache" / "foamy.train"
        self.assertTrue((fallback / cache_name()).is_file())
        self.fetch("--force", env={"XDG_CACHE_HOME": ""})
        self.fetch("--force", env={"XDG_CACHE_HOME": None})
        self.assertEqual(len(list(fallback.iterdir())), 1)
        self.assertFalse(self.helper.cache.exists())
        self.assertFalse((self.helper.root / "relative").exists())

    def test_fresh_cache_is_returned_as_stored(self):
        now = int(time.time())
        stored = {"status": "ok", "route": ROUTE, "departures": [], "routeNotices": [], "updatedAt": now - 10,
                  "stale": False, "error": "", "errorCode": "", "searchHours": 24, "extra": {"kept": ["ø"]}}
        path = self.helper.write_cache(stored)
        result = self.helper.run("--route-stdin", stdin=json.dumps(ROUTE))
        self.assertEqual((result.code, result.stderr, result.stdout), (0, b"", path.read_bytes()))
        self.assertEqual(self.entur.requests, [])
        self.helper.write_cache(dict(stored, updatedAt=now - 40))
        self.assertEqual(self.fetch()["updatedAt"], self.helper.read_cache()["updatedAt"])
        self.assertEqual(len(self.entur.requests), 2)

    def test_changing_hours_fetches_a_new_window_instead_of_reusing_short_cache(self):
        self.entur.fallback[API_PATH] = Reply(trips(leg(base_time())))
        self.fetch("--hours", "1")
        self.assertEqual(self.entur.windows(), [60])
        self.fetch("--hours", "24")
        # One train in the short window: widen to the full day.
        self.assertEqual(self.entur.windows(), [60, 180, 1440])
        self.fetch("--hours", "24")
        self.assertEqual(len(self.entur.requests), 3)

    def test_offline_never_requests_network(self):
        report = self.fetch("--offline")
        self.assertEqual(report, {"status": "error", "route": ROUTE, "departures": [], "routeNotices": [], "updatedAt": 0,
                                  "stale": False, "error": "Offline. Showing the last available update.",
                                  "errorCode": "offline"})
        self.fetch("--force")
        stale = self.fetch("--offline")
        self.assertEqual((stale["status"], stale["stale"], stale["errorCode"]), ("stale", True, "offline"))
        self.assertEqual(len(self.entur.requests), 2)

    def test_cache_expiry_and_corruption_do_not_block_refresh(self):
        for corrupt in (b"{", b'{"bad": 1}', b"[]", b"\xff", b" " * 2_000_001):
            self.helper.cache_dir.mkdir(parents=True, exist_ok=True)
            self.helper.cache_file().write_bytes(corrupt)
            self.assertEqual(self.fetch()["status"], "ok")
        old = dict(self.helper.read_cache(), updatedAt=int(time.time()) - 86401)
        self.helper.write_cache(old)
        self.assertEqual(self.fetch("--offline")["status"], "error")
        future = dict(old, updatedAt=int(time.time()) + 3600)
        self.helper.write_cache(future)
        self.assertEqual(self.fetch("--offline")["status"], "error")

    def test_invalid_snapshots_are_ignored(self):
        now = int(time.time())
        good = {"status": "ok", "route": ROUTE, "departures": [], "routeNotices": [], "updatedAt": now - 10,
                "stale": False, "error": "", "errorCode": ""}
        departure = {"id": "a", "line": "R10", "platform": "1", "aimedTime": "10:00", "expectedTime": "10:00",
                     "arrivalTime": "10:10", "aimed": now, "expected": now, "arrival": now, "delay": 0, "duration": 10,
                     "realtime": True, "cancelled": False, "notices": []}
        n = {"id": "n", "summary": "s", "detail": "", "scopeLabel": "", "kind": "info"}
        self.helper.write_cache(dict(good, departures=[dict(departure, notices=[n])], routeNotices=[n]))
        self.assertEqual(self.fetch("--offline")["status"], "stale")
        invalid = [dict(good, status="stale"), dict(good, route=ROUTE["from"]), dict(good, updatedAt=float(now)),
                   dict(good, updatedAt=True), dict(good, stale=0), dict(good, error=None), dict(good, departures={}),
                   dict(good, departures=[dict(departure, delay=1.0)]), dict(good, departures=[dict(departure, realtime=1)]),
                   dict(good, departures=[dict(departure, line=None)]), dict(good, departures=["x"]),
                   dict(good, routeNotices=[dict(n, kind="error")]),
                   dict(good, departures=[dict(departure, notices=[{"id": "n"}])]), dict(good, noticesOmitted=1)]
        for snapshot in invalid:
            with self.subTest(snapshot=snapshot):
                self.helper.write_cache(snapshot)
                self.assertEqual(self.fetch("--offline")["status"], "error")

    def test_an_older_oversized_snapshot_is_cut_when_read(self):
        # An older helper kept every notice at full length: the cache is read
        # back within the same limits, fresh or stale, and left as it is.
        now = int(time.time())
        long = "x" * 2000

        def n(identifier, text="s"):
            return {"id": identifier, "summary": text, "detail": text, "kind": "info", "scopeLabel": text}

        def departure(identifier, count):
            return {"id": identifier, "line": "R10", "platform": "1" * 50, "aimedTime": "10:00", "expectedTime": "10:00",
                    "arrivalTime": "10:10", "aimed": now, "expected": now, "arrival": now, "delay": 0, "duration": 10,
                    "realtime": True, "cancelled": False, "notices": [n(f"n{i}", long if i == 0 else "s") for i in range(count)]}
        old = {"status": "ok", "route": ROUTE, "departures": [departure(f"d{i}", 60) for i in range(10)],
               "routeNotices": [n("r"), n("r"), *(n(f"r{i}") for i in range(10_000))], "updatedAt": now - 10,
               "stale": False, "error": "", "errorCode": "", "searchHours": 24}
        path = self.helper.write_cache(old)
        stored = path.read_bytes()
        self.assertLess(len(stored), 2_000_000)
        fresh = self.fetch()
        stale = self.fetch("--offline")
        self.assertEqual(self.entur.requests, [])
        self.assertEqual(path.read_bytes(), stored)
        for report in (fresh, stale):
            self.assertEqual([d["id"] for d in report["departures"]], [f"d{i}" for i in range(6)])
            for d in report["departures"]:
                self.assertEqual([x["id"] for x in d["notices"]], ["n0", "n1", "n2"])
                self.assertEqual((len(d["platform"]), len(d["notices"][0]["detail"])), (20, 600))
            self.assertEqual([x["id"] for x in report["routeNotices"]], ["r", "r0", "r1", "r2", "r3"])
            self.assertIs(report["noticesOmitted"], True)
        self.assertEqual(stale, dict(fresh, status="stale", stale=True, error="Offline. Showing the last available update.",
                                     errorCode="offline"))
        # Within the limits, a snapshot is still returned byte for byte.
        self.helper.write_cache(fresh)
        result = self.helper.run("--route-stdin", stdin=json.dumps(ROUTE))
        self.assertEqual(result.stdout, path.read_bytes())

    def test_cache_write_failure_is_reported_with_the_departures(self):
        self.helper.cache.mkdir()
        self.helper.cache_dir.write_text("not a directory")
        self.entur.plan(busy(base_time()))
        report = self.fetch("--force")
        self.assertEqual((report["status"], len(report["departures"]), report["error"], report["errorCode"]),
                         ("ok", 6, "Could not save the local cache.", "cache_write"))

    def test_no_temporary_files_remain(self):
        self.fetch("--force")
        self.fetch("--force", "--language", "nb")
        self.assertEqual(sorted(p.name for p in self.helper.cache_dir.iterdir()),
                         sorted([cache_name(), cache_name(ROUTE, "nb")]))

    def test_busy_route_needs_only_the_short_window(self):
        self.entur.plan(busy(base_time()))
        report = self.fetch("--force")
        self.assertEqual(self.entur.windows(), [180])
        self.assertEqual(len(report["departures"]), 6)
        self.assertEqual(report["searchHours"], 3)
        self.assertNotIn("wideSince", report)

    def test_sparse_route_widens_and_remembers_when(self):
        self.entur.fallback[API_PATH] = Reply(trips(leg(base_time())))
        report = self.fetch("--force")
        self.assertEqual(self.entur.windows(), [180, 1440])
        self.assertEqual(list(report)[-2:], ["searchHours", "wideSince"])
        self.assertEqual((report["searchHours"], report["wideSince"]), (24, report["updatedAt"]))
        self.assertEqual(self.helper.read_cache(), report)

    def test_sparse_route_reuses_the_full_window_for_an_hour(self):
        self.entur.fallback[API_PATH] = Reply(trips(leg(base_time())))
        first = self.fetch("--force")
        since = first["wideSince"] - 600
        self.helper.write_cache(dict(first, updatedAt=first["updatedAt"] - 600, wideSince=since))
        report = self.fetch("--force")
        # Continuous polling refreshes updatedAt, but the hour counts from the first widening.
        self.assertEqual(self.entur.windows(), [180, 1440, 1440])
        self.assertEqual(report["wideSince"], since)
        self.helper.write_cache(dict(report, wideSince=int(time.time()) - 3605))
        report = self.fetch("--force")
        self.assertEqual(self.entur.windows()[3:], [180, 1440])
        self.assertLessEqual(abs(report["wideSince"] - time.time()), 5)
        for odd in ({"wideSince": 1.5}, {"wideSince": None}, {"searchHours": 3}, {"wideSince": int(time.time()) + 60}):
            self.helper.write_cache(dict(report, **odd))
            self.fetch("--force")
        self.assertEqual(self.entur.windows()[5:], [180, 1440] * 4)

    def test_short_look_ahead_uses_one_window(self):
        for hours in ("1", "3"):
            self.fetch("--force", "--hours", hours)
        self.assertEqual(self.entur.windows(), [60, 180])

    def test_failed_widening_keeps_the_short_window(self):
        for failure in (Reply({}, status=500), Reply(raw=b"nope"), Reply({"errors": ["x"]})):
            with self.subTest(failure=failure.data):
                self.entur.plan(trips(leg(base_time())), failure)
                report = self.fetch("--force")
                self.assertEqual((report["status"], len(report["departures"]), report["searchHours"], report["errorCode"]),
                                 ("ok", 1, 3, ""))

    def test_requests_share_one_budget_inside_the_widget_timeout(self):
        # 11 s for the short window leaves too little to widen: keep its answer instead of being killed.
        self.entur.plan(Reply(trips(leg(base_time())), delay=11))
        began = time.monotonic()
        report = self.fetch("--force")
        self.assertEqual(self.entur.windows(), [180])
        self.assertEqual((report["status"], len(report["departures"]), report["searchHours"]), ("ok", 1, 3))
        self.assertLess(time.monotonic() - began, 13)
        # 6 s leaves 8 s for the widening; a reply after 9 s is too late.
        self.entur.plan(Reply(trips(leg(base_time())), delay=6), Reply(busy(base_time()), delay=9))
        began = time.monotonic()
        report = self.fetch("--force")
        elapsed = time.monotonic() - began
        self.assertEqual(self.entur.windows()[1:], [180, 1440])
        self.assertEqual((report["status"], len(report["departures"]), report["searchHours"]), ("ok", 1, 3))
        self.assertTrue(13 <= elapsed < 16, elapsed)

    def test_read_route_is_bounded(self):
        text = json.dumps(ROUTE)
        self.assertEqual(self.fetch("--offline", route=text + " " * (4096 - len(text)))["route"], ROUTE)
        self.assertEqual(self.fetch("--offline", route=text + " " * (4097 - len(text)))["errorCode"], "invalid_route")


class SearchTests(Case):
    def search(self, text, *replies, **kwargs):
        self.entur.stations(*replies)
        return self.helper.json("--search=" + text, **kwargs)

    def test_request_shape(self):
        self.search(" Lillestrøm st/1&2 ", {"features": []})
        (request,) = self.entur.taken(GEOCODER_PATH)
        self.assertEqual((request["method"], request["body"]), ("GET", b""))
        self.assertEqual(request["query"], "q=Lillestr%C3%B8m+st%2F1%262&limit=8&stopPlaceTypes=railStation")
        self.assertEqual(request["headers"]["et-client-name"], CLIENT)
        self.assertEqual(request["headers"]["accept"], "application/json")
        self.assertEqual(request["headers"]["content-type"], "application/json")
        self.assertEqual(request["headers"]["host"], self.entur.url.split("//")[1])

    def test_query_length_is_checked_after_trimming(self):
        for text in ("", " a ", "x" * 101):
            self.assertEqual(self.search(text), {"status": "ok", "stations": []})
        self.assertEqual(self.entur.requests, [])
        self.search("ab")
        self.search("ø" * 100)
        self.assertEqual(len(self.entur.requests), 2)

    def test_search_labels_are_one_bounded_line(self):
        long = feature("NSR:StopPlace:12", "Central", "Central,\n" + "x" * 400)
        blank = feature("NSR:StopPlace:13", " Airport ", "\x00\x1f ")
        tabs = feature("NSR:StopPlace:14", "Ski", "Ski\t\t\x7fstasjon")
        stations = self.search("Central", {"features": [long, blank, tabs]})["stations"]
        self.assertEqual(len(stations[0]["label"]), 160)
        self.assertEqual((stations[0]["label"][:10], stations[0]["label"][-2:]), ("Central, x", "x…"))
        self.assertEqual(stations[1], {"id": "NSR:StopPlace:13", "name": "Airport", "label": "Airport"})
        self.assertEqual(stations[2]["label"], "Ski stasjon")

    def test_search_validates_and_deduplicates_stations(self):
        good = feature("NSR:StopPlace:12", "Central", "Central, City")
        names_text = {"properties": {"id": "NSR:StopPlace:17", "names": "Oslo", "stopPlaceTypes": ["railStation"]}}
        types_text = {"properties": {"id": "NSR:StopPlace:18", "names": {"default": "Ås"}, "stopPlaceTypes": "railStation"}}
        others = [good, {"properties": {"id": "not-an-id", "stopPlaceTypes": ["railStation"]}},
                  feature("NSR:StopPlace:15", "Bus", types=("onstreetBus",)), feature("NSR:StopPlace:16", "x" * 161),
                  names_text, {"properties": None}, types_text, "x", None]
        self.assertEqual(self.search("Central", {"features": others})["stations"],
                         [{"id": "NSR:StopPlace:12", "name": "Central", "label": "Central, City"}])

    def test_a_long_station_list_below_the_byte_cap_keeps_the_first_eight(self):
        features = [feature(f"NSR:StopPlace:{i // 2}", f"Station {i}") for i in range(10_000)]
        self.assertLess(len(json.dumps({"features": features})), 2_000_000)
        stations = self.search("Station", {"features": features})["stations"]
        self.assertEqual([s["id"] for s in stations], [f"NSR:StopPlace:{i}" for i in range(8)])
        self.assertEqual(stations[1]["name"], "Station 2")

    def test_search_query_starting_with_a_dash_is_not_an_option(self):
        found = self.search("-x", {"features": [feature("NSR:StopPlace:9", "-x Junction")]})
        self.assertEqual(self.entur.taken(GEOCODER_PATH)[0]["query"].split("&")[0], "q=-x")
        self.assertEqual(found["stations"][0]["name"], "-x Junction")

    def test_search_failures(self):
        invalid = {"status": "error", "route": None, "departures": [], "routeNotices": [], "updatedAt": 0, "stale": False,
                   "error": "Station search returned an invalid response.", "errorCode": "invalid_response"}
        self.assertEqual(self.search("Oslo", {"features": {}}), invalid)
        self.assertEqual(self.search("Oslo", Reply({}, status=502))["errorCode"], "http_error")
        self.assertEqual(self.search("Oslo", Reply(raw=b"<html>"))["errorCode"], "invalid_response")
        self.assertEqual(self.refused().json("--search=Oslo")["errorCode"], "network_error")


class NetworkTests(Case):
    def test_planner_request_shape(self):
        self.fetch("--force", "--hours", "2")
        (request,) = self.entur.taken(API_PATH)
        variables = {"from": "NSR:StopPlace:1", "to": "NSR:StopPlace:2", "searchWindow": 120}
        self.assertEqual(request["method"], "POST")
        self.assertEqual(request["body"], json.dumps({"query": QUERY, "variables": variables}).encode())
        self.assertEqual(request["headers"]["et-client-name"], CLIENT)
        self.assertEqual(request["headers"]["accept"], "application/json")
        self.assertEqual(request["headers"]["content-type"], "application/json")
        self.assertEqual(request["query"], "")

    def test_failures_map_to_codes(self):
        cases = [(Reply({}, status=500), "http_error"), (Reply({}, status=404), "http_error"),
                 (Reply(raw=b"not json"), "invalid_response"), (Reply([]), "invalid_response"),
                 (Reply(raw=b'{"a": 1} x'), "invalid_response"), (Reply(raw=b'{"a": "\xff"}'), "invalid_response")]
        for reply, code in cases:
            with self.subTest(code=code, data=reply.data[:20]):
                self.assertEqual(self.plan(reply)["errorCode"], code)

    def test_response_size_limit(self):
        def sized(size):
            head = b'{"data": {"trip": {"tripPatterns": []}}, "pad": "'
            return head + b"x" * (size - len(head) - 2) + b'"}'
        self.assertEqual(self.plan(Reply(raw=sized(2_000_000)))["status"], "ok")
        self.assertEqual(self.plan(Reply(raw=sized(2_000_001)))["errorCode"], "invalid_response")

    def test_redirect_is_followed_for_search(self):
        moved = GEOCODER_PATH + "?q=moved&limit=8&stopPlaceTypes=railStation"
        self.entur.stations(Reply({}, status=302, headers={"Location": moved}),
                            {"features": [feature("NSR:StopPlace:3", "Moved")]})
        self.assertEqual(self.helper.json("--search=Oslo")["stations"][0]["name"], "Moved")
        self.assertEqual([r["query"].split("&")[0] for r in self.entur.taken(GEOCODER_PATH)], ["q=Oslo", "q=moved"])


@unittest.skipUnless(CertAuthority.available, "needs the openssl CLI for a test CA")
class TlsProxyTests(unittest.TestCase):
    """HTTPS to a fake Entur on localhost: the system trust store (here
    SSL_CERT_FILE) and https_proxy/no_proxy as Python's urllib reads them."""

    @classmethod
    def setUpClass(cls):
        cls.dir = tempfile.TemporaryDirectory(prefix="foamy-train-ca-")
        cls.ca = CertAuthority(cls.dir.name)

    @classmethod
    def tearDownClass(cls):
        cls.dir.cleanup()

    def setUp(self):
        self.temp = temporary()
        self.addCleanup(self.temp.cleanup)
        self.entur = FakeEntur(tls=self.ca)
        self.addCleanup(self.entur.close)
        self.proxy = FakeProxy(("127.0.0.1", self.entur.port))
        self.addCleanup(self.proxy.close)
        self.helper = Helper(self.temp.name, self.entur.url)
        self.helper.env["SSL_CERT_FILE"] = str(self.ca.ca)
        self.entur.fallback[GEOCODER_PATH] = Reply({"features": [feature("NSR:StopPlace:7", "Secure")]})

    def search(self, **env):
        return self.helper.json("--search=Oslo", env=env)

    def test_https_with_the_trusted_test_ca(self):
        self.assertEqual(self.search()["stations"][0]["name"], "Secure")
        self.assertEqual(self.helper.fetch("--force")["status"], "ok")
        self.assertEqual(self.proxy.seen(), [])

    def test_untrusted_certificate_is_a_network_error(self):
        self.assertEqual(self.search(SSL_CERT_FILE=None)["errorCode"], "network_error")
        self.assertEqual(self.entur.requests, [])

    def test_https_proxy_tunnels_the_request(self):
        self.assertEqual(self.search(https_proxy=self.proxy.url)["stations"][0]["name"], "Secure")
        (tunnel,) = self.proxy.seen()
        self.assertEqual(tunnel["request"].split()[:2], ["CONNECT", f"localhost:{self.entur.port}"])
        self.assertNotIn("proxy-authorization", tunnel["headers"])
        self.assertEqual(self.entur.requests[0]["headers"]["host"], f"localhost:{self.entur.port}")

    def test_uppercase_proxy_and_credentials(self):
        self.search(HTTPS_PROXY=self.proxy.url.replace("http://", "http://user:p%40ss@"))
        self.search(https_proxy="127.0.0.1:%d" % self.proxy.port)
        first, second = self.proxy.seen()
        self.assertEqual(first["headers"]["proxy-authorization"], basic("user", "p@ss"))
        self.assertNotIn("proxy-authorization", second["headers"])

    def test_lowercase_wins_and_empty_lowercase_disables(self):
        self.search(https_proxy=self.proxy.url, HTTPS_PROXY="http://127.0.0.1:9")
        self.assertEqual(len(self.proxy.seen()), 1)
        self.assertEqual(self.search(https_proxy="", HTTPS_PROXY="http://127.0.0.1:9")["stations"][0]["name"], "Secure")
        self.assertEqual(self.search(http_proxy="http://127.0.0.1:9", all_proxy="http://127.0.0.1:9")["status"], "ok")
        self.assertEqual(len(self.proxy.seen()), 1)

    def test_no_proxy_bypasses_matching_hosts(self):
        for value in ("localhost", "*", "example.org, .LOCALHOST", f"localhost:{self.entur.port}", "host"):
            self.search(https_proxy=self.proxy.url, no_proxy=value)
        self.search(https_proxy=self.proxy.url, NO_PROXY="localhost")
        self.search(https_proxy=self.proxy.url, no_proxy="otherhost,calhost.x")
        # Suffixes match whole labels: "host" doesn't cover "localhost".
        self.assertEqual(len(self.proxy.seen()), 2)

    def test_unreachable_proxy_is_a_network_error(self):
        self.assertEqual(self.search(https_proxy="http://127.0.0.1:9")["errorCode"], "network_error")
        self.assertEqual(self.entur.requests, [])

    def test_trickling_proxy_reply_is_bounded_by_the_request_deadline(self):
        # Each byte arrives well within any per-read timeout; only the
        # request's 12 s deadline ends it, before the widget's 18 s timeout.
        slow = FakeProxy(("127.0.0.1", self.entur.port), trickle=True)
        self.addCleanup(slow.close)
        began = time.monotonic()
        report = self.search(https_proxy=slow.url)
        elapsed = time.monotonic() - began
        self.assertEqual(report["errorCode"], "network_error")
        self.assertEqual(len(slow.seen()), 1)
        self.assertEqual(self.entur.requests, [])
        self.assertTrue(11.5 <= elapsed < 14, elapsed)


if __name__ == "__main__":
    unittest.main()
