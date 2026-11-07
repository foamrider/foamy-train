//! Entur data: station validation, geocoder results, journey-planner
//! answers and their service notices. The rules (and the order in which
//! fields are read, so the same inputs fail) are train_fetch.py's.

use std::fs::File;
use std::io::Read;
use std::sync::OnceLock;

use jiff::Timestamp;
use jiff::tz::TimeZone;
use serde_json::{Map, Value, json};

use crate::py::{self, Dict};
use crate::{Failure, TrainError};

pub const MAX_LABEL: usize = 160;
pub const MAX_DEPARTURES: usize = 6;
const MAX_TZIF: u64 = 256 * 1024;
/// Python's zoneinfo search path (sysconfig TZPATH, then its built-in default).
const ZONEINFO: [&str; 4] = [
    "/usr/share/zoneinfo",
    "/usr/lib/zoneinfo",
    "/usr/share/lib/zoneinfo",
    "/etc/zoneinfo",
];

const SELECT: TrainError =
    TrainError::new("invalid_route", "Select both stations from search results.");
const BAD_NAME: TrainError = TrainError::new("invalid_route", "Invalid station name.");
const SAME: TrainError = TrainError::new("invalid_route", "Choose two different stations.");
pub const INVALID: TrainError = TrainError::new(
    "invalid_response",
    "Entur returned an invalid response. Try Refresh.",
);
const BAD_SEARCH: TrainError = TrainError::new(
    "invalid_response",
    "Station search returned an invalid response.",
);
const API_ERROR: TrainError =
    TrainError::new("api_error", "Entur could not find departures. Try Refresh.");

pub type Object = Map<String, Value>;

/// `NSR:StopPlace:<digits>` (ASCII digits).
fn valid_id(id: &str) -> bool {
    id.strip_prefix("NSR:StopPlace:")
        .is_some_and(|digits| !digits.is_empty() && digits.bytes().all(|b| b.is_ascii_digit()))
}

/// A station from the widget or the geocoder: `{"id", "name"}` with the
/// name trimmed.
pub fn station(value: Option<&Value>) -> Result<Object, TrainError> {
    let Some(Value::Object(value)) = value else {
        return Err(SELECT);
    };
    let id = match value.get("id") {
        Some(Value::String(id)) if valid_id(id) => id,
        _ => return Err(SELECT),
    };
    let name = match value.get("name") {
        Some(Value::String(name)) => name,
        _ => return Err(BAD_NAME),
    };
    let trimmed = py::strip(name);
    if trimmed.is_empty() || py::len(name) > 160 || name.chars().any(|c| (c as u32) < 32) {
        return Err(BAD_NAME);
    }
    let mut out = Object::new();
    out.insert("id".into(), Value::String(id.clone()));
    out.insert("name".into(), Value::String(trimmed.to_owned()));
    Ok(out)
}

/// The station pair: `{"from": station, "to": station}`, two different ids.
pub fn validate_route(value: &Value) -> Result<Value, TrainError> {
    let Value::Object(value) = value else {
        return Err(SELECT);
    };
    let from = station(value.get("from"))?;
    let to = station(value.get("to"))?;
    if from["id"] == to["id"] {
        return Err(SAME);
    }
    Ok(json!({"from": from, "to": to}))
}

/// Entur's free-text display label as one bounded line: runs of control
/// characters become one space, then trim; empty falls back to the name.
fn label(value: Option<&Value>, fallback: &str) -> String {
    let mut text = String::new();
    if let Some(Value::String(value)) = value {
        let mut in_run = false;
        for c in value.chars() {
            if (c as u32) < 0x20 || c == '\u{7f}' {
                if !in_run {
                    text.push(' ');
                }
                in_run = true;
            } else {
                text.push(c);
                in_run = false;
            }
        }
    }
    let text = py::strip(&text);
    py::truncate(if text.is_empty() { fallback } else { text }, MAX_LABEL).to_owned()
}

