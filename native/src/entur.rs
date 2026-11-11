//! Entur data: station validation, geocoder results, journey-planner
//! answers and their service notices. The rules (and the order in which
//! fields are read, so the same inputs fail) are train_fetch.py's.

use std::collections::HashSet;
use std::fs::File;
use std::io::Read;
use std::sync::OnceLock;

use jiff::Timestamp;
use jiff::tz::TimeZone;
use serde_json::{Map, Value, json};

use crate::py::{self, Dict};
use crate::{Failure, TrainError};

// The report contract: how much provider data a reply may carry. Entur's
// replies are bounded only by their 2,000,000-byte body (and the station
// search by its own limit=8 request), and the popup builds every station row
// and notice eagerly (QML Repeaters), so counts and lengths are capped here
// while parsing, before anything is kept, and again on a cached snapshot (an
// older helper's, or an edited one: `bound_report`). Model.js applies the
// same numbers to every reply it reads. Lengths are code points.
//
// Text is cut, never rejected: a long notice is still worth reading, and the
// trailing `…` shows that it was cut (`clip`). Ids are cut the same way and
// deduplicated after cutting, so a list never holds two equal keys. Lists
// keep their first entries; a notice left out marks the report
// `noticesOmitted`, so the popup never presents a partial list as complete.
/// Station search results: the request's limit=8.
pub const MAX_STATIONS: usize = 8;
/// Departures: the six soonest.
pub const MAX_DEPARTURES: usize = 6;
/// Notices on one departure: three keep a card readable, and the popup at
/// most 6 x 3 + 5 = 23 notices.
pub const MAX_NOTICES: usize = 3;
/// Route-wide notices, shown once above the departures.
pub const MAX_ROUTE_NOTICES: usize = 5;
/// A notice's headline (Entur summaries are a sentence or two).
pub const MAX_SUMMARY: usize = 200;
/// A notice's description and advice, joined: a few short paragraphs.
pub const MAX_DETAIL: usize = 600;
/// A notice's scope: line codes and stop place names joined with " · ".
pub const MAX_SCOPE: usize = 100;
/// Notice and departure ids (Entur's are short codes like `RUT:SituationNumber:1`).
pub const MAX_ID: usize = 100;
/// Line and platform codes ("R10", "11").
pub const MAX_CODE: usize = 20;
/// A station's display label.
pub const MAX_LABEL: usize = 160;
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

/// `text` in at most `limit` code points (at least 1): cut text ends in `…`.
/// Model.js's `clip` is the same rule.
pub fn clip(text: &str, limit: usize) -> String {
    match text.char_indices().nth(limit) {
        None => text.to_owned(),
        Some(_) => {
            let end = text
                .char_indices()
                .nth(limit - 1)
                .map_or(text.len(), |(at, _)| at);
            format!("{}…", &text[..end])
        }
    }
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
    clip(if text.is_empty() { fallback } else { text }, MAX_LABEL)
}

