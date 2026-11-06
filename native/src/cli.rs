//! The command line, parsed the way train_fetch.py's argparse parser did:
//! unique prefixes of long options, `--opt=value`, the last value wins, a
//! value may start with `-` only when it looks like a negative number or
//! contains a space, unknown arguments are reported after the known ones.

use std::ffi::{OsStr, OsString};
use std::os::unix::ffi::OsStrExt;

pub const USAGE: &str = "usage: foamy-train-helper [-h] [--search SEARCH] [--route-stdin] [--language {en,nb}] \
[--hours {1,...,24}] [--force] [--offline]";

pub const HELP: &str = "\nEntur direct rail departures (foamy-train).\n\noptions:\n  -h, --help           show this help message and exit\n  --search SEARCH\n  --route-stdin        Read the station pair (JSON from the widget entry in shell.json) from stdin\n  --language {en,nb}\n  --hours {1,...,24}   Look ahead 1–24 hours\n  --force\n  --offline\n";

#[derive(Debug, PartialEq)]
pub struct Args {
    pub search: Option<OsString>,
    pub route_stdin: bool,
    pub language: &'static str,
    pub hours: i64,
    pub force: bool,
    pub offline: bool,
}

impl Default for Args {
    fn default() -> Self {
        Args {
            search: None,
            route_stdin: false,
            language: "en",
            hours: 24,
            force: false,
            offline: false,
        }
    }
}

#[derive(Debug, PartialEq)]
pub enum Parsed {
    Run(Args),
    Help,
    /// A usage error: usage and this message on stderr, exit 2.
    Usage(String),
}

#[derive(Clone, Copy, PartialEq, Debug)]
enum Kind {
    Help,
    Flag,
    Value,
}

const OPTIONS: [(&str, Kind); 8] = [
    ("-h", Kind::Help),
    ("--help", Kind::Help),
    ("--search", Kind::Value),
    ("--route-stdin", Kind::Flag),
    ("--language", Kind::Value),
    ("--hours", Kind::Value),
    ("--force", Kind::Flag),
    ("--offline", Kind::Flag),
];