/// Geocoder features → rail stations `{"id", "name", "label"}`, deduplicated.
pub fn stations(data: &Object) -> Result<Vec<Value>, TrainError> {
    let Some(Value::Array(features)) = data.get("features") else {
        return Err(BAD_SEARCH);
    };
    let mut results = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    for feature in features {
        let Value::Object(feature) = feature else {
            continue;
        };
        let props = match feature.get("properties") {
            None => continue, // the default `{}` has no stopPlaceTypes
            Some(Value::Object(props)) => props,
            Some(_) => continue,
        };
        match props.get("stopPlaceTypes") {
            Some(Value::Array(types)) if types.iter().any(|t| t == "railStation") => {}
            _ => continue,
        }
        // `names.get` on a truthy non-dict raises AttributeError: skipped.
        let names = Dict::or_empty(props.get("names"));
        let Ok(default) = names.get("default") else {
            continue;
        };
        let candidate = json!({"id": props.get("id"), "name": default});
        let Ok(mut item) = station(Some(&candidate)) else {
            continue;
        };
        let id = item["id"].as_str().unwrap_or_default().to_owned();
        if seen.contains(&id) {
            continue;
        }
        let name = item["name"].as_str().unwrap_or_default().to_owned();
        item.insert(
            "label".into(),
            Value::String(label(names.get("display").ok().flatten(), &name)),
        );
        seen.push(id);
        results.push(Value::Object(item));
    }
    Ok(results)
}

/// The text in `language`, else Norwegian (for `nb`) or English, else the
/// first text; trimmed.
fn localized(values: Option<&Value>, language: &str) -> String {
    let Some(Value::Array(values)) = values else {
        return String::new();
    };
    let texts: Vec<&Object> = values
        .iter()
        .filter_map(|v| match v {
            Value::Object(v) if matches!(v.get("value"), Some(Value::String(_))) => Some(v),
            _ => None,
        })
        .collect();
    let second = if language == "nb" { "no" } else { "en" };
    for locale in [language, second, "nb", "en"] {
        for value in &texts {
            if value.get("language").and_then(Value::as_str) == Some(locale) {
                return py::strip(value["value"].as_str().unwrap_or_default()).to_owned();
            }
        }
    }
    texts
        .first()
        .map(|v| py::strip(v["value"].as_str().unwrap_or_default()).to_owned())
        .unwrap_or_default()
}

const WIDE_TYPES: [&str; 3] = [
    "AffectedLine",
    "AffectedStopPlace",
    "AffectedStopPlaceOnLine",
];

/// Notices → (per departure, route-wide). Route-wide only when every
/// affected entity is a line or stop place; repeated wording is not scope.
fn notices(values: &[&Value], language: &str) -> Result<(Vec<Value>, Vec<Value>), TrainError> {
    let (mut departures, mut broader, mut seen) = (Vec::new(), Vec::new(), Vec::<String>::new());
    for value in values {
        let Value::Object(value) = value else {
            continue;
        };
        let description = localized(value.get("description"), language);
        let advice = localized(value.get("advice"), language);
        let mut summary = localized(value.get("summary"), language);
        if summary.is_empty() {
            summary = if description.is_empty() {
                advice.clone()
            } else {
                description.clone()
            };
        }
        if summary.is_empty() {
            continue;
        }
        let mut details: Vec<&str> = Vec::new();
        for text in [&description, &advice] {
            if !text.is_empty() && *text != summary && !details.contains(&text.as_str()) {
                details.push(text);
            }
        }
        let detail = details.join("\n\n");
        let identity = match py::or_none(value.get("id")) {
            Some(id) => py::str_of(id),
            None => format!("{summary}{detail}"),
        };
        if seen.contains(&identity) {
            continue;
        }
        seen.push(identity.clone());
        let affected = py::or_none(value.get("affects"));
        let wide = match affected {
            None => false,
            Some(Value::Array(items)) => items.iter().all(|a| {
                matches!(a, Value::Object(a) if a.get("__typename").and_then(Value::as_str).is_some_and(|t| WIDE_TYPES.contains(&t)))
            }),
            // Iterating a dict or a string yields strings: never wide.
            Some(Value::Object(_) | Value::String(_)) => false,
            // `for a in 5` raises TypeError.
            Some(_) => return Err(INVALID),
        };
        let mut labels: Vec<String> = Vec::new();
        if wide {
            for entity in affected.and_then(Value::as_array).into_iter().flatten() {
                for (field, key) in [("line", "publicCode"), ("stopPlace", "name")] {
                    let named = Dict::or_empty(entity.get(field))
                        .get(key)
                        .map_err(|()| INVALID)?;
                    match py::or_none(named) {
                        None => {}
                        Some(Value::String(text)) => {
                            if !labels.contains(text) {
                                labels.push(text.clone());
                            }
                        }
                        // " · ".join() of a non-string raises TypeError.
                        Some(_) => return Err(INVALID),
                    }
                }
            }
        }
        let kind = if value.get("reportType").and_then(Value::as_str) == Some("general") {
            "info"
        } else {
            "warning"
        };
        let notice = json!({"id": identity, "summary": summary, "detail": detail, "kind": kind,
                            "scopeLabel": labels.join(" · ")});
        if wide {
            broader.push(notice)
        } else {
            departures.push(notice)
        }
    }
    Ok((departures, broader))
}

