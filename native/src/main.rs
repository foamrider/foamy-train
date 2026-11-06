//! `foamy-train-helper`: direct rail departures and station search from
//! Entur for the foamy-train widget. It replaces `train_fetch.py` with the
//! same contract; replies and cache files are byte-identical to the Python
//! helper's for the same input and clock.
//!
//! # Arguments
//!
//! Parsed like the Python helper's argparse parser (`cli.rs`):
//!
//! - `--search=<text>`: station search (the widget always uses the `=` form,
//!   so a query starting with `-` stays a query). Wins over everything else.
//! - `--route-stdin`: read the station pair from stdin (at most 4096 bytes of
//!   JSON, `{"from": {"id", "name"}, "to": {…}}`), so it never shows in argv.
//!   Without it the report is `unconfigured` and nothing is fetched.
//! - `--language en|nb` (default `en`): notice language and part of the cache key.
//! - `--hours 1..24` (default 24): look-ahead.
//! - `--force`: ignore a fresh cache. `--offline`: never touch the network.
//! - `-h`/`--help`: usage on stdout, exit 0.
//!
//! Unique prefixes (`--off`), `--opt=value` and repeated options work as in
//! argparse. A usage error prints usage and the error on stderr, nothing on
//! stdout, and exits 2.
//!
//! # Reply
//!
//! Otherwise exactly one line of JSON on stdout, exit 0, stderr empty, in
//! Python `json.dump`'s format (`", "` and `": "` separators, UTF-8, no
//! ASCII escaping), keys in this order:
//!
//! - search: `{"status": "ok", "stations": [{"id", "name", "label"}, …]}`;
//!   a query shorter than 2 or longer than 100 characters (after trimming)
//!   gives no stations and no request.
//! - departures: `{"status", "route", "departures", "routeNotices",
//!   "updatedAt", "stale", "error", "errorCode"}` plus `searchHours` and
//!   `wideSince` on fetched reports. `status` is `ok`, `stale` (an earlier
//!   snapshot with the error of this attempt), `error` or `unconfigured`.
//!   Departure keys: `id line aimed expected arrival aimedTime expectedTime
//!   arrivalTime delay duration platform realtime cancelled notices`; notice
//!   keys: `id summary detail kind scopeLabel`.
//! - any failure without a snapshot: the same keys with `status` `error`,
//!   `route` as validated (or `null`) and `error`/`errorCode`:
//!
//! | errorCode | error (an i18n catalog key) |
//! |---|---|
//! | `invalid_route` | Select both stations from search results. / Invalid station name. / Choose two different stations. |
//! | `invalid_input` | Invalid route or unavailable local cache. Select the stations again. |
//! | `offline` | Offline. Showing the last available update. |
//! | `network_error` | Cannot reach Entur. Check your connection and try Refresh. |
//! | `http_error` | Entur is unavailable. Try Refresh. |
//! | `invalid_response` | Entur returned an invalid response. Try Refresh. / Station search returned an invalid response. |
//! | `api_error` | Entur could not find departures. Try Refresh. |
//! | `cache_write` | Could not save the local cache. (on an `ok` report) |
//! | `internal` | Train request failed. Try Refresh. (exit 101 on a helper bug, 1 without Europe/Oslo tz data) |
//!
//! # Fetching
//!
//! 1. Read the cache; a valid snapshot younger than 30 s is printed as stored
//!    unless `--force` or `--offline`.
//! 2. `--offline` fails with `offline`. Otherwise search 3 hours first and
//!    widen to the full look-ahead only when that holds fewer than 6 direct
//!    trains; a route that widened keeps the full window for an hour from its
//!    first widening (`wideSince`). Look-aheads of 3 hours or less use one
//!    window. All planner requests share a 14 s budget: each gets
//!    `max(1, min(12, remaining))` seconds, a widening needs 4 s left, and a
//!    failed widening keeps the short window's answer. The widget's
//!    `timeout --kill-after=2s 18s` stays the outer bound.
//! 3. Keep patterns with exactly one rail leg, departing (expected or aimed)
//!    no earlier than a minute ago and expected within the look-ahead;
//!    deduplicate by service journey and aimed time, sort by expected then
//!    aimed time, keep 6. Times are `HH:MM` in Europe/Oslo.
//! 4. Write the snapshot; failures fall back to the stored snapshot (`stale`).
//!
//! # Network
//!
//! - `POST https://api.entur.io/journey-planner/v3/graphql` with
//!   `{"query": …, "variables": {"from", "to", "searchWindow": minutes}}`
//!   and `GET https://api.entur.io/geocoder/v3/autocomplete?q=…&limit=8&stopPlaceTypes=railStation`,
//!   both with `ET-Client-Name: foamrider-foamy-train`, `Accept` and
//!   `Content-Type: application/json`, no compression. Replies are JSON
//!   objects of at most 2,000,000 bytes; 2xx only, redirects followed (up to 10).
//! - TLS through rustls with the system trust store (rustls-native-certs:
//!   `SSL_CERT_FILE`/`SSL_CERT_DIR` when set, else OpenSSL's default paths).
//! - `https_proxy`/`HTTPS_PROXY` and `no_proxy`/`NO_PROXY` as Python's urllib
//!   reads them (`net.rs`): CONNECT over plain TCP whatever the proxy URL's
//!   scheme, Basic credentials from `user:password@`, port 443 if missing.
//! - Test only: `FOAMY_TRAIN_ENTUR_URL` replaces `https://api.entur.io` with
//!   a loopback base URL (`http(s)://127.0.0.1|localhost|[::1][:port]`); any
//!   other value fails every request with `network_error`. Plain-http test
//!   URLs never use a proxy.
//!
//! # Files
//!
//! `${XDG_CACHE_HOME:-$HOME/.cache}/foamy.train/<sha256(from/to/language/hours)>.json`
//! (`XDG_CACHE_HOME` only when absolute). The directory is created 0700
//! (missing parents with the default mode); the file is written atomically
//! (temporary file, fsync, rename, mode 0600) in `json.dump` format plus a
//! newline. Reads are capped at 2,000,000 bytes. Config and state
//! directories are never touched. Europe/Oslo comes from
//! `/usr/share/zoneinfo` (then `/usr/lib/zoneinfo`, `/usr/share/lib/zoneinfo`,
//! `/etc/zoneinfo`, Python's TZPATH). No child processes are run.
//!
//! # Deliberate differences from train_fetch.py
//!
//! - Each request has a total deadline (urllib's timeout applied to each
//!   socket operation, so a trickling reply could run until `timeout` killed
//!   the helper).
//! - The cache is refused (a miss on read, `cache_write` on write) when it is
//!   a symlink or not a regular file, when its directory is not owned by this
//!   user or is writable by others, or without an absolute `HOME`.
//! - Station ids need ASCII digits; timestamps are ISO 8601 extended dates
//!   (Python also took week dates, basic format and a few stray forms);
//!   JSON input is UTF-8 (an optional BOM), not UTF-16/32, and lone
//!   surrogate escapes or nesting over 128 levels are invalid instead of
//!   crashing the helper; `str()` of non-string ids inside arrays or objects
//!   escapes only common invisible characters.
//! - A non-UTF-8 `--search` value is `invalid_input` even when short.
//! - Malformed HTTP replies, a bad proxy port and missing tz data are
//!   reported (`network_error`, `internal`) instead of a Python traceback.