#[derive(Debug)]
enum Class {
    /// An argument (`A` in argparse's pattern).
    Argument,
    /// A known option, with the value after `=` if any.
    Option(&'static str, Kind, Option<OsString>),
    /// Something that looks like an option but isn't one.
    Unknown,
    /// `--`: everything after it is an argument.
    Separator,
}

fn find(name: &[u8]) -> Option<(&'static str, Kind)> {
    OPTIONS
        .iter()
        .copied()
        .find(|(option, _)| option.as_bytes() == name)
}

/// `^-\d+$|^-\d*\.\d+$`
fn negative_number(arg: &[u8]) -> bool {
    let Some(rest) = arg.strip_prefix(b"-") else {
        return false;
    };
    let digits = |s: &[u8]| s.iter().all(u8::is_ascii_digit);
    match rest.iter().position(|&b| b == b'.') {
        None => !rest.is_empty() && digits(rest),
        Some(dot) => digits(&rest[..dot]) && rest.len() > dot + 1 && digits(&rest[dot + 1..]),
    }
}

/// argparse's `_parse_optional`.
fn classify(arg: &OsStr) -> Result<Class, String> {
    let bytes = arg.as_bytes();
    if bytes.first() != Some(&b'-') || bytes == b"-" {
        return Ok(Class::Argument);
    }
    if bytes == b"--" {
        return Ok(Class::Separator);
    }
    if let Some((name, kind)) = find(bytes) {
        return Ok(Class::Option(name, kind, None));
    }
    let (name, explicit) = match bytes.iter().position(|&b| b == b'=') {
        Some(eq) => (
            &bytes[..eq],
            Some(OsStr::from_bytes(&bytes[eq + 1..]).to_owned()),
        ),
        None => (bytes, None),
    };
    if explicit.is_some()
        && let Some((option, kind)) = find(name)
    {
        return Ok(Class::Option(option, kind, explicit));
    }
    if bytes.starts_with(b"--") {
        let matches: Vec<_> = OPTIONS
            .iter()
            .filter(|(option, _)| option.as_bytes().starts_with(name))
            .collect();
        match matches.as_slice() {
            [(option, kind)] => return Ok(Class::Option(option, *kind, explicit)),
            [] => {}
            many => {
                let names: Vec<&str> = many.iter().map(|(option, _)| *option).collect();
                return Err(format!(
                    "ambiguous option: {} could match {}",
                    name.escape_ascii(),
                    names.join(", ")
                ));
            }
        }
    } else if bytes.starts_with(b"-h") {
        // `-hX`: -h with an explicit argument.
        return Ok(Class::Option(
            "-h",
            Kind::Help,
            Some(OsStr::from_bytes(&bytes[2..]).to_owned()),
        ));
    }
    if negative_number(bytes) || bytes.contains(&b' ') {
        return Ok(Class::Argument);
    }
    Ok(Class::Unknown)
}

/// `int(text)` for base 10: surrounding whitespace, a sign, ASCII digits
/// with single underscores between them.
pub fn python_int(text: &str) -> Option<i64> {
    let text = crate::py::strip(text);
    let (negative, digits) = match text.as_bytes().first() {
        Some(b'-') => (true, &text[1..]),
        Some(b'+') => (false, &text[1..]),
        _ => (false, text),
    };
    let bytes = digits.as_bytes();
    if bytes.is_empty()
        || bytes[0] == b'_'
        || bytes[bytes.len() - 1] == b'_'
        || digits.contains("__")
    {
        return None;
    }
    let mut value: i64 = 0;
    for &b in bytes {
        match b {
            b'_' => {}
            b'0'..=b'9' => value = value.checked_mul(10)?.checked_add(i64::from(b - b'0'))?,
            _ => return None,
        }
    }
    Some(if negative { -value } else { value })
}

fn text(value: &OsStr) -> String {
    value.to_string_lossy().into_owned()
}

pub fn parse(args: &[OsString]) -> Parsed {
    // argparse classifies every argument before consuming any.
    let mut classes = Vec::with_capacity(args.len());
    let mut after_separator = false;
    for arg in args {
        if after_separator {
            classes.push(Class::Argument);
            continue;
        }
        match classify(arg) {
            Ok(Class::Separator) => {
                after_separator = true;
                classes.push(Class::Separator);
            }
            Ok(class) => classes.push(class),
            Err(message) => return Parsed::Usage(message),
        }
    }
    let mut out = Args::default();
    let mut extras: Vec<String> = Vec::new();
    let mut i = 0;
    while i < args.len() {
        let class = &classes[i];
        i += 1;
        let (name, kind, explicit) = match class {
            Class::Option(name, kind, explicit) => (*name, *kind, explicit.clone()),
            Class::Separator => continue,
            Class::Argument | Class::Unknown => {
                extras.push(text(&args[i - 1]));
                continue;
            }
        };
        if kind != Kind::Value {
            if let Some(value) = explicit {
                return Parsed::Usage(format!(
                    "argument {name}: ignored explicit argument '{}'",
                    text(&value)
                ));
            }
            match (kind, name) {
                (Kind::Help, _) => return Parsed::Help,
                (_, "--route-stdin") => out.route_stdin = true,
                (_, "--force") => out.force = true,
                _ => out.offline = true,
            }
            continue;
        }
        let value = match explicit {
            Some(value) => value,
            None if matches!(classes.get(i), Some(Class::Argument)) => {
                i += 1;
                args[i - 1].clone()
            }
            None => return Parsed::Usage(format!("argument {name}: expected one argument")),
        };
        match name {
            "--search" => out.search = Some(value),
            "--language" => match value.as_bytes() {
                b"en" => out.language = "en",
                b"nb" => out.language = "nb",
                _ => {
                    return Parsed::Usage(format!(
                        "argument --language: invalid choice: '{}' (choose from en, nb)",
                        text(&value)
                    ));
                }
            },
            _ => match value.to_str().and_then(python_int) {
                Some(hours) if (1..=24).contains(&hours) => out.hours = hours,
                Some(hours) => {
                    return Parsed::Usage(format!(
                        "argument --hours: invalid choice: {hours} (choose from 1 to 24)"
                    ));
                }
                None => {
                    return Parsed::Usage(format!(
                        "argument --hours: invalid int value: '{}'",
                        text(&value)
                    ));
                }
            },
        }
    }
    if !extras.is_empty() {
        return Parsed::Usage(format!("unrecognized arguments: {}", extras.join(" ")));
    }
    Parsed::Run(out)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn run(list: &[&str]) -> Parsed {
        parse(&list.iter().map(OsString::from).collect::<Vec<_>>())
    }

    fn args(list: &[&str]) -> Args {
        match run(list) {
            Parsed::Run(args) => args,
            other => panic!("{list:?}: {other:?}"),
        }
    }

    #[test]
    fn widget_command_lines() {
        let a = args(&[
            "--language",
            "nb",
            "--hours",
            "6",
            "--route-stdin",
            "--force",
            "--offline",
        ]);
        assert_eq!(
            a,
            Args {
                route_stdin: true,
                language: "nb",
                hours: 6,
                force: true,
                offline: true,
                search: None
            }
        );
        assert_eq!(args(&["--search=-x"]).search, Some(OsString::from("-x")));
        assert_eq!(args(&["--search="]).search, Some(OsString::new()));
        assert_eq!(args(&[]), Args::default());
    }

    #[test]
    fn argparse_forms() {
        assert_eq!(args(&["--sea", "-5"]).search, Some(OsString::from("-5")));
        assert_eq!(
            args(&["--search", "-.5"]).search,
            Some(OsString::from("-.5"))
        );
        assert_eq!(
            args(&["--search", "-x y"]).search,
            Some(OsString::from("-x y"))
        );
        assert_eq!(args(&["--search", ""]).search, Some(OsString::new()));
        assert_eq!(args(&["--hours=7", "--hou", " 3 "]).hours, 3);
        assert_eq!(args(&["--hours", "+1_2"]).hours, 12);
        assert_eq!(args(&["--route", "--off", "--f", "--l=nb"]).language, "nb");
        for help in [&["-h"][..], &["--he", "--bogus"], &["--help", "x"]] {
            assert_eq!(run(help), Parsed::Help, "{help:?}");
        }
    }

    #[test]
    fn usage_errors() {
        for bad in [
            &["--hours", "0"][..],
            &["--hours", "25"],
            &["--hours", "1.5"],
            &["--hours", "1__2"],
            &["--hours="],
            &["--language", "de"],
            &["--bogus"],
            &["positional"],
            &["--search"],
            &["--search", "-x"],
            &["--search", "--force"],
            &["--h"],
            &["--force=1"],
            &["--", "--offline"],
            &["-x"],
            &["-hx"],
            &["-h", "--h"],
            &["--hours", "99", "-h"],
        ] {
            assert!(matches!(run(bad), Parsed::Usage(_)), "{bad:?}");
        }
    }

    #[test]
    fn python_ints() {
        assert_eq!(python_int(" 7\n"), Some(7));
        assert_eq!(python_int("-0"), Some(0));
        assert_eq!(python_int("007"), Some(7));
        for bad in [
            "",
            "_1",
            "1_",
            "1__0",
            "1.0",
            "0x10",
            "+",
            "99999999999999999999",
        ] {
            assert_eq!(python_int(bad), None, "{bad}");
        }
    }
}