/// Unix seconds of an ISO 8601 date-time with a UTC offset, truncated
/// toward zero like `int(datetime.fromisoformat(...).timestamp())`.
pub fn timestamp(value: Option<&Value>) -> Result<i64, TrainError> {
    let Some(Value::String(text)) = value else {
        return Err(INVALID);
    };
    parse_iso(&text.replace('Z', "+00:00")).ok_or(INVALID)
}

fn digits(text: &[char], at: usize, count: usize) -> Option<i64> {
    let slice = text.get(at..at + count)?;
    slice.iter().try_fold(0i64, |n, c| {
        c.to_digit(10)
            .filter(|_| c.is_ascii_digit())
            .map(|d| n * 10 + i64::from(d))
    })
}

/// `HH[[:]MM[[:]SS[{.,}f…]]]` → (hours, minutes, seconds, microseconds).
fn clock(text: &[char]) -> Option<(i64, i64, i64, i64)> {
    let mut parts = [0i64; 3];
    let mut pos = 0;
    let mut separated = false;
    for (index, part) in parts.iter_mut().enumerate() {
        *part = digits(text, pos, 2)?;
        pos += 2;
        if pos == text.len() || index == 2 {
            break;
        }
        if index == 0 {
            separated = text[pos] == ':';
        }
        if separated {
            if text[pos] != ':' {
                return None;
            }
            pos += 1;
        } else if !text[pos].is_ascii_digit() {
            break;
        }
    }
    let mut micros = 0;
    if pos < text.len() {
        if !matches!(text[pos], '.' | ',') {
            return None;
        }
        let fraction = &text[pos + 1..];
        if fraction.is_empty() || !fraction.iter().all(char::is_ascii_digit) {
            return None;
        }
        let used: String = fraction.iter().take(6).collect();
        micros = used.parse::<i64>().ok()? * 10i64.pow(6 - used.len() as u32);
    }
    Some((parts[0], parts[1], parts[2], micros))
}

fn days_from_civil(year: i64, month: i64, day: i64) -> i64 {
    let y = if month <= 2 { year - 1 } else { year };
    let era = y.div_euclid(400);
    let yoe = y - era * 400;
    let mp = (month + 9) % 12;
    let doy = (153 * mp + 2) / 5 + day - 1;
    let doe = yoe * 365 + yoe / 4 - yoe / 100 + doy;
    era * 146_097 + doe - 719_468
}

fn month_days(year: i64, month: i64) -> i64 {
    match month {
        2 if (year % 4 == 0 && year % 100 != 0) || year % 400 == 0 => 29,
        2 => 28,
        4 | 6 | 9 | 11 => 30,
        _ => 31,
    }
}

/// `YYYY-MM-DD`, any one separator character, a clock time and a required
/// `±HH[[:]MM[[:]SS[.f…]]]` offset.
fn parse_iso(text: &str) -> Option<i64> {
    let chars: Vec<char> = text.chars().collect();
    let year = digits(&chars, 0, 4)?;
    let month = digits(&chars, 5, 2)?;
    let day = digits(&chars, 8, 2)?;
    if chars[4] != '-' || chars[7] != '-' || chars.len() < 11 {
        return None;
    }
    if !(1..=9999).contains(&year)
        || !(1..=12).contains(&month)
        || !(1..=month_days(year, month)).contains(&day)
    {
        return None;
    }
    let time = &chars[11..];
    let sign_at = time.iter().position(|c| matches!(c, '+' | '-'))?;
    let (hour, minute, second, micros) = clock(&time[..sign_at])?;
    let (oh, om, os, ou) = clock(&time[sign_at + 1..])?;
    let midnight_next = hour == 24 && minute == 0 && second == 0 && micros == 0;
    if !(hour < 24 || midnight_next) || minute > 59 || second > 59 || om > 59 || os > 59 {
        return None;
    }
    let offset = ((oh * 60 + om) * 60 + os) * 1_000_000 + ou;
    if offset >= 86_400 * 1_000_000 {
        return None;
    }
    let offset = if time[sign_at] == '-' {
        -offset
    } else {
        offset
    };
    let seconds = days_from_civil(year, month, day) * 86_400 + hour * 3600 + minute * 60 + second;
    Some((seconds * 1_000_000 + micros - offset) / 1_000_000)
}

