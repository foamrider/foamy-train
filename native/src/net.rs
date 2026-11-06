//! Requests to Entur: HTTPS with the system trust store, `https_proxy` and
//! `no_proxy` read the way Python's urllib reads them, bounded replies.

use std::collections::HashMap;
use std::ffi::OsString;
use std::sync::{Arc, OnceLock};
use std::time::Duration;

use serde_json::Value;
use ureq::config::AutoHeaderValue;
use ureq::tls::{Certificate, RootCerts, TlsConfig, TlsProvider};
use ureq::{Agent, Proxy, ProxyProtocol};

use crate::entur::{INVALID, Object};
use crate::{TrainError, py};

pub const ENDPOINT_ENV: &str = "FOAMY_TRAIN_ENTUR_URL";
const ENTUR: &str = "https://api.entur.io";
const API_PATH: &str = "/journey-planner/v3/graphql";
const GEOCODER_PATH: &str = "/geocoder/v3/autocomplete";
const CLIENT: &str = "foamrider-foamy-train";
const USER_AGENT: &str = "foamy-train-helper";
pub const MAX_BYTES: u64 = 2_000_000;

const HTTP: TrainError = TrainError::new("http_error", "Entur is unavailable. Try Refresh.");
const NETWORK: TrainError = TrainError::new(
    "network_error",
    "Cannot reach Entur. Check your connection and try Refresh.",
);

/// Where requests go: `https://api.entur.io`, or the test-only override.
pub struct Endpoint {
    base: String,
    https: bool,
    /// The URL's authority as urllib's `Request.host` holds it (for no_proxy).
    netloc: String,
}

impl Endpoint {
    /// From `FOAMY_TRAIN_ENTUR_URL` when set (it must be a loopback base URL;
    /// anything else fails every request rather than reaching another host).
    pub fn from_env() -> Result<Endpoint, TrainError> {
        match std::env::var_os(ENDPOINT_ENV) {
            None => Ok(Endpoint {
                base: ENTUR.into(),
                https: true,
                netloc: "api.entur.io".into(),
            }),
            Some(value) => value.to_str().and_then(loopback).ok_or(NETWORK),
        }
    }

    pub fn planner(&self) -> String {
        format!("{}{API_PATH}", self.base)
    }

    pub fn geocoder(&self, query: &str) -> String {
        format!(
            "{}{GEOCODER_PATH}?q={}&limit=8&stopPlaceTypes=railStation",
            self.base,
            quote_plus(query)
        )
    }
}

/// `http(s)://{127.0.0.1|localhost|[::1]}[:port][/]`.
fn loopback(text: &str) -> Option<Endpoint> {
    let (https, rest) = if let Some(rest) = text.strip_prefix("https://") {
        (true, rest)
    } else {
        (false, text.strip_prefix("http://")?)
    };
    let netloc = rest.strip_suffix('/').unwrap_or(rest);
    let host = ["127.0.0.1", "localhost", "[::1]"]
        .into_iter()
        .find(|h| netloc.starts_with(h))?;
    match &netloc[host.len()..] {
        "" => {}
        port => {
            let port = port.strip_prefix(':')?;
            if port.is_empty()
                || !port.bytes().all(|b| b.is_ascii_digit())
                || port.parse::<u16>().ok()? == 0
            {
                return None;
            }
        }
    }
    let scheme = if https { "https" } else { "http" };
    Some(Endpoint {
        base: format!("{scheme}://{netloc}"),
        https,
        netloc: netloc.into(),
    })
}

