//! The few Python semantics the helper's contract depends on: `str.strip()`
//! whitespace, lengths in code points, truthiness, `str()` of JSON values,
//! and `json.dump`'s default output format (`", "` and `": "` separators,
//! UTF-8, `repr` floats), so replies and cache files keep the bytes the
//! Python helper wrote.

use std::io::{self, Write};

use serde::Serialize;
use serde_json::ser::Formatter;
use serde_json::{Map, Value};

/// Python's `str.isspace()`: Unicode White_Space plus U+001C..U+001F, which
/// Python counts as whitespace (bidi classes B and S) and Rust does not.
pub fn is_space(c: char) -> bool {
    c.is_whitespace() || ('\u{1c}'..='\u{1f}').contains(&c)
}

/// `str.strip()`.
pub fn strip(text: &str) -> &str {
    text.trim_matches(is_space)
}

/// `len(str)`: code points, not bytes.
pub fn len(text: &str) -> usize {
    text.chars().count()
}

/// `bool(value)`; a missing key (`dict.get` returning `None`) is false.
pub fn truthy(value: Option<&Value>) -> bool {
    match value {
        None | Some(Value::Null) => false,
        Some(Value::Bool(b)) => *b,
        Some(Value::Number(n)) => n.as_f64().is_some_and(|f| f != 0.0),
        Some(Value::String(s)) => !s.is_empty(),
        Some(Value::Array(a)) => !a.is_empty(),
        Some(Value::Object(o)) => !o.is_empty(),
    }
}

/// `value or None`: the value when it is truthy.
pub fn or_none(value: Option<&Value>) -> Option<&Value> {
    if truthy(value) { value } else { None }
}

/// The receiver of a Python `x.get(key)` call where `x` is
/// `something or {}`: a dict, the empty default, or a truthy non-dict whose
/// `.get` would raise `AttributeError`.
#[derive(Clone, Copy)]
pub enum Dict<'a> {
    Map(&'a Map<String, Value>),
    Empty,
    Other,
}

impl<'a> Dict<'a> {
    /// `value or {}`.
    pub fn or_empty(value: Option<&'a Value>) -> Dict<'a> {
        match or_none(value) {
            None => Dict::Empty,
            Some(Value::Object(map)) => Dict::Map(map),
            Some(_) => Dict::Other,
        }
    }

    /// `.get(key)`; `Err` where Python raises `AttributeError`.
    pub fn get(self, key: &str) -> Result<Option<&'a Value>, ()> {
        match self {
            Dict::Map(map) => Ok(map.get(key)),
            Dict::Empty => Ok(None),
            Dict::Other => Err(()),
        }
    }
}

/// `value is True`.
pub fn is_true(value: Option<&Value>) -> bool {
    matches!(value, Some(Value::Bool(true)))
}

/// `str(value)` of a parsed JSON value.
pub fn str_of(value: &Value) -> String {
    match value {
        Value::String(s) => s.clone(),
        other => repr(other),
    }
}

/// `repr(value)`. Strings follow Python's quoting; outside ASCII, only C0/C1
/// controls and a few invisible characters are escaped (Python escapes every
/// non-printable code point). Entur never sends such ids; this only keeps
/// odd data deterministic.
pub fn repr(value: &Value) -> String {
    match value {
        Value::Null => "None".into(),
        Value::Bool(true) => "True".into(),
        Value::Bool(false) => "False".into(),
        Value::Number(n) => match (n.as_i64(), n.as_u64(), n.as_f64()) {
            (Some(i), _, _) => i.to_string(),
            (None, Some(u), _) => u.to_string(),
            (_, _, Some(f)) => float_repr(f),
            _ => n.to_string(),
        },
        Value::String(s) => string_repr(s),
        Value::Array(items) => {
            let parts: Vec<String> = items.iter().map(repr).collect();
            format!("[{}]", parts.join(", "))
        }
        Value::Object(map) => {
            let parts: Vec<String> = map
                .iter()
                .map(|(k, v)| format!("{}: {}", string_repr(k), repr(v)))
                .collect();
            format!("{{{}}}", parts.join(", "))
        }
    }
}

