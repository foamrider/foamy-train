#!/usr/bin/env python3
"""Entur direct rail departures. No third-party dependencies or embedded route."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from datetime import datetime
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

API = "https://api.entur.io/journey-planner/v3/graphql"
GEOCODER = "https://api.entur.io/geocoder/v3/autocomplete"
CLIENT = "foamrider-foamy-train"
MAX_BYTES = 2_000_000
CACHE_SECONDS = 30
OSLO = ZoneInfo("Europe/Oslo")
NOTICE_FIELDS = """id reportType summary { language value } description { language value }
 advice { language value } affects { __typename
 ... on AffectedLine { line { publicCode } }
 ... on AffectedStopPlace { stopPlace { name } }
 ... on AffectedStopPlaceOnLine { line { publicCode } stopPlace { name } }
 }"""
# Entur currently returns no trips for maximumTransfers: 0. Bound the search to 1
# and enforce the one-rail-leg contract below before showing any journey.
# Use an explicit window: the automatic search can end before the next direct train.
QUERY = """query Departures($from: String!, $to: String!, $searchWindow: Int!) {
 trip(from: {place: $from}, to: {place: $to}, numTripPatterns: 12, searchWindow: $searchWindow,
 maximumTransfers: 1, includeRealtimeCancellations: true, includePlannedCancellations: true,
 modes: {transportModes: [{transportMode: rail}]}) {
 tripPatterns { legs { id mode aimedStartTime expectedStartTime aimedEndTime expectedEndTime realtime
 line { publicCode } serviceJourney { id }
 fromEstimatedCall { cancellation realtime quay { publicCode } situations { """ + NOTICE_FIELDS + """ } }
 toEstimatedCall { cancellation situations { """ + NOTICE_FIELDS + """ } }
 situations { """ + NOTICE_FIELDS + """ }
 } } } }"""


class TrainError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def directory(variable: str, fallback: str) -> Path:
    value = os.environ.get(variable, "")
    return Path(value if value and os.path.isabs(value) else Path.home() / fallback) / "foamy.train"


def read_json(path: Path) -> object:
    with path.open("rb") as handle:
        data = handle.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("File is too large")
    return json.loads(data)


def atomic_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = None
    try:
        fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=".train-")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if temporary and os.path.exists(temporary):
            os.unlink(temporary)


def station(value: object) -> dict:
    if not isinstance(value, dict):
        raise TrainError("invalid_route", "Select both stations from search results.")
    identifier, name = value.get("id"), value.get("name")
    if not isinstance(identifier, str) or not re.fullmatch(r"NSR:StopPlace:\d+", identifier):
        raise TrainError("invalid_route", "Select both stations from search results.")
    if not isinstance(name, str) or not name.strip() or len(name) > 160 or any(ord(c) < 32 for c in name):
        raise TrainError("invalid_route", "Invalid station name.")
    return {"id": identifier, "name": name.strip()}


def validate_route(value: object) -> dict:
    if not isinstance(value, dict):
        raise TrainError("invalid_route", "Select both stations from search results.")
    route = {key: station(value.get(key)) for key in ("from", "to")}
    if route["from"]["id"] == route["to"]["id"]:
        raise TrainError("invalid_route", "Choose two different stations.")
    return route


def route_identity(route: dict) -> str:
    return route["from"]["id"] + "/" + route["to"]["id"]


def request_json(url: str, payload: dict | None = None) -> dict:
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=body, headers={"ET-Client-Name": CLIENT, "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=12) as response:
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise ValueError("Response too large")
        result = json.loads(data)
        if not isinstance(result, dict):
            raise ValueError("Expected object")
        return result
    except HTTPError as error:
        raise TrainError("http_error", "Entur is unavailable. Try Refresh.") from error
    except (URLError, TimeoutError, OSError) as error:
        raise TrainError("network_error", "Cannot reach Entur. Check your connection and try Refresh.") from error
    except (ValueError, UnicodeError) as error:
        raise TrainError("invalid_response", "Entur returned an invalid response. Try Refresh.") from error


def search(query: str) -> list[dict]:
    query = query.strip()
    if not 2 <= len(query) <= 100:
        return []
    data = request_json(GEOCODER + "?" + urlencode({"q": query, "limit": 8, "stopPlaceTypes": "railStation"}))
    features = data.get("features")
    if not isinstance(features, list):
        raise TrainError("invalid_response", "Station search returned an invalid response.")
    results, seen = [], set()
    for feature in features:
        if not isinstance(feature, dict):
            continue
        props = feature.get("properties", {})
        if not isinstance(props, dict) or not isinstance(props.get("stopPlaceTypes"), list) or "railStation" not in props["stopPlaceTypes"]:
            continue
        names = props.get("names") or {}
        try:
            item = station({"id": props.get("id"), "name": names.get("default")})
        except (TrainError, AttributeError):
            continue
        if item["id"] in seen:
            continue
        seen.add(item["id"])
        item["label"] = str(names.get("display") or item["name"])
        results.append(item)
    return results


def localized(values: object, language: str) -> str:
    if not isinstance(values, list):
        return ""
    texts = [v for v in values if isinstance(v, dict) and isinstance(v.get("value"), str)]
    for locale in (language, "no" if language == "nb" else "en", "nb", "en"):
        for value in texts:
            if value.get("language") == locale:
                return value["value"].strip()
    return texts[0]["value"].strip() if texts else ""


def notices(values: object, language: str) -> tuple[list, list]:
    departures, broader, seen = [], [], set()
    if not isinstance(values, list):
        return departures, broader
    for value in values:
        if not isinstance(value, dict):
            continue
        summary = localized(value.get("summary"), language)
        description = localized(value.get("description"), language)
        advice = localized(value.get("advice"), language)
        summary = summary or description or advice
        if not summary:
            continue
        detail = "\n\n".join(dict.fromkeys(t for t in (description, advice) if t and t != summary))
        identity = str(value.get("id") or summary + detail)
        if identity in seen:
            continue
        seen.add(identity)
        affected = value.get("affects") or []
        # Repeated wording is not evidence of route scope. Unknown/mixed scope stays per departure.
        wide = bool(affected) and all(isinstance(a, dict) and a.get("__typename") in ("AffectedLine", "AffectedStopPlace", "AffectedStopPlaceOnLine") for a in affected)
        labels = []
        if wide:
            for affected_entity in affected:
                for field, key in (("line", "publicCode"), ("stopPlace", "name")):
                    entity = affected_entity.get(field) or {}
                    if entity.get(key) and entity[key] not in labels:
                        labels.append(entity[key])
        notice = {"id": identity, "summary": summary, "detail": detail,
                  "kind": "info" if value.get("reportType") == "general" else "warning",
                  "scopeLabel": " · ".join(labels)}
        (broader if wide else departures).append(notice)
    return departures, broader


def timestamp(value: object) -> int:
    if not isinstance(value, str):
        raise ValueError("Missing time")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Missing timezone")
    return int(parsed.timestamp())


def time_label(epoch: int) -> str:
    return datetime.fromtimestamp(epoch, OSLO).strftime("%H:%M")


def parse_response(data: dict, route: dict, language: str, now: int, look_ahead_hours: int = 24) -> dict:
    if data.get("errors"):
        raise TrainError("api_error", "Entur could not find departures. Try Refresh.")
    try:
        patterns = data["data"]["trip"]["tripPatterns"]
        if not isinstance(patterns, list):
            raise ValueError("Missing patterns")
        departures, route_notices, seen, seen_notices = [], [], set(), set()
        for pattern in patterns:
            legs = pattern["legs"]
            # One rail leg only: never present the first leg of a transfer or a replacement bus as a direct train.
            if not isinstance(legs, list) or len(legs) != 1 or legs[0].get("mode") != "rail":
                continue
            leg = legs[0]
            aimed = timestamp(leg["aimedStartTime"])
            expected = timestamp(leg["expectedStartTime"])
            arrival = timestamp(leg["expectedEndTime"])
            start = leg.get("fromEstimatedCall") or {}
            end = leg.get("toEstimatedCall") or {}
            cancelled = start.get("cancellation") is True or end.get("cancellation") is True
            # Enforce the selected limit even if routing returns a delayed trip beyond its window.
            if max(aimed, expected) < now - 60 or expected > now + look_ahead_hours * 3600:
                continue
            identity = str((leg.get("serviceJourney") or {}).get("id") or leg.get("id") or "") + ":" + str(aimed)
            if identity in seen:
                continue
            seen.add(identity)
            local_notices, wide_notices = notices((leg.get("situations") or []) + (start.get("situations") or []) + (end.get("situations") or []), language)
            for notice in wide_notices:
                if notice["id"] not in seen_notices:
                    route_notices.append(notice)
                    seen_notices.add(notice["id"])
            departures.append({"id": identity, "line": str((leg.get("line") or {}).get("publicCode") or "—"),
                "aimed": aimed, "expected": expected, "arrival": arrival, "aimedTime": time_label(aimed),
                "expectedTime": time_label(expected), "arrivalTime": time_label(arrival),
                "delay": max(0, (expected - aimed) // 60), "duration": max(0, (arrival - expected) // 60),
                "platform": str((start.get("quay") or {}).get("publicCode") or "—"),
                "realtime": start.get("realtime") is True, "cancelled": cancelled, "notices": local_notices})
        departures.sort(key=lambda d: (d["expected"], d["aimed"]))
        return {"status": "ok", "route": route, "departures": departures[:6], "routeNotices": route_notices,
                "updatedAt": now, "stale": False, "error": "", "errorCode": ""}
    except (KeyError, TypeError, ValueError, AttributeError) as error:
        raise TrainError("invalid_response", "Entur returned an invalid response. Try Refresh.") from error


def cache_path(route: dict, language: str, look_ahead_hours: int = 24) -> Path:
    # A short-window snapshot must not hide departures after the user expands the search.
    key = hashlib.sha256((route_identity(route) + "/" + language + "/" + str(look_ahead_hours)).encode()).hexdigest()
    return directory("XDG_CACHE_HOME", ".cache") / (key + ".json")


def empty(status: str, route: dict | None = None) -> dict:
    return {"status": status, "route": route, "departures": [], "routeNotices": [], "updatedAt": 0, "stale": False, "error": "", "errorCode": ""}


def valid_snapshot(value: object, route: dict, now: int) -> bool:
    if not isinstance(value, dict) or value.get("route") != route or value.get("status") != "ok":
        return False
    if type(value.get("updatedAt")) is not int or not 0 <= now - value["updatedAt"] <= 86400:
        return False
    if not isinstance(value.get("departures"), list) or not isinstance(value.get("routeNotices"), list):
        return False
    if not isinstance(value.get("error"), str) or not isinstance(value.get("errorCode"), str) or type(value.get("stale")) is not bool:
        return False
    all_notices = list(value["routeNotices"])
    for departure in value["departures"]:
        if not isinstance(departure, dict):
            return False
        if not all(isinstance(departure.get(k), str) for k in ("id", "line", "platform", "aimedTime", "expectedTime", "arrivalTime")):
            return False
        if not all(type(departure.get(k)) is int for k in ("aimed", "expected", "arrival", "delay", "duration")):
            return False
        if not all(type(departure.get(k)) is bool for k in ("realtime", "cancelled")) or not isinstance(departure.get("notices"), list):
            return False
        all_notices.extend(departure["notices"])
    return all(isinstance(n, dict) and all(isinstance(n.get(k), str) for k in ("id", "summary", "detail", "scopeLabel"))
               and n.get("kind") in ("info", "warning") for n in all_notices)


def fetch(route: dict | None, language: str, force: bool = False, offline: bool = False, look_ahead_hours: int = 24) -> dict:
    if type(look_ahead_hours) is not int or not 1 <= look_ahead_hours <= 24:
        raise TrainError("invalid_setting", "Choose between 1 and 24 hours.")
    if route is None:
        return empty("unconfigured")
    now, cached = int(time.time()), None
    path = cache_path(route, language, look_ahead_hours)
    try:
        candidate = read_json(path)
        if valid_snapshot(candidate, route, now):
            cached = candidate
    except (OSError, ValueError):
        # Cache corruption must not prevent a fresh request; route config errors are handled separately.
        pass
    if cached and not force and not offline and now - cached["updatedAt"] < CACHE_SECONDS:
        return cached
    try:
        if offline:
            raise TrainError("offline", "Offline. Showing the last available update.")
        report = parse_response(request_json(API, {"query": QUERY, "variables": {"from": route["from"]["id"], "to": route["to"]["id"], "searchWindow": look_ahead_hours * 60}}), route, language, now, look_ahead_hours)
        try:
            atomic_json(path, report)
        except OSError:
            report["error"] = "Could not save the local cache."
            report["errorCode"] = "cache_write"
        return report
    except TrainError as error:
        report = dict(cached) if cached else empty("error", route)
        report.update(status="stale" if cached else "error", stale=bool(cached), error=str(error), errorCode=error.code)
        return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--search")
    parser.add_argument("--route", help="Station pair from the widget entry in shell.json (JSON)")
    parser.add_argument("--language", choices=("en", "nb"), default="en")
    parser.add_argument("--hours", type=int, choices=range(1, 25), default=24, help="Look ahead 1–24 hours")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    try:
        if args.search is not None:
            result = {"status": "ok", "stations": search(args.search)}
        else:
            route = validate_route(json.loads(args.route)) if args.route is not None else None
            result = fetch(route, args.language, args.force, args.offline, args.hours)
    except TrainError as error:
        result = dict(empty("error"), error=str(error), errorCode=error.code)
    except (OSError, ValueError) as error:
        result = dict(empty("error"), error="Invalid route or unavailable local cache. Select the stations again.", errorCode="invalid_input")
    json.dump(result, sys.stdout, ensure_ascii=False)
    print()


if __name__ == "__main__":
    main()