/// `urllib.parse.quote_plus`.
fn quote_plus(text: &str) -> String {
    let mut out = String::with_capacity(text.len());
    for byte in text.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'_' | b'.' | b'-' | b'~' => {
                out.push(byte as char)
            }
            b' ' => out.push('+'),
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

/// `urllib.parse.unquote`: percent escapes as UTF-8, invalid sequences replaced.
fn unquote(text: &str) -> String {
    let bytes = text.as_bytes();
    let mut out = Vec::with_capacity(bytes.len());
    let mut i = 0;
    while i < bytes.len() {
        let hex = |b: u8| (b as char).to_digit(16);
        if bytes[i] == b'%'
            && i + 2 < bytes.len()
            && let (Some(h), Some(l)) = (hex(bytes[i + 1]), hex(bytes[i + 2]))
        {
            out.push((h * 16 + l) as u8);
            i += 3;
            continue;
        }
        out.push(bytes[i]);
        i += 1;
    }
    String::from_utf8_lossy(&out).into_owned()
}

/// `urllib.request.getproxies_environment()`: `<scheme>_proxy` in any case,
/// then the all-lowercase-suffix spellings win (an empty one removes the
/// entry). Keys are the lowercased scheme (`https`, `no`, …).
pub fn env_proxies(
    vars: impl IntoIterator<Item = (OsString, OsString)>,
) -> HashMap<String, String> {
    let mut proxies = HashMap::new();
    let mut environment = Vec::new();
    for (name, value) in vars {
        let Some(name) = name.to_str().map(str::to_owned) else {
            continue;
        };
        let chars: Vec<char> = name.chars().collect();
        let n = chars.len();
        if n > 5
            && chars[n - 6] == '_'
            && chars[n - 5..].iter().collect::<String>().to_lowercase() == "proxy"
        {
            let scheme = chars[..n - 6].iter().collect::<String>().to_lowercase();
            let value = value.to_string_lossy().into_owned();
            if !value.is_empty() {
                proxies.insert(scheme.clone(), value.clone());
            }
            environment.push((name, value, scheme));
        }
    }
    for (name, value, scheme) in environment {
        if name.ends_with("_proxy") {
            if value.is_empty() {
                proxies.remove(&scheme);
            } else {
                proxies.insert(scheme, value);
            }
        }
    }
    proxies
}

/// `urllib.request.proxy_bypass_environment(host)`.
pub fn bypass(no_proxy: &str, host: &str) -> bool {
    if no_proxy == "*" {
        return true;
    }
    let host = host.to_lowercase();
    let host_only = split_port(&host);
    for name in no_proxy.split(',') {
        let name = py::strip(name);
        if name.is_empty() {
            continue;
        }
        let name = name.trim_start_matches('.').to_lowercase();
        if host_only == name || host == name {
            return true;
        }
        let dotted = format!(".{name}");
        if host_only.ends_with(&dotted) || host.ends_with(&dotted) {
            return true;
        }
    }
    false
}

/// `urllib.parse._splitport`: `host:digits` → host.
fn split_port(host: &str) -> &str {
    match host.rfind(':') {
        Some(i) if host[i + 1..].bytes().all(|b| b.is_ascii_digit()) => &host[..i],
        _ => host,
    }
}

/// A proxy as urllib's `_parse_proxy` and http.client read it: the scheme is
/// ignored (an https request always tunnels with CONNECT over plain TCP),
/// credentials need both a user and a password, a missing port is 443.
#[derive(Debug, PartialEq)]
pub struct ProxySpec {
    pub host: String,
    pub port: u16,
    pub credentials: Option<(String, String)>,
}

pub fn parse_proxy(proxy: &str) -> Result<ProxySpec, TrainError> {
    let rest = match proxy.find(':') {
        Some(i) if i > 0 && !proxy[..i].contains('/') => &proxy[i + 1..],
        _ => proxy,
    };
    let authority = if !rest.starts_with('/') {
        proxy
    } else if !rest.starts_with("//") {
        return Err(INVALID); // "proxy URL with no authority" is a ValueError
    } else {
        let end = match rest.find('@') {
            Some(at) => rest[at..].find('/').map(|e| e + at),
            None => rest[2..].find('/').map(|e| e + 2),
        };
        &rest[2..end.unwrap_or(rest.len()).max(2)]
    };
    let (userinfo, hostport) = match authority.rfind('@') {
        Some(at) => (Some(&authority[..at]), &authority[at + 1..]),
        None => (None, authority),
    };
    let credentials = userinfo.and_then(|info| {
        let (user, password) = info.split_once(':')?;
        (!user.is_empty() && !password.is_empty()).then(|| (unquote(user), unquote(password)))
    });
    let hostport = unquote(hostport);
    let (mut host, port) = match (hostport.rfind(':'), hostport.rfind(']')) {
        (Some(i), j) if j.is_none_or(|j| i > j) => {
            let digits = &hostport[i + 1..];
            let port = if digits.is_empty() {
                443
            } else {
                match crate::cli::python_int(digits) {
                    Some(port) => u16::try_from(port).map_err(|_| NETWORK)?,
                    None => return Err(INVALID), // http.client.InvalidURL
                }
            };
            (hostport[..i].to_owned(), port)
        }
        _ => (hostport.clone(), 443),
    };
    if host.len() >= 2 && host.starts_with('[') && host.ends_with(']') {
        host = host[1..host.len() - 1].to_owned();
    }
    Ok(ProxySpec {
        host,
        port,
        credentials,
    })
}

/// The CONNECT proxy for an https request to `netloc`, if any.
fn proxy_for(netloc: &str) -> Result<Option<Proxy>, TrainError> {
    let proxies = env_proxies(std::env::vars_os());
    let Some(proxy) = proxies.get("https") else {
        return Ok(None);
    };
    if proxies.get("no").is_some_and(|no| bypass(no, netloc)) {
        return Ok(None);
    }
    let spec = parse_proxy(proxy)?;
    if spec.host.is_empty() {
        return Err(NETWORK);
    }
    let host = if spec.host.contains(':') {
        format!("[{}]", spec.host)
    } else {
        spec.host
    };
    let mut builder = Proxy::builder(ProxyProtocol::Http)
        .host(&host)
        .port(spec.port);
    if let Some((user, password)) = &spec.credentials {
        builder = builder.username(user).password(password);
    }
    builder.build().map(Some).map_err(|_| NETWORK)
}

/// The system trust store (rustls-native-certs: `SSL_CERT_FILE` /
/// `SSL_CERT_DIR` when set, else the OpenSSL default locations), loaded once.
fn roots() -> Arc<Vec<Certificate<'static>>> {
    static ROOTS: OnceLock<Arc<Vec<Certificate<'static>>>> = OnceLock::new();
    ROOTS
        .get_or_init(|| {
            let found = rustls_native_certs::load_native_certs();
            Arc::new(
                found
                    .certs
                    .iter()
                    .map(|der| Certificate::from_der(der.as_ref()).to_owned())
                    .collect(),
            )
        })
        .clone()
}