fn string_repr(text: &str) -> String {
    let quote = if text.contains('\'') && !text.contains('"') {
        '"'
    } else {
        '\''
    };
    let mut out = String::with_capacity(text.len() + 2);
    out.push(quote);
    for c in text.chars() {
        match c {
            '\\' => out.push_str("\\\\"),
            '\t' => out.push_str("\\t"),
            '\n' => out.push_str("\\n"),
            '\r' => out.push_str("\\r"),
            c if c == quote => {
                out.push('\\');
                out.push(c);
            }
            c if (c as u32) < 0x20 || (0x7f..=0xa0).contains(&(c as u32)) || c == '\u{ad}' => {
                out.push_str(&format!("\\x{:02x}", c as u32));
            }
            c if c.is_whitespace() && c != ' '
                || matches!(c, '\u{200b}'..='\u{200f}' | '\u{feff}') =>
            {
                out.push_str(&format!("\\u{:04x}", c as u32));
            }
            c => out.push(c),
        }
    }
    out.push(quote);
    out
}

/// `repr(float)`: the shortest round-trip digits, positional for decimal
/// exponents -4..16, otherwise `d.ddde±XX`.
pub fn float_repr(value: f64) -> String {
    if !value.is_finite() {
        return if value.is_nan() {
            "nan".into()
        } else if value > 0.0 {
            "inf".into()
        } else {
            "-inf".into()
        };
    }
    let scientific = format!("{value:e}");
    let (mantissa, exponent) = scientific.split_once('e').unwrap_or((&scientific, "0"));
    let exponent: i32 = exponent.parse().unwrap_or(0);
    let negative = mantissa.starts_with('-');
    let digits: String = mantissa.chars().filter(char::is_ascii_digit).collect();
    let sign = if negative { "-" } else { "" };
    if (-4..16).contains(&exponent) {
        let point = exponent + 1;
        let body = if point <= 0 {
            format!("0.{}{}", "0".repeat((-point) as usize), digits)
        } else if (point as usize) >= digits.len() {
            format!("{}{}.0", digits, "0".repeat(point as usize - digits.len()))
        } else {
            format!(
                "{}.{}",
                &digits[..point as usize],
                &digits[point as usize..]
            )
        };
        format!("{sign}{body}")
    } else {
        let (first, rest) = digits.split_at(1);
        let fraction = if rest.is_empty() {
            String::new()
        } else {
            format!(".{rest}")
        };
        let exponent_sign = if exponent < 0 { '-' } else { '+' };
        format!(
            "{sign}{first}{fraction}e{exponent_sign}{:02}",
            exponent.unsigned_abs()
        )
    }
}

/// `json.dump`'s default layout: `", "` between items, `": "` after keys,
/// floats as `repr`. String escaping matches `ensure_ascii=False`.
struct PythonFormatter;

impl Formatter for PythonFormatter {
    fn begin_array_value<W: ?Sized + Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }

    fn begin_object_key<W: ?Sized + Write>(
        &mut self,
        writer: &mut W,
        first: bool,
    ) -> io::Result<()> {
        if first {
            Ok(())
        } else {
            writer.write_all(b", ")
        }
    }

    fn begin_object_value<W: ?Sized + Write>(&mut self, writer: &mut W) -> io::Result<()> {
        writer.write_all(b": ")
    }

    fn write_f64<W: ?Sized + Write>(&mut self, writer: &mut W, value: f64) -> io::Result<()> {
        writer.write_all(float_repr(value).as_bytes())
    }
}

/// `json.dumps(value, ensure_ascii=False)` as bytes.
pub fn dumps(value: &Value) -> Vec<u8> {
    let mut out = Vec::new();
    let mut serializer = serde_json::Serializer::with_formatter(&mut out, PythonFormatter);
    value
        .serialize(&mut serializer)
        .expect("serializing a Value into a Vec cannot fail");
    out
}

/// `json.dump(value, file, ensure_ascii=False)` followed by a newline.
pub fn dump_line(value: &Value) -> Vec<u8> {
    let mut out = dumps(value);
    out.push(b'\n');
    out
}