mod cache;
mod cli;
mod entur;
mod net;
mod py;

use std::ffi::OsString;
use std::io::{self, Write};
use std::process::ExitCode;
use std::time::{Duration, Instant, SystemTime, UNIX_EPOCH};

use foamy_helper::io as bounded;
use serde_json::{Value, json};

use crate::entur::Object;

const QUERY_FIELDS: &str = "id reportType summary { language value } description { language value }
 advice { language value } affects { __typename
 ... on AffectedLine { line { publicCode } }
 ... on AffectedStopPlace { stopPlace { name } }
 ... on AffectedStopPlaceOnLine { line { publicCode } stopPlace { name } }
 }";

/// Entur returns no trips for `maximumTransfers: 0`; the search allows one and
/// the parser keeps single-leg patterns only. The explicit window keeps the
/// automatic search from ending before the next direct train.
fn query() -> String {
    format!(
        "query Departures($from: String!, $to: String!, $searchWindow: Int!) {{
 trip(from: {{place: $from}}, to: {{place: $to}}, numTripPatterns: 12, searchWindow: $searchWindow,
 maximumTransfers: 1, includeRealtimeCancellations: true, includePlannedCancellations: true,
 modes: {{transportModes: [{{transportMode: rail}}]}}) {{
 tripPatterns {{ legs {{ id mode aimedStartTime expectedStartTime aimedEndTime expectedEndTime realtime
 line {{ publicCode }} serviceJourney {{ id }}
 fromEstimatedCall {{ cancellation realtime quay {{ publicCode }} situations {{ {QUERY_FIELDS} }} }}
 toEstimatedCall {{ cancellation situations {{ {QUERY_FIELDS} }} }}
 situations {{ {QUERY_FIELDS} }}
 }} }} }} }}"
    )
}

