//! The departure cache: one JSON snapshot per route, language and
//! look-ahead under `${XDG_CACHE_HOME:-$HOME/.cache}/foamy.train/`.

use std::ffi::OsString;
use std::fs::DirBuilder;
use std::io::{self, ErrorKind};
use std::os::unix::ffi::OsStrExt;
use std::os::unix::fs::DirBuilderExt;
use std::path::{Path, PathBuf};

use foamy_helper::{fs, hash};
use serde_json::Value;

use crate::net::MAX_BYTES;
use crate::py;

/// `$XDG_CACHE_HOME/foamy.train` when that is absolute, else
/// `$HOME/.cache/foamy.train`; None without an absolute `HOME`.
pub fn directory(xdg_cache: Option<OsString>, home: Option<OsString>) -> Option<PathBuf> {
    let absolute =
        |value: OsString| (value.as_bytes().first() == Some(&b'/')).then(|| PathBuf::from(value));
    xdg_cache
        .and_then(absolute)
        .or_else(|| home.and_then(absolute).map(|home| home.join(".cache")))
        .map(|dir| dir.join("foamy.train"))
}

/// `<dir>/<sha256("<from>/<to>/<language>/<hours>")>.json`: a short-window
/// snapshot never hides departures after the user widens the look-ahead.
pub fn file(dir: &Path, route: &Value, language: &str, hours: i64) -> PathBuf {
    let key = format!(
        "{}/{}/{language}/{hours}",
        route["from"]["id"].as_str().unwrap_or_default(),
        route["to"]["id"].as_str().unwrap_or_default()
    );
    dir.join(format!("{}.json", hash::sha256_hex(key.as_bytes())))
}

/// The stored snapshot, if it is a readable regular file of at most
/// MAX_BYTES holding JSON. Anything else is a cache miss.
pub fn read(path: &Path) -> Option<Value> {
    py::loads(&fs::read_file_limited(path, MAX_BYTES).ok()?).ok()
}

fn integer(value: Option<&Value>) -> Option<i64> {
    match value {
        Some(Value::Number(n)) if !n.is_f64() => n.as_i64(),
        _ => None,
    }
}

fn is_int(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Number(n)) if !n.is_f64())
}

fn is_str(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::String(_)))
}

fn is_bool(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Bool(_)))
}

/// A complete `ok` snapshot for this route, at most a day old.
pub fn valid_snapshot(value: &Value, route: &Value, now: i64) -> bool {
    let Value::Object(map) = value else {
        return false;
    };
    if map.get("route") != Some(route) || map.get("status").and_then(Value::as_str) != Some("ok") {
        return false;
    }
    if !is_int(map.get("updatedAt"))
        || !integer(map.get("updatedAt")).is_some_and(|t| (0..=86_400).contains(&(now - t)))
    {
        return false;
    }
    let (Some(Value::Array(departures)), Some(Value::Array(route_notices))) =
        (map.get("departures"), map.get("routeNotices"))
    else {
        return false;
    };
    if !is_str(map.get("error"))
        || !is_str(map.get("errorCode"))
        || !is_bool(map.get("stale"))
        || map.get("noticesOmitted").is_some_and(|v| !v.is_boolean())
    {
        return false;
    }
    let mut notices: Vec<&Value> = route_notices.iter().collect();
    for departure in departures {
        let Value::Object(d) = departure else {
            return false;
        };
        let texts = [
            "id",
            "line",
            "platform",
            "aimedTime",
            "expectedTime",
            "arrivalTime",
        ];
        if !texts.iter().all(|k| is_str(d.get(*k)))
            || !["aimed", "expected", "arrival", "delay", "duration"]
                .iter()
                .all(|k| is_int(d.get(*k)))
            || !["realtime", "cancelled"].iter().all(|k| is_bool(d.get(*k)))
        {
            return false;
        }
        let Some(Value::Array(own)) = d.get("notices") else {
            return false;
        };
        notices.extend(own);
    }
    notices.iter().all(|n| {
        matches!(n, Value::Object(n)
            if ["id", "summary", "detail", "scopeLabel"].iter().all(|k| is_str(n.get(*k)))
                && matches!(n.get("kind").and_then(Value::as_str), Some("info" | "warning")))
    })
}