/// One agent per run, so the widening request reuses the connection.
pub struct Client {
    endpoint: Endpoint,
    agent: Result<Agent, TrainError>,
}

impl Client {
    pub fn new() -> Result<Client, TrainError> {
        let endpoint = Endpoint::from_env()?;
        let agent = Client::agent(&endpoint);
        Ok(Client { endpoint, agent })
    }

    fn agent(endpoint: &Endpoint) -> Result<Agent, TrainError> {
        let mut config = Agent::config_builder()
            .http_status_as_error(false)
            .max_redirects(10)
            .user_agent(USER_AGENT)
            .accept_encoding(AutoHeaderValue::None);
        if endpoint.https {
            let tls = TlsConfig::builder()
                .provider(TlsProvider::Rustls)
                .root_certs(RootCerts::Specific(roots()))
                .unversioned_rustls_crypto_provider(Arc::new(
                    rustls::crypto::ring::default_provider(),
                ))
                .build();
            config = config.tls_config(tls).proxy(proxy_for(&endpoint.netloc)?);
        } else {
            // The test override's plain-http URLs never use a proxy.
            config = config.proxy(None);
        }
        Ok(Agent::new_with_config(config.build()))
    }

    pub fn endpoint(&self) -> &Endpoint {
        &self.endpoint
    }

    /// GET (`body` None) or POST a JSON request; the reply must be a JSON
    /// object of at most MAX_BYTES. `timeout` bounds the whole request.
    pub fn request_json(
        &self,
        url: &str,
        body: Option<Vec<u8>>,
        timeout: Duration,
    ) -> Result<Object, TrainError> {
        let agent = self.agent.as_ref().map_err(|e| *e)?;
        let response = match body {
            Some(body) => headers(agent.post(url))
                .config()
                .timeout_global(Some(timeout))
                .build()
                .send(body),
            None => headers(agent.get(url))
                .config()
                .timeout_global(Some(timeout))
                .build()
                .call(),
        };
        let mut response = response.map_err(classify)?;
        if !response.status().is_success() {
            return Err(HTTP);
        }
        // ureq's limit fails a read that reaches it even at the end of the
        // body, so allow one byte more and check the length here.
        let data = response
            .body_mut()
            .with_config()
            .limit(MAX_BYTES + 1)
            .read_to_vec()
            .map_err(classify)?;
        if data.len() as u64 > MAX_BYTES {
            return Err(INVALID);
        }
        match py::loads(&data) {
            Ok(Value::Object(object)) => Ok(object),
            _ => Err(INVALID),
        }
    }
}

fn headers<B>(request: ureq::RequestBuilder<B>) -> ureq::RequestBuilder<B> {
    request
        .header("ET-Client-Name", CLIENT)
        .header("Accept", "application/json")
        .header("Content-Type", "application/json")
}