const MAX_ROUTE_BYTES: u64 = 4096;
const CACHE_SECONDS: i64 = 30;
const FIRST_WINDOW_HOURS: i64 = 3;
const WIDE_REUSE_SECONDS: i64 = 3600;
const REQUEST_TIMEOUT: f64 = 12.0;
const FETCH_BUDGET: Duration = Duration::from_secs(14);
const WIDEN_MIN_SECONDS: f64 = 4.0;

/// A failure the reply reports: `error` (an i18n catalog key) and `errorCode`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct TrainError {
    pub code: &'static str,
    pub message: &'static str,
}

impl TrainError {
    pub const fn new(code: &'static str, message: &'static str) -> TrainError {
        TrainError { code, message }
    }
}

/// Why a run produced no report of its own.
#[derive(Debug, PartialEq)]
pub enum Failure {
    Train(TrainError),
    /// Unreadable route input (Python's OSError/ValueError): `invalid_input`.
    Input,
    /// No Europe/Oslo time zone data.
    Internal,
}

const OFFLINE: TrainError =
    TrainError::new("offline", "Offline. Showing the last available update.");
const SELECT: TrainError =
    TrainError::new("invalid_route", "Select both stations from search results.");
const INVALID_INPUT: TrainError = TrainError::new(
    "invalid_input",
    "Invalid route or unavailable local cache. Select the stations again.",
);
const INTERNAL: TrainError = TrainError::new("internal", "Train request failed. Try Refresh.");
const CACHE_WRITE: TrainError = TrainError::new("cache_write", "Could not save the local cache.");

fn empty(status: &str, route: Option<&Value>) -> Object {
    let value = json!({"status": status, "route": route, "departures": [], "routeNotices": [], "updatedAt": 0,
                       "stale": false, "error": "", "errorCode": ""});
    match value {
        Value::Object(map) => map,
        _ => unreachable!("json! of an object literal is an object"),
    }
}

fn failed(error: TrainError) -> Value {
    let mut report = empty("error", None);
    report.insert("error".into(), error.message.into());
    report.insert("errorCode".into(), error.code.into());
    Value::Object(report)
}

/// `value == hours` with Python's numeric equality (24.0 and True compare).
fn same_number(value: Option<&Value>, hours: i64) -> bool {
    match value {
        Some(Value::Number(n)) => n
            .as_i64()
            .map_or_else(|| n.as_f64() == Some(hours as f64), |i| i == hours),
        Some(Value::Bool(b)) => i64::from(*b) == hours,
        _ => false,
    }
}

/// When the full window was first chosen, while that choice is still within
/// WIDE_REUSE_SECONDS.
fn wide_since(cached: Option<&Value>, hours: i64, now: i64) -> Option<i64> {
    let cached = cached?;
    if !same_number(cached.get("searchHours"), hours) {
        return None;
    }
    let since = match cached.get("wideSince") {
        Some(Value::Number(n)) if !n.is_f64() => n.as_i64()?,
        _ => return None,
    };
    (0..WIDE_REUSE_SECONDS)
        .contains(&now.checked_sub(since)?)
        .then_some(since)
}

fn search_windows(hours: i64, cached: Option<&Value>, now: i64) -> Vec<i64> {
    if hours <= FIRST_WINDOW_HOURS || wide_since(cached, hours, now).is_some() {
        vec![hours]
    } else {
        vec![FIRST_WINDOW_HOURS, hours]
    }
}

fn unix_now() -> i64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_or(0, |d| d.as_secs() as i64)
}