/// `Path.mkdir(mode=0o700, parents=True, exist_ok=True)`: missing parents
/// get the default mode, an existing directory (or a link to one) is fine.
fn make_dir(dir: &Path) -> io::Result<()> {
    let leaf = || DirBuilder::new().mode(0o700).create(dir);
    let exists = |error: io::Error| if dir.is_dir() { Ok(()) } else { Err(error) };
    match leaf() {
        Ok(()) => Ok(()),
        Err(error) if error.kind() == ErrorKind::NotFound => {
            if let Some(parent) = dir.parent() {
                DirBuilder::new()
                    .recursive(true)
                    .mode(0o777)
                    .create(parent)?;
            }
            leaf().or_else(exists)
        }
        Err(error) => exists(error),
    }
}

/// Writes the snapshot atomically (temporary file, fsync, rename, mode 0600).
pub fn write(path: &Path, report: &Value) -> io::Result<()> {
    let dir = path
        .parent()
        .ok_or_else(|| io::Error::from(ErrorKind::InvalidInput))?;
    make_dir(dir)?;
    fs::write_atomic(path, &py::dump_line(report), 0o600)
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn directory_rules() {
        let dir = |x: Option<&str>, h: Option<&str>| {
            directory(x.map(OsString::from), h.map(OsString::from))
        };
        assert_eq!(
            dir(Some("/x"), Some("/h")),
            Some(PathBuf::from("/x/foamy.train"))
        );
        assert_eq!(
            dir(Some("rel"), Some("/h")),
            Some(PathBuf::from("/h/.cache/foamy.train"))
        );
        assert_eq!(
            dir(Some(""), Some("/h")),
            Some(PathBuf::from("/h/.cache/foamy.train"))
        );
        assert_eq!(dir(None, Some("rel")), None);
        assert_eq!(dir(None, None), None);
    }

    #[test]
    fn file_names_hash_route_language_and_hours() {
        let route = json!({"from": {"id": "NSR:StopPlace:1"}, "to": {"id": "NSR:StopPlace:2"}});
        // hashlib.sha256(b"NSR:StopPlace:1/NSR:StopPlace:2/en/24").hexdigest()
        assert_eq!(
            file(Path::new("/c"), &route, "en", 24),
            PathBuf::from(
                "/c/01a5fd2c959e96bc6a563057a3050eff873e618c15cfdf4650276749ff6dc817.json"
            )
        );
    }

    #[test]
    fn file_names_stay_byte_identical_across_padding_edges() {
        // hashlib.sha256(key.encode()).hexdigest(), the names train_fetch.py
        // and the ring-based helper wrote: keys of 36 to 120 bytes cover the
        // one- and two-block paddings (55/56, 63/64/65, 119/120 bytes).
        let mut cases: Vec<(String, &str, &str, i64, &str)> = vec![
            (
                "NSR:StopPlace:59872".into(),
                "NSR:StopPlace:337",
                "nb",
                168,
                "98f796bf95ace91d09a6441f82a6a539ece7b7b73b70ebcbc0b712de173c7348",
            ),
            (
                "NSR:StopPlace:1".into(),
                "NSR:StopPlace:2",
                "en",
                1,
                "331e1a1537aa87a615a7e6ad34c2329d8ecf477546b91a3769bc0734d1c15de8",
            ),
        ];
        for (nines, digest) in [
            (
                19,
                "ab904dfc48ffa44c2dcaffdea76e5776f93cb47fb94208002f70eed1338b7107",
            ),
            (
                20,
                "1cde85bb06e4a6e775fe318fdedea072abd4cda9a1689f85045b738fbfc2bedc",
            ),
            (
                27,
                "5014dcc1588b9562ca782620ed9d7478ba32bddc65534c4f815201435ba6b9bb",
            ),
            (
                28,
                "17005036bf1823638b98e2335612dd08742ad098138bdf6af4bf55090913e08f",
            ),
            (
                29,
                "0bcafef48513f2505ba8fdd176c1ce628607d8975bad8275dbabc656d6b920ca",
            ),
            (
                83,
                "c77bf8351481332864ef254d3f7766d6e8fe69377c602fc53412cc0c797faef7",
            ),
            (
                84,
                "5af422d10f528da4986492bcbb4f9176bfaf85df5f3342cbd892c3c0e771cbfa",
            ),
        ] {
            let from = format!("NSR:StopPlace:{}", "9".repeat(nines));
            cases.push((from, "NSR:StopPlace:2", "en", 24, digest));
        }
        for (from, to, language, hours, digest) in cases {
            let route = json!({"from": {"id": from}, "to": {"id": to}});
            assert_eq!(
                file(Path::new("/c"), &route, language, hours),
                PathBuf::from(format!("/c/{digest}.json")),
                "{from}/{to}/{language}/{hours}"
            );
        }
    }
}