fn oslo() -> Result<&'static TimeZone, Failure> {
    static OSLO: OnceLock<Option<TimeZone>> = OnceLock::new();
    OSLO.get_or_init(|| {
        ZONEINFO.iter().find_map(|dir| {
            let mut data = Vec::new();
            File::open(format!("{dir}/Europe/Oslo"))
                .ok()?
                .take(MAX_TZIF)
                .read_to_end(&mut data)
                .ok()?;
            TimeZone::tzif("Europe/Oslo", &data).ok()
        })
    })
    .as_ref()
    .ok_or(Failure::Internal)
}

/// `HH:MM` in Europe/Oslo.
pub fn time_label(epoch: i64) -> Result<String, Failure> {
    let zoned = Timestamp::from_second(epoch)
        .map_err(|_| Failure::Train(INVALID))?
        .to_zoned(oslo()?.clone());
    Ok(format!("{:02}:{:02}", zoned.hour(), zoned.minute()))
}

/// `x[key]` on a parsed value; anything but a dict holding `key` raises.
fn index<'a>(value: &'a Value, key: &str) -> Result<&'a Value, TrainError> {
    value
        .as_object()
        .and_then(|map| map.get(key))
        .ok_or(INVALID)
}

/// `(a or []) + (b or []) + …`: each part falsy or a list.
fn concat<'a>(parts: &[Option<&'a Value>]) -> Result<Vec<&'a Value>, TrainError> {
    let mut out = Vec::new();
    for part in parts {
        match py::or_none(*part) {
            None => {}
            Some(Value::Array(items)) => out.extend(items),
            Some(_) => return Err(INVALID),
        }
    }
    Ok(out)
}

fn text_or_dash(value: Option<&Value>) -> String {
    py::or_none(value).map_or_else(|| "—".to_owned(), py::str_of)
}