fn search(query: &OsString) -> Result<Value, Failure> {
    let query = query.to_str().ok_or(Failure::Input)?;
    let query = py::strip(query);
    if !(2..=100).contains(&py::len(query)) {
        return Ok(json!({"status": "ok", "stations": []}));
    }
    let client = net::Client::new().map_err(Failure::Train)?;
    let url = client.endpoint().geocoder(query);
    let data = client
        .request_json(&url, None, Duration::from_secs_f64(REQUEST_TIMEOUT))
        .map_err(Failure::Train)?;
    Ok(json!({"status": "ok", "stations": entur::stations(&data).map_err(Failure::Train)?}))
}

fn read_route() -> Result<Value, Failure> {
    let data = bounded::read_stdin_limited(MAX_ROUTE_BYTES).map_err(|error| {
        if bounded::is_over_limit(&error) {
            Failure::Train(SELECT)
        } else {
            Failure::Input
        }
    })?;
    let value = py::loads(&data).map_err(|()| Failure::Input)?;
    entur::validate_route(&value).map_err(Failure::Train)
}

/// Requests the windows in turn within the shared budget.
fn plan(
    route: &Value,
    language: &str,
    hours: i64,
    cached: Option<&Value>,
    now: i64,
) -> Result<Object, Failure> {
    let client = net::Client::new().map_err(Failure::Train)?;
    let url = client.endpoint().planner();
    let deadline = Instant::now() + FETCH_BUDGET;
    let mut report: Option<Object> = None;
    for window in search_windows(hours, cached, now) {
        let remaining = deadline
            .saturating_duration_since(Instant::now())
            .as_secs_f64();
        if report.is_some() && remaining < WIDEN_MIN_SECONDS {
            break;
        }
        let variables = json!({"from": route["from"]["id"], "to": route["to"]["id"], "searchWindow": window * 60});
        let body = py::dumps(&json!({"query": query(), "variables": variables}));
        let timeout = Duration::from_secs_f64(remaining.clamp(1.0, REQUEST_TIMEOUT));
        let candidate = client
            .request_json(&url, Some(body), timeout)
            .map_err(Failure::Train)
            .and_then(|data| entur::parse_response(&data, route, language, now, hours));
        let mut candidate = match candidate {
            Ok(candidate) => candidate,
            // A failed widening keeps the short window's departures.
            Err(Failure::Train(_)) if report.is_some() => break,
            Err(failure) => return Err(failure),
        };
        candidate.insert("searchHours".into(), window.into());
        if window == hours && window > FIRST_WINDOW_HOURS {
            let since = wide_since(cached, hours, now)
                .filter(|&s| s != 0)
                .unwrap_or(now);
            candidate.insert("wideSince".into(), since.into());
        }
        let enough = candidate["departures"]
            .as_array()
            .is_some_and(|d| d.len() >= entur::MAX_DEPARTURES);
        report = Some(candidate);
        if enough {
            break;
        }
    }
    report.ok_or(Failure::Internal)
}

fn fetch(
    route: Option<Value>,
    language: &str,
    force: bool,
    offline: bool,
    hours: i64,
) -> Result<Value, Failure> {
    let Some(route) = route else {
        return Ok(Value::Object(empty("unconfigured", None)));
    };
    let now = unix_now();
    let path = cache::directory(std::env::var_os("XDG_CACHE_HOME"), std::env::var_os("HOME"))
        .map(|dir| cache::file(&dir, &route, language, hours));
    // Cache corruption must not prevent a fresh request.
    let cached = path
        .as_deref()
        .and_then(cache::read)
        .filter(|v| cache::valid_snapshot(v, &route, now));
    if let Some(snapshot) = &cached {
        let fresh = snapshot["updatedAt"]
            .as_i64()
            .is_some_and(|t| now - t < CACHE_SECONDS);
        if fresh && !force && !offline {
            return Ok(snapshot.clone());
        }
    }
    let attempt = if offline {
        Err(Failure::Train(OFFLINE))
    } else {
        plan(&route, language, hours, cached.as_ref(), now)
    };
    match attempt {
        Ok(mut report) => {
            let snapshot = Value::Object(report.clone());
            if path
                .as_deref()
                .is_none_or(|path| cache::write(path, &snapshot).is_err())
            {
                report.insert("error".into(), CACHE_WRITE.message.into());
                report.insert("errorCode".into(), CACHE_WRITE.code.into());
            }
            Ok(Value::Object(report))
        }
        Err(Failure::Train(error)) => {
            let mut report = match &cached {
                Some(Value::Object(snapshot)) => snapshot.clone(),
                _ => empty("error", Some(&route)),
            };
            let stale = cached.is_some();
            report.insert(
                "status".into(),
                (if stale { "stale" } else { "error" }).into(),
            );
            report.insert("stale".into(), stale.into());
            report.insert("error".into(), error.message.into());
            report.insert("errorCode".into(), error.code.into());
            Ok(Value::Object(report))
        }
        Err(other) => Err(other),
    }
}