/// Geocoder features → rail stations `{"id", "name", "label"}`, deduplicated,
/// the first MAX_STATIONS (the rest of the reply is not read).
pub fn stations(data: &Object) -> Result<Vec<Value>, TrainError> {
    let Some(Value::Array(features)) = data.get("features") else {
        return Err(BAD_SEARCH);
    };
    let mut results = Vec::new();
    let mut seen: Vec<String> = Vec::new();
    for feature in features {
        if results.len() == MAX_STATIONS {
            break;
        }
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

/// A notice as the report carries it, every field within the contract.
fn notice(id: &str, summary: &str, detail: &str, kind: &str, scope: &str) -> Value {
    json!({"id": clip(id, MAX_ID), "summary": clip(summary, MAX_SUMMARY), "detail": clip(detail, MAX_DETAIL),
           "kind": kind, "scopeLabel": clip(scope, MAX_SCOPE)})
}

/// Notices whose id is already in `list`.
fn listed(list: &[Value], id: &str) -> bool {
    list.iter().any(|n| n["id"] == id)
}

/// Notices kept for one list (a departure's, or the route's across all
/// departures) and whether a further distinct one was left out.
#[derive(Default)]
struct NoticeList {
    list: Vec<Value>,
    omitted: bool,
}

impl NoticeList {
    /// Full, and known to have left one out: nothing more to learn.
    fn done(&self, limit: usize) -> bool {
        self.list.len() == limit && self.omitted
    }
}

/// A departure's situations → its own notices, with the route-wide ones
/// added to `route`. Route-wide only when every affected entity is a line or
/// stop place; repeated wording is not scope. Notices are deduplicated by
/// their (cut) id before they count against a limit. Once both lists are
/// full and each has left one out, the remaining situations are not read.
fn notices(
    values: &[&Value],
    language: &str,
    route: &mut NoticeList,
) -> Result<NoticeList, TrainError> {
    let mut own = NoticeList::default();
    // Ids kept on this departure or seen on the route: at most
    // MAX_NOTICES + MAX_ROUTE_NOTICES.
    let mut seen: Vec<String> = Vec::new();
    for value in values {
        if own.done(MAX_NOTICES) && route.done(MAX_ROUTE_NOTICES) {
            break;
        }
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
        let identity = clip(
            &match py::or_none(value.get("id")) {
                Some(id) => py::str_of(id),
                None => format!("{summary}{detail}"),
            },
            MAX_ID,
        );
        if seen.contains(&identity) {
            continue;
        }
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
        // Every entity is checked; labels stop once they fill the scope.
        let (mut labels, mut width): (Vec<&str>, usize) = (Vec::new(), 0);
        if wide {
            for entity in affected.and_then(Value::as_array).into_iter().flatten() {
                for (field, key) in [("line", "publicCode"), ("stopPlace", "name")] {
                    let named = Dict::or_empty(entity.get(field))
                        .get(key)
                        .map_err(|()| INVALID)?;
                    match py::or_none(named) {
                        None => {}
                        Some(Value::String(text)) => {
                            if width <= MAX_SCOPE && !labels.contains(&text.as_str()) {
                                width += py::len(text) + 3;
                                labels.push(text);
                            }
                        }
                        // " · ".join() of a non-string raises TypeError.
                        Some(_) => return Err(INVALID),
                    }
                }
            }
        }
        let (kept, limit) = if wide {
            if listed(&route.list, &identity) {
                seen.push(identity);
                continue;
            }
            (&mut *route, MAX_ROUTE_NOTICES)
        } else {
            (&mut own, MAX_NOTICES)
        };
        if kept.list.len() == limit {
            kept.omitted = true;
            continue;
        }
        let kind = if value.get("reportType").and_then(Value::as_str) == Some("general") {
            "info"
        } else {
            "warning"
        };
        kept.list.push(notice(
            &identity,
            &summary,
            &detail,
            kind,
            &labels.join(" · "),
        ));
        seen.push(identity);
    }
    Ok(own)
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
    // The MAX_DEPARTURES soonest so far, in report order (a stable sort by
    // expected then aimed time), each with whether it left a notice out.
    let mut departures: Vec<(i64, i64, Value, bool)> = Vec::new();
    let mut route_notices = NoticeList::default();
    let mut seen = HashSet::<String>::new();
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
        let identity = clip(&format!("{name}:{aimed}"), MAX_ID);
        if !seen.insert(identity.clone()) {
            continue;
        }
        let situations = concat(&[
            leg.get("situations"),
            start.get("situations").map_err(bad)?,
            end.get("situations").map_err(bad)?,
        ])
        .map_err(wrap)?;
        let own = notices(&situations, language, &mut route_notices).map_err(wrap)?;
        let line = Dict::or_empty(leg.get("line"))
            .get("publicCode")
            .map_err(bad)?;
        let quay = Dict::or_empty(start.get("quay").map_err(bad)?)
            .get("publicCode")
            .map_err(bad)?;
        let departure = json!({
            "id": identity, "line": clip(&text_or_dash(line), MAX_CODE), "aimed": aimed, "expected": expected, "arrival": arrival,
            "aimedTime": time_label(aimed)?, "expectedTime": time_label(expected)?, "arrivalTime": time_label(arrival)?,
            "delay": 0.max((expected - aimed).div_euclid(60)), "duration": 0.max((arrival - expected).div_euclid(60)),
            "platform": clip(&text_or_dash(quay), MAX_CODE), "realtime": py::is_true(start.get("realtime").map_err(bad)?),
            "cancelled": cancelled, "notices": own.list,
        });
        // After every earlier departure at the same times, as a stable sort puts it.
        let at = departures.partition_point(|(e, a, _, _)| (*e, *a) <= (expected, aimed));
        if at < MAX_DEPARTURES {
            departures.insert(at, (expected, aimed, departure, own.omitted));
            departures.truncate(MAX_DEPARTURES);
        }
    }
    let omitted = route_notices.omitted || departures.iter().any(|(_, _, _, omitted)| *omitted);
    let departures: Vec<Value> = departures.into_iter().map(|(_, _, d, _)| d).collect();
    let report = json!({"status": "ok", "route": route, "departures": departures, "routeNotices": route_notices.list,
                        "updatedAt": now, "stale": false, "error": "", "errorCode": ""});
    let Value::Object(mut report) = report else {
        unreachable!("json! of an object literal is an object")
    };
    if omitted {
        report.insert("noticesOmitted".into(), true.into());
    }
    Ok(report)
}

/// A notice list within `limit`: fields cut, deduplicated by the cut id.
/// True when a distinct notice was left out.
fn bound_notices(list: &mut Vec<Value>, limit: usize) -> bool {
    let mut omitted = false;
    let mut kept: Vec<Value> = Vec::new();
    for n in std::mem::take(list) {
        let text = |key: &str| n[key].as_str().unwrap_or_default().to_owned();
        let id = clip(&text("id"), MAX_ID);
        if listed(&kept, &id) {
            continue;
        }
        if kept.len() == limit {
            omitted = true;
            break;
        }
        let kind = text("kind");
        kept.push(notice(
            &id,
            &text("summary"),
            &text("detail"),
            &kind,
            &text("scopeLabel"),
        ));
    }
    *list = kept;
    omitted
}

/// A cached snapshot (already `cache::valid_snapshot`) within the report
/// contract, as parse_response would have written it: an older helper kept
/// every notice at full length. Departures are deduplicated by the cut id and
/// keep their stored order. Model.js's `parse` does the same to every reply.
pub fn bound_report(report: &mut Object) {
    let mut omitted = false;
    if let Some(Value::Array(departures)) = report.get_mut("departures") {
        let mut ids: Vec<String> = Vec::new();
        departures.retain_mut(|d| {
            let Value::Object(d) = d else { return false };
            let text = |d: &Object, key: &str| {
                d.get(key)
                    .and_then(Value::as_str)
                    .unwrap_or_default()
                    .to_owned()
            };
            let id = clip(&text(d, "id"), MAX_ID);
            if ids.len() == MAX_DEPARTURES || ids.contains(&id) {
                return false;
            }
            for key in ["line", "platform"] {
                let code = clip(&text(d, key), MAX_CODE);
                d.insert(key.into(), code.into());
            }
            if let Some(Value::Array(own)) = d.get_mut("notices") {
                omitted |= bound_notices(own, MAX_NOTICES);
            }
            d.insert("id".into(), id.clone().into());
            ids.push(id);
            true
        });
    }
    if let Some(Value::Array(list)) = report.get_mut("routeNotices") {
        omitted |= bound_notices(list, MAX_ROUTE_NOTICES);
    }
    if omitted {
        report.insert("noticesOmitted".into(), true.into());
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

    #[test]
    fn clip_cuts_whole_code_points_with_an_ellipsis() {
        assert_eq!(clip("ab", 5), "ab");
        assert_eq!(clip("abc", 3), "abc");
        assert_eq!(clip("abcd", 3), "ab…");
        assert_eq!(clip("øøøø", 2), "ø…");
        assert_eq!(clip("🚆🚆🚆", 2), "🚆…");
        assert_eq!(clip("x", 1), "x");
        assert_eq!(clip("xy", 1), "…");
    }

    fn rail(id: &str, situations: Vec<Value>) -> Value {
        json!({"id": id, "mode": "rail", "aimedStartTime": "2026-09-26T09:12:00+02:00",
               "expectedStartTime": "2026-09-26T09:12:00+02:00", "expectedEndTime": "2026-09-26T09:22:00+02:00",
               "serviceJourney": {"id": id}, "situations": situations})
    }

    fn report(legs: Vec<Value>) -> Object {
        let patterns: Vec<Value> = legs.into_iter().map(|leg| json!({"legs": [leg]})).collect();
        let data = json!({"data": {"trip": {"tripPatterns": patterns}}});
        assert!(py::dumps(&data).len() < 2_000_000, "below the response cap");
        parse_response(data.as_object().unwrap(), &route(), "en", 1790406000, 1).unwrap()
    }

    #[test]
    fn ten_thousand_situations_keep_three_notices() {
        // The marketplace review's shape: one valid rail leg, 10,000 unique situations.
        let many = (0..10_000)
            .map(|i| json!({"id": format!("n{i}"), "summary": [{"language": "en", "value": "x"}]}))
            .collect();
        let report = report(vec![rail("t", many)]);
        let notices = report["departures"][0]["notices"].as_array().unwrap();
        let ids: Vec<&str> = notices.iter().map(|n| n["id"].as_str().unwrap()).collect();
        assert_eq!(ids, ["n0", "n1", "n2"]);
        assert_eq!(report["noticesOmitted"], true);
        assert_eq!(bound(&report), report);
    }

    #[test]
    fn route_notices_are_counted_across_departures_after_deduplication() {
        let wide = |id: String| json!({"id": id, "summary": [{"value": "Works"}], "affects": [{"__typename": "AffectedLine"}]});
        // The same five route-wide notices on every departure: all kept, none left out.
        let same: Vec<Value> = (0..6)
            .map(|d| {
                rail(
                    &format!("t{d}"),
                    (0..5).map(|i| wide(format!("w{i}"))).collect(),
                )
            })
            .collect();
        let kept = report(same);
        assert_eq!(kept["routeNotices"].as_array().unwrap().len(), 5);
        assert!(!kept.contains_key("noticesOmitted"));
        // 2,000 distinct ones on each of six departures: the first five overall.
        let distinct: Vec<Value> = (0..6)
            .map(|d| {
                rail(
                    &format!("t{d}"),
                    (0..2000).map(|i| wide(format!("w{d}-{i}"))).collect(),
                )
            })
            .collect();
        let report = report(distinct);
        let ids: Vec<&str> = report["routeNotices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, ["w0-0", "w0-1", "w0-2", "w0-3", "w0-4"]);
        assert!(
            report["departures"]
                .as_array()
                .unwrap()
                .iter()
                .all(|d| d["notices"] == json!([]))
        );
        assert_eq!(report["noticesOmitted"], true);
    }

    #[test]
    fn notice_text_and_codes_are_cut_to_the_contract() {
        let long = "ø".repeat(50_000);
        let affects: Vec<Value> = (0..5000)
            .map(|i| json!({"__typename": "AffectedStopPlace", "stopPlace": {"name": format!("Stop {i}")}}))
            .collect();
        let situations = vec![
            json!({"id": long, "summary": [{"value": long}], "description": [{"value": format!("d{long}")}],
                   "advice": [{"value": format!("a{long}")}]}),
            json!({"id": "wide", "summary": [{"value": "x"}], "affects": affects}),
        ];
        let mut leg = rail("t", situations);
        leg["line"] = json!({"publicCode": long});
        leg["fromEstimatedCall"] = json!({"quay": {"publicCode": long}});
        leg["serviceJourney"] = json!({"id": long});
        let report = report(vec![leg]);
        let d = &report["departures"][0];
        let n = &d["notices"][0];
        let r = &report["routeNotices"][0];
        for (text, limit) in [
            (&n["id"], MAX_ID),
            (&n["summary"], MAX_SUMMARY),
            (&n["detail"], MAX_DETAIL),
            (&r["scopeLabel"], MAX_SCOPE),
            (&d["id"], MAX_ID),
            (&d["line"], MAX_CODE),
            (&d["platform"], MAX_CODE),
        ] {
            let text = text.as_str().unwrap();
            assert_eq!(py::len(text), limit, "{text}");
            assert!(text.ends_with('…'), "{text}");
        }
        assert!(
            r["scopeLabel"]
                .as_str()
                .unwrap()
                .starts_with("Stop 0 · Stop 1 · ")
        );
        assert!(!report.contains_key("noticesOmitted"));
    }

    #[test]
    fn station_search_keeps_the_first_eight() {
        let features: Vec<Value> = (0..10_000)
            .map(|i| json!({"properties": {"id": format!("NSR:StopPlace:{}", i / 2), "names": {"default": format!("S{i}")},
                                           "stopPlaceTypes": ["railStation"]}}))
            .collect();
        let data = json!({"features": features});
        assert!(py::dumps(&data).len() < 2_000_000, "below the response cap");
        let found = stations(data.as_object().unwrap()).unwrap();
        let ids: Vec<&str> = found.iter().map(|s| s["id"].as_str().unwrap()).collect();
        assert_eq!(
            ids,
            (0..8)
                .map(|i| format!("NSR:StopPlace:{i}"))
                .collect::<Vec<_>>()
        );
    }

    fn bound(report: &Object) -> Object {
        let mut copy = report.clone();
        bound_report(&mut copy);
        copy
    }

    #[test]
    fn an_older_snapshot_is_cut_like_a_fresh_answer() {
        let n = |id: String, text: &str| json!({"id": id, "summary": text, "detail": text, "kind": "info", "scopeLabel": text});
        let long = "x".repeat(5000);
        let departure = |id: String| {
            json!({"id": id, "line": long, "platform": long, "aimed": 1, "expected": 1, "arrival": 1,
                   "aimedTime": "10:00", "expectedTime": "10:00", "arrivalTime": "10:10", "delay": 0, "duration": 10,
                   "realtime": true, "cancelled": false,
                   "notices": (0..1000).map(|i| n(format!("n{i}"), &long)).collect::<Vec<_>>()})
        };
        let mut departures: Vec<Value> = (0..20).map(|i| departure(format!("d{i}"))).collect();
        departures.insert(1, departure("d0".into()));
        let mut route_notices = vec![n("dup".into(), "a"), n("dup".into(), "b")];
        route_notices.extend((0..10_000).map(|i| n(format!("r{i}"), "r")));
        let old = json!({"status": "ok", "route": route(), "departures": departures, "routeNotices": route_notices,
                         "updatedAt": 0, "stale": false, "error": "", "errorCode": ""});
        let cut = bound(old.as_object().unwrap());
        let departures = cut["departures"].as_array().unwrap();
        let ids: Vec<&str> = departures
            .iter()
            .map(|d| d["id"].as_str().unwrap())
            .collect();
        assert_eq!(ids, ["d0", "d1", "d2", "d3", "d4", "d5"]);
        for d in departures {
            assert_eq!(d["notices"].as_array().unwrap().len(), MAX_NOTICES);
            assert_eq!(py::len(d["line"].as_str().unwrap()), MAX_CODE);
            let first = &d["notices"][0];
            assert_eq!(py::len(first["summary"].as_str().unwrap()), MAX_SUMMARY);
            assert_eq!(py::len(first["detail"].as_str().unwrap()), MAX_DETAIL);
            assert_eq!(py::len(first["scopeLabel"].as_str().unwrap()), MAX_SCOPE);
        }
        let route_ids: Vec<&str> = cut["routeNotices"]
            .as_array()
            .unwrap()
            .iter()
            .map(|n| n["id"].as_str().unwrap())
            .collect();
        assert_eq!(route_ids, ["dup", "r0", "r1", "r2", "r3"]);
        assert_eq!(cut["routeNotices"][0]["summary"], "a");
        assert_eq!(cut["noticesOmitted"], true);
        // Within the contract: unchanged, byte for byte.
        assert_eq!(
            py::dumps(&Value::Object(bound(&cut))),
            py::dumps(&Value::Object(cut))
        );
    }
}