/// `json.loads(bytes)` for UTF-8 input: an optional UTF-8 byte order mark,
/// then exactly one JSON value surrounded by optional whitespace.
pub fn loads(data: &[u8]) -> Result<Value, ()> {
    let data = data.strip_prefix(b"\xef\xbb\xbf").unwrap_or(data);
    serde_json::from_slice(data).map_err(|_| ())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    /// Every code point for which Python 3.14's `str.isspace()` is true.
    const PYTHON_SPACES: &[u32] = &[
        0x09, 0x0a, 0x0b, 0x0c, 0x0d, 0x1c, 0x1d, 0x1e, 0x1f, 0x20, 0x85, 0xa0, 0x1680, 0x2000,
        0x2001, 0x2002, 0x2003, 0x2004, 0x2005, 0x2006, 0x2007, 0x2008, 0x2009, 0x200a, 0x2028,
        0x2029, 0x202f, 0x205f, 0x3000,
    ];

    #[test]
    fn whitespace_matches_python() {
        let ours: Vec<u32> = (0..=0x10ffffu32)
            .filter_map(char::from_u32)
            .filter(|&c| is_space(c))
            .map(|c| c as u32)
            .collect();
        assert_eq!(ours, PYTHON_SPACES);
        assert_eq!(strip("\u{1f} Oslo S\u{3000}"), "Oslo S");
    }

    #[test]
    fn code_point_lengths() {
        assert_eq!(len("Lillestrøm"), 10);
    }

    #[test]
    fn truthiness() {
        for value in [
            json!(null),
            json!(false),
            json!(0),
            json!(0.0),
            json!(""),
            json!([]),
            json!({}),
        ] {
            assert!(!truthy(Some(&value)), "{value}");
        }
        for value in [
            json!(true),
            json!(1),
            json!(-0.5),
            json!(" "),
            json!([0]),
            json!({"a": null}),
        ] {
            assert!(truthy(Some(&value)), "{value}");
        }
        assert!(!truthy(None));
    }

    #[test]
    fn str_and_repr() {
        assert_eq!(str_of(&json!("sj:1")), "sj:1");
        assert_eq!(str_of(&json!(42)), "42");
        assert_eq!(str_of(&json!(true)), "True");
        assert_eq!(str_of(&json!(null)), "None");
        assert_eq!(str_of(&json!(1.5)), "1.5");
        assert_eq!(
            str_of(&json!(["a", 1, {"k": "it's"}])),
            "['a', 1, {'k': \"it's\"}]"
        );
        assert_eq!(str_of(&json!({"q": "a'\"b\n"})), "{'q': 'a\\'\"b\\n'}");
    }

    #[test]
    fn float_repr_matches_python() {
        let cases = [
            (1.0, "1.0"),
            (0.1, "0.1"),
            (123.456, "123.456"),
            (1e15, "1000000000000000.0"),
            (1e16, "1e+16"),
            (1.5e16, "1.5e+16"),
            (0.0001, "0.0001"),
            (0.00001, "1e-05"),
            (-2.5e-7, "-2.5e-07"),
            (-0.0, "-0.0"),
            (1762430000.25, "1762430000.25"),
            (1.7976931348623157e308, "1.7976931348623157e+308"),
        ];
        for (value, text) in cases {
            assert_eq!(float_repr(value), text);
        }
    }

    #[test]
    fn dumps_uses_python_separators() {
        let value = json!({"b": [1, 2.0, "ø\n\u{7f}"], "a": {}, "c": [], "d": null});
        assert_eq!(
            String::from_utf8(dumps(&value)).unwrap(),
            "{\"b\": [1, 2.0, \"ø\\n\u{7f}\"], \"a\": {}, \"c\": [], \"d\": null}"
        );
        assert_eq!(dumps(&json!("\u{1}\u{8}")), b"\"\\u0001\\b\"");
    }

    #[test]
    fn loads_accepts_one_value_with_an_optional_bom() {
        assert_eq!(loads(b"\xef\xbb\xbf {\"a\": 1}\n"), Ok(json!({"a": 1})));
        assert!(loads(b"").is_err());
        assert!(loads(b"{} x").is_err());
        assert!(loads(b"\xff").is_err());
        assert!(loads(b"\"\\ud800\"").is_err());
    }
}