fn respond(args: cli::Args) -> Result<Value, Failure> {
    if let Some(query) = &args.search {
        return search(query);
    }
    let route = if args.route_stdin {
        Some(read_route()?)
    } else {
        None
    };
    fetch(route, args.language, args.force, args.offline, args.hours)
}

fn print(value: &Value) -> bool {
    let mut stdout = io::stdout().lock();
    stdout
        .write_all(&py::dump_line(value))
        .and_then(|()| stdout.flush())
        .is_ok()
}

fn main() -> ExitCode {
    // A helper bug still answers in JSON and exits 101 instead of aborting
    // (and dumping core) under the kit's panic = "abort".
    let previous = std::panic::take_hook();
    std::panic::set_hook(Box::new(move |info| {
        previous(info);
        print(&failed(INTERNAL));
        std::process::exit(101);
    }));
    let args: Vec<OsString> = std::env::args_os().skip(1).collect();
    let args = match cli::parse(&args) {
        cli::Parsed::Run(args) => args,
        cli::Parsed::Help => {
            let mut stdout = io::stdout().lock();
            let ok = writeln!(stdout, "{}\n{}", cli::USAGE, cli::HELP)
                .and_then(|()| stdout.flush())
                .is_ok();
            return if ok {
                ExitCode::SUCCESS
            } else {
                ExitCode::FAILURE
            };
        }
        cli::Parsed::Usage(message) => {
            let _ = writeln!(
                io::stderr(),
                "{}\nfoamy-train-helper: error: {message}",
                cli::USAGE
            );
            return ExitCode::from(2);
        }
    };
    let (reply, code) = match respond(args) {
        Ok(reply) => (reply, 0),
        Err(Failure::Train(error)) => (failed(error), 0),
        Err(Failure::Input) => (failed(INVALID_INPUT), 0),
        Err(Failure::Internal) => (failed(INTERNAL), 1),
    };
    if print(&reply) {
        ExitCode::from(code)
    } else {
        ExitCode::FAILURE
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_shape() {
        let q = query();
        assert!(q.starts_with(
            "query Departures($from: String!, $to: String!, $searchWindow: Int!) {\n trip("
        ));
        assert!(q.ends_with("\n } } } }"));
        assert_eq!(q.matches("affects { __typename").count(), 3);
        assert_eq!(q.matches('{').count(), q.matches('}').count());
    }

    #[test]
    fn widening_memory() {
        let now = 1_000_000;
        let cached = json!({"searchHours": 24, "wideSince": now - 600});
        assert_eq!(wide_since(Some(&cached), 24, now), Some(now - 600));
        assert_eq!(search_windows(24, Some(&cached), now), [24]);
        assert_eq!(
            wide_since(
                Some(&json!({"searchHours": 24.0, "wideSince": now})),
                24,
                now
            ),
            Some(now)
        );
        assert_eq!(
            wide_since(
                Some(&json!({"searchHours": true, "wideSince": now})),
                1,
                now
            ),
            Some(now)
        );
        for stale in [
            json!({"searchHours": 24, "wideSince": now - 3600}),
            json!({"searchHours": 24, "wideSince": now + 1}),
            json!({"searchHours": 3, "wideSince": now}),
            json!({"searchHours": 24, "wideSince": 5.0}),
        ] {
            assert_eq!(wide_since(Some(&stale), 24, now), None, "{stale}");
        }
        assert_eq!(search_windows(24, None, now), [3, 24]);
        assert_eq!(search_windows(3, None, now), [3]);
    }

    #[test]
    fn failure_reports_use_python_layout() {
        let text = String::from_utf8(py::dump_line(&failed(SELECT))).unwrap();
        assert_eq!(
            text,
            "{\"status\": \"error\", \"route\": null, \"departures\": [], \"routeNotices\": [], \"updatedAt\": 0, \
             \"stale\": false, \"error\": \"Select both stations from search results.\", \"errorCode\": \"invalid_route\"}\n"
        );
    }
}