/// A journey-planner answer → the report: direct rail departures only.
pub fn parse_response(
    data: &Object,
    route: &Value,
    language: &str,
    now: i64,
    hours: i64,
) -> Result<Object, Failure> {
    if py::truthy(data.get("errors")) {
        return Err(Failure::Train(API_ERROR));
    }
    let wrap = |e: TrainError| Failure::Train(e);
    let patterns = index(
        index(data.get("data").ok_or(INVALID).map_err(wrap)?, "trip").map_err(wrap)?,
        "tripPatterns",
    )
    .map_err(wrap)?;
    let Value::Array(patterns) = patterns else {
        return Err(Failure::Train(INVALID));
    };
    let bad = |()| Failure::Train(INVALID);
    let mut departures: Vec<(i64, i64, Value)> = Vec::new();
    let (mut route_notices, mut seen, mut seen_notices) =
        (Vec::new(), Vec::<String>::new(), Vec::<String>::new());
    for pattern in patterns {
        let legs = index(pattern, "legs").map_err(wrap)?;
        // One rail leg only: never the first leg of a transfer or a replacement bus.
        let Value::Array(legs) = legs else { continue };
        if legs.len() != 1 {
            continue;
        }
        let Value::Object(leg) = &legs[0] else {
            return Err(Failure::Train(INVALID));
        };
        if leg.get("mode").and_then(Value::as_str) != Some("rail") {
            continue;
        }
        let aimed =
            timestamp(Some(index(&legs[0], "aimedStartTime").map_err(wrap)?)).map_err(wrap)?;
        let expected =
            timestamp(Some(index(&legs[0], "expectedStartTime").map_err(wrap)?)).map_err(wrap)?;
        let arrival =
            timestamp(Some(index(&legs[0], "expectedEndTime").map_err(wrap)?)).map_err(wrap)?;
        let start = Dict::or_empty(leg.get("fromEstimatedCall"));
        let end = Dict::or_empty(leg.get("toEstimatedCall"));
        let cancelled = py::is_true(start.get("cancellation").map_err(bad)?)
            || py::is_true(end.get("cancellation").map_err(bad)?);
        // The selected look-ahead holds even if routing returns a later delayed trip.
        if aimed.max(expected) < now - 60 || expected > now + hours * 3600 {
            continue;
        }
        let journey = Dict::or_empty(leg.get("serviceJourney"))
            .get("id")
            .map_err(bad)?;
        let name = py::or_none(journey)
            .or_else(|| py::or_none(leg.get("id")))
            .map(py::str_of)
            .unwrap_or_default();
        let identity = format!("{name}:{aimed}");
        if seen.contains(&identity) {
            continue;
        }
        seen.push(identity.clone());
        let situations = concat(&[
            leg.get("situations"),
            start.get("situations").map_err(bad)?,
            end.get("situations").map_err(bad)?,
        ])
        .map_err(wrap)?;
        let (local, wide) = notices(&situations, language).map_err(wrap)?;
        for notice in wide {
            let id = notice["id"].as_str().unwrap_or_default().to_owned();
            if !seen_notices.contains(&id) {
                seen_notices.push(id);
                route_notices.push(notice);
            }
        }
        let line = Dict::or_empty(leg.get("line"))
            .get("publicCode")
            .map_err(bad)?;
        let quay = Dict::or_empty(start.get("quay").map_err(bad)?)
            .get("publicCode")
            .map_err(bad)?;
        let departure = json!({
            "id": identity, "line": text_or_dash(line), "aimed": aimed, "expected": expected, "arrival": arrival,
            "aimedTime": time_label(aimed)?, "expectedTime": time_label(expected)?, "arrivalTime": time_label(arrival)?,
            "delay": 0.max((expected - aimed).div_euclid(60)), "duration": 0.max((arrival - expected).div_euclid(60)),
            "platform": text_or_dash(quay), "realtime": py::is_true(start.get("realtime").map_err(bad)?),
            "cancelled": cancelled, "notices": local,
        });
        departures.push((expected, aimed, departure));
    }
    departures.sort_by_key(|(expected, aimed, _)| (*expected, *aimed));
    let departures: Vec<Value> = departures
        .into_iter()
        .take(MAX_DEPARTURES)
        .map(|(_, _, d)| d)
        .collect();
    let report = json!({"status": "ok", "route": route, "departures": departures, "routeNotices": route_notices,
                        "updatedAt": now, "stale": false, "error": "", "errorCode": ""});
    match report {
        Value::Object(report) => Ok(report),
        _ => unreachable!("json! of an object literal is an object"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn route() -> Value {
        json!({"from": {"id": "NSR:StopPlace:1", "name": "Central"}, "to": {"id": "NSR:StopPlace:2", "name": "Airport"}})
    }

    #[test]
    fn iso_timestamps_follow_fromisoformat() {
        let ok = [
            ("2026-09-26T09:12:00+02:00", 1790406720),
            ("2026-09-26 09:12:00+02:00", 1790406720),
            ("2026-09-26x09:12:00+02:00", 1790406720),
            ("2026-09-26ø09:12:00+02:00", 1790406720),
            ("2026-09-26T09:12+02:00", 1790406720),
            ("2026-09-26T09+02:00", 1790406000),
            ("2026-09-26T0912+0200", 1790406720),
            ("2026-09-26T091200+02", 1790406720),
            ("2026-09-26T09:12:00.5+02:00", 1790406720),
            ("2026-09-26T09:12:00,5+02:00", 1790406720),
            ("2026-09-26T09:12:00.1234567+02:00", 1790406720),
            ("2026-09-26T09:12:00+02:00:30", 1790406690),
            ("2026-09-26T09:12:00+02:00:30.5", 1790406689),
            ("2026-09-26T24:00:00+00:00", 1790467200),
            ("2026-09-26T09:12:00-23:59", 1790500260),
            ("2024-02-29T00:00:00+00:00", 1709164800),
            ("2026-09-26T09:12:00.000000001+00:00", 1790413920),
            ("2026-09-26T09:12:00-00:00", 1790413920),
            ("2026-09-26T09:12:00.5+0200", 1790406720),
        ];
        for (text, epoch) in ok {
            assert_eq!(parse_iso(text), Some(epoch), "{text}");
        }
        let bad = [
            "2026-09-26T09:12:60+00:00",
            "2026-09-26T09:12:00+24:00",
            "2026-09-26T09:12:00+0",
            "2026-09-26T09:12:00.+02:00",
            "2026-09-26T9:12:00+02:00",
            "0000-01-01T00:00:00+00:00",
            "2026-02-29T00:00:00+00:00",
            "2026-09-26T09:12:00+02:00x",
            "2026-09-26T09:12:00+02:",
            "2026-09-26T09:12:00.5",
            "2026-09-26T09:12:00",
            "2026-09-26T09:12:00+02:00.5",
            "2026-09-26T09:1200+02:00",
            "2026-09-26T",
            "2026-09-26T24:00:01+00:00",
            "bad",
            "",
        ];
        for text in bad {
            assert_eq!(parse_iso(text), None, "{text}");
        }
        assert_eq!(
            timestamp(Some(&json!("2026-09-26T07:12:00Z"))),
            Ok(1790406720)
        );
        assert_eq!(timestamp(Some(&json!(5))), Err(INVALID));
    }

    #[test]
    fn oslo_labels_cross_daylight_saving() {
        // 2026-03-29 01:00 UTC: 02:00 CET becomes 03:00 CEST.
        assert_eq!(time_label(1774745940).unwrap(), "01:59");
        assert_eq!(time_label(1774746000).unwrap(), "03:00");
        // 2026-10-25 01:00 UTC: 03:00 CEST becomes 02:00 CET.
        assert_eq!(time_label(1792889940).unwrap(), "02:59");
        assert_eq!(time_label(1792890000).unwrap(), "02:00");
        assert_eq!(time_label(1790406720).unwrap(), "09:12");
    }

    #[test]
    fn stations_and_routes() {
        let ok = station(Some(
            &json!({"id": "NSR:StopPlace:12", "name": " Oslo S ", "label": "x"}),
        ))
        .unwrap();
        assert_eq!(
            Value::Object(ok),
            json!({"id": "NSR:StopPlace:12", "name": "Oslo S"})
        );
        for bad in [
            json!({"id": "NSR:StopPlace:", "name": "x"}),
            json!({"id": "NSR:StopPlace:١", "name": "x"}),
            json!("x"),
        ] {
            assert_eq!(station(Some(&bad)), Err(SELECT));
        }
        assert_eq!(
            station(Some(&json!({"id": "NSR:StopPlace:1", "name": "a\u{1f}"}))),
            Err(BAD_NAME)
        );
        assert_eq!(
            station(Some(&json!({"id": "NSR:StopPlace:1", "name": "\u{1c}"}))),
            Err(BAD_NAME)
        );
        assert!(station(Some(&json!({"id": "NSR:StopPlace:1", "name": "a\u{7f}"}))).is_ok());
        assert_eq!(validate_route(&route()), Ok(route()));
        assert_eq!(
            validate_route(&json!({"from": route()["from"], "to": route()["from"]})),
            Err(SAME)
        );
    }

    #[test]
    fn labels_are_one_bounded_line() {
        assert_eq!(label(Some(&json!("a\n\t b\u{7f}")), "x"), "a  b");
        assert_eq!(label(Some(&json!("\u{0}")), "Name"), "Name");
        assert_eq!(label(Some(&json!(5)), "Name"), "Name");
        assert_eq!(
            py::len(&label(Some(&json!("ø".repeat(400))), "x")),
            MAX_LABEL
        );
    }

    #[test]
    fn report_order_and_fields() {
        let leg = json!({"id": "t", "mode": "rail", "aimedStartTime": "2026-09-26T09:12:00+02:00",
                         "expectedStartTime": "2026-09-26T09:14:30+02:00", "expectedEndTime": "2026-09-26T09:13:00+02:00"});
        let data = json!({"data": {"trip": {"tripPatterns": [{"legs": [leg]}]}}});
        let report =
            parse_response(data.as_object().unwrap(), &route(), "en", 1790406000, 1).unwrap();
        let keys: Vec<&str> = report.keys().map(String::as_str).collect();
        assert_eq!(
            keys,
            [
                "status",
                "route",
                "departures",
                "routeNotices",
                "updatedAt",
                "stale",
                "error",
                "errorCode"
            ]
        );
        let d = &report["departures"][0];
        assert_eq!(
            (d["delay"].as_i64(), d["duration"].as_i64()),
            (Some(2), Some(0))
        );
        assert_eq!(d["id"], "t:1790406720");
    }
}