fn classify(error: ureq::Error) -> TrainError {
    match error {
        ureq::Error::BodyExceedsLimit(_) => INVALID,
        ureq::Error::StatusCode(_)
        | ureq::Error::TooManyRedirects
        | ureq::Error::RedirectFailed => HTTP,
        _ => NETWORK,
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn env(pairs: &[(&str, &str)]) -> HashMap<String, String> {
        env_proxies(
            pairs
                .iter()
                .map(|(k, v)| (OsString::from(k), OsString::from(v))),
        )
    }

    #[test]
    fn proxy_variables_follow_urllib() {
        assert_eq!(
            env(&[("HTTPS_PROXY", "a")])
                .get("https")
                .map(String::as_str),
            Some("a")
        );
        assert_eq!(
            env(&[("HTTPS_PROXY", "a"), ("https_proxy", "b")])
                .get("https")
                .map(String::as_str),
            Some("b")
        );
        assert_eq!(
            env(&[("https_proxy", "b"), ("HTTPS_PROXY", "a")])
                .get("https")
                .map(String::as_str),
            Some("b")
        );
        assert_eq!(
            env(&[("https_proxy", ""), ("HTTPS_PROXY", "a")]).get("https"),
            None
        );
        assert_eq!(
            env(&[("HTTPS_proxy", "c")])
                .get("https")
                .map(String::as_str),
            Some("c")
        );
        assert_eq!(
            env(&[("NO_PROXY", "x"), ("all_proxy", "y")])
                .get("no")
                .map(String::as_str),
            Some("x")
        );
        assert_eq!(env(&[("_proxy", "x"), ("proxy", "y")]).len(), 1);
    }

    #[test]
    fn no_proxy_matches_like_urllib() {
        assert!(bypass("*", "api.entur.io"));
        assert!(bypass("entur.io", "api.entur.io"));
        assert!(bypass(" .ENTUR.io ,x", "api.entur.io"));
        assert!(bypass("api.entur.io", "api.entur.io"));
        assert!(bypass("localhost:8443", "localhost:8443"));
        assert!(bypass("localhost", "LOCALHOST:8443"));
        assert!(!bypass("tur.io", "api.entur.io"));
        assert!(!bypass("*.entur.io", "api.entur.io"));
        assert!(!bypass("", "api.entur.io"));
    }

    #[test]
    fn proxy_urls_parse_like_urllib() {
        let spec = |host: &str, port, credentials: Option<(&str, &str)>| ProxySpec {
            host: host.into(),
            port,
            credentials: credentials.map(|(u, p)| (u.into(), p.into())),
        };
        assert_eq!(
            parse_proxy("http://proxy:3128"),
            Ok(spec("proxy", 3128, None))
        );
        assert_eq!(
            parse_proxy("https://proxy:3128/path"),
            Ok(spec("proxy", 3128, None))
        );
        assert_eq!(parse_proxy("socks5://proxy"), Ok(spec("proxy", 443, None)));
        assert_eq!(parse_proxy("proxy:3128"), Ok(spec("proxy", 3128, None)));
        assert_eq!(
            parse_proxy("http://u:p%40ss@proxy:8080"),
            Ok(spec("proxy", 8080, Some(("u", "p@ss"))))
        );
        assert_eq!(
            parse_proxy("http://u@proxy:8080"),
            Ok(spec("proxy", 8080, None))
        );
        assert_eq!(
            parse_proxy("http://u:@proxy:8080"),
            Ok(spec("proxy", 8080, None))
        );
        assert_eq!(
            parse_proxy("http://[::1]:3128"),
            Ok(spec("::1", 3128, None))
        );
        assert_eq!(parse_proxy("http://[::1]"), Ok(spec("::1", 443, None)));
        assert_eq!(parse_proxy("http://proxy:"), Ok(spec("proxy", 443, None)));
        assert_eq!(parse_proxy("http:/proxy"), Err(INVALID));
        assert_eq!(parse_proxy("http://proxy:x"), Err(INVALID));
        assert_eq!(parse_proxy("http://proxy:70000"), Err(NETWORK));
    }

    #[test]
    fn query_encoding_matches_quote_plus() {
        assert_eq!(
            quote_plus("Lillestrøm st/1&2"),
            "Lillestr%C3%B8m+st%2F1%262"
        );
        assert_eq!(quote_plus("-x_.~"), "-x_.~");
        assert_eq!(unquote("p%40ss%zz%4"), "p@ss%zz%4");
    }

    #[test]
    fn endpoint_override_is_loopback_only() {
        for good in [
            "http://127.0.0.1:8080",
            "https://localhost:1/",
            "http://[::1]:65535",
            "http://localhost",
        ] {
            assert!(loopback(good).is_some(), "{good}");
        }
        for bad in [
            "http://example.org",
            "http://127.0.0.1.evil:80",
            "http://localhost:0",
            "http://localhost:99999",
            "http://localhost:80/path",
            "ftp://localhost",
            "http://user@localhost",
            "http://localhost:",
            "localhost:80",
        ] {
            assert!(loopback(bad).is_none(), "{bad}");
        }
        assert_eq!(
            loopback("http://127.0.0.1:9/").unwrap().planner(),
            "http://127.0.0.1:9/journey-planner/v3/graphql"
        );
    }
}
