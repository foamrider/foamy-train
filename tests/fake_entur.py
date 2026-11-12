"""Test doubles for the departure helper, which the tests run as a process.

- FakeEntur: a local journey planner and geocoder (HTTP, or HTTPS with a test
  CA) that records every request and answers from queued replies.
- FakeProxy: a CONNECT proxy that records the tunnel request and forwards it
  to a FakeEntur (or, with trickle=True, sends its reply one byte every 0.5 s
  and never opens the tunnel).
- CertAuthority: a throwaway CA and server certificate (openssl CLI), trusted by the
  helper only through SSL_CERT_FILE.
- Helper: runs the helper with temporary HOME/XDG directories, an empty PATH,
  no proxy variables and FOAMY_TRAIN_ENTUR_URL pointing at a FakeEntur.

FOAMY_TRAIN_ENTUR_URL is the helper's test-only endpoint override: a base URL
on the loopback interface (http or https, `127.0.0.1`, `localhost` or
`[::1]`) that replaces https://api.entur.io. Nothing here reaches Entur.

FOAMY_HELPER is the helper's argv prefix as a JSON list (default: this
machine's bin/<arch>/foamy-train-helper), e.g. the aarch64 build through qemu
binfmt:
  FOAMY_HELPER='["bin/aarch64/foamy-train-helper"]' python3 -m unittest discover -s tests -p 'test_*.py'
"""

import base64
import hashlib
import json
import os
from pathlib import Path
import platform
import select
import shutil
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from zoneinfo import ZoneInfo

PLUGIN = Path(__file__).resolve().parents[1]
ENDPOINT_ENV = "FOAMY_TRAIN_ENTUR_URL"
API_PATH = "/journey-planner/v3/graphql"
GEOCODER_PATH = "/geocoder/v3/autocomplete"
CLIENT = "foamrider-foamy-train"
OSLO = ZoneInfo("Europe/Oslo")
ROUTE = {"from": {"id": "NSR:StopPlace:1", "name": "Central"}, "to": {"id": "NSR:StopPlace:2", "name": "Airport"}}

NOTICE_FIELDS = """id reportType summary { language value } description { language value }
 advice { language value } affects { __typename
 ... on AffectedLine { line { publicCode } }
 ... on AffectedStopPlace { stopPlace { name } }
 ... on AffectedStopPlaceOnLine { line { publicCode } stopPlace { name } }
 }"""
# The GraphQL document the helper must send, byte for byte.
QUERY = (
    """query Departures($from: String!, $to: String!, $searchWindow: Int!) {
 trip(from: {place: $from}, to: {place: $to}, numTripPatterns: 12, searchWindow: $searchWindow,
 maximumTransfers: 1, includeRealtimeCancellations: true, includePlannedCancellations: true,
 modes: {transportModes: [{transportMode: rail}]}) {
 tripPatterns { legs { id mode aimedStartTime expectedStartTime aimedEndTime expectedEndTime realtime
 line { publicCode } serviceJourney { id }
 fromEstimatedCall { cancellation realtime quay { publicCode } situations { """
    + NOTICE_FIELDS
    + """ } }
 toEstimatedCall { cancellation situations { """
    + NOTICE_FIELDS
    + """ } }
 situations { """
    + NOTICE_FIELDS
    + """ }
 } } } }"""
)
DEPARTURE_KEYS = [
    "id",
    "line",
    "aimed",
    "expected",
    "arrival",
    "aimedTime",
    "expectedTime",
    "arrivalTime",
    "delay",
    "duration",
    "platform",
    "realtime",
    "cancelled",
    "notices",
]
REPORT_KEYS = ["status", "route", "departures", "routeNotices", "updatedAt", "stale", "error", "errorCode"]


def helper_prefix():
    if os.environ.get("FOAMY_HELPER"):
        prefix = json.loads(os.environ["FOAMY_HELPER"])
    else:
        prefix = [str(PLUGIN / "bin" / platform.machine() / "foamy-train-helper")]
    # Resolve the program now: the helper runs with an empty PATH in a
    # temporary working directory, so a relative path is the plugin's.
    program = prefix[0] if "/" in prefix[0] else shutil.which(prefix[0])
    if program and not Path(program).is_absolute():
        program = str(PLUGIN / program)
    if not program:
        raise RuntimeError(f"helper program not found: {prefix[0]}")
    return [str(Path(program).resolve()), *prefix[1:]]


HELPER = helper_prefix()


# --- fixtures ------------------------------------------------------------------


def iso(epoch):
    return datetime.fromtimestamp(epoch, OSLO).isoformat()


def hm(epoch):
    return datetime.fromtimestamp(epoch, OSLO).strftime("%H:%M")


def base_time(minutes=8):
    """A whole minute a few minutes from now."""
    return (int(time.time()) // 60 + minutes) * 60


def leg(start, **changes):
    """A direct rail leg: aimed at `start`, 3 minutes late, 10 minutes long."""
    value = {
        "id": "train-1",
        "mode": "rail",
        "aimedStartTime": iso(start),
        "expectedStartTime": iso(start + 180),
        "aimedEndTime": iso(start + 600),
        "expectedEndTime": iso(start + 780),
        "line": {"publicCode": "R10"},
        "fromEstimatedCall": {"cancellation": False, "realtime": True, "quay": {"publicCode": "11"}},
        "toEstimatedCall": {"cancellation": False},
        "situations": [],
    }
    value.update(changes)
    return value


def on_time(start, **changes):
    return leg(start, **{"expectedStartTime": iso(start), "expectedEndTime": iso(start + 600), **changes})


def trips(*legs):
    return {"data": {"trip": {"tripPatterns": [{"legs": [value]} for value in legs]}}}


def busy(start, count=7):
    return trips(*[on_time(start + i * 300, id=f"t{i}", serviceJourney={"id": f"sj{i}"}) for i in range(count)])


def notice(identifier="n1", **changes):
    value = {
        "id": identifier,
        "reportType": "incident",
        "summary": [{"language": "en", "value": "Signal fault"}, {"language": "nb", "value": "Signalfeil"}],
        "description": [{"language": "en", "value": "Allow more time."}],
        "affects": [{"__typename": "AffectedServiceJourney"}],
    }
    value.update(changes)
    return value


def feature(identifier, name, display=None, types=("railStation",)):
    names = {"default": name}
    if display is not None:
        names["display"] = display
    return {"properties": {"id": identifier, "names": names, "stopPlaceTypes": list(types)}}


def cache_name(route=ROUTE, language="en", hours=24):
    key = route["from"]["id"] + "/" + route["to"]["id"] + "/" + language + "/" + str(hours)
    return hashlib.sha256(key.encode()).hexdigest() + ".json"


def python_json(value):
    """The helper's output format: Python's json.dump defaults, UTF-8, one line."""
    return json.dumps(value, ensure_ascii=False) + "\n"


# --- fake Entur ------------------------------------------------------------------


class Reply:
    def __init__(self, body=None, status=200, delay=0.0, raw=None, headers=None):
        self.status, self.delay, self.headers = status, delay, headers or {}
        self.data = raw if raw is not None else json.dumps(body).encode()


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):
        pass

    def handle_one_request(self):
        try:
            super().handle_one_request()
        except (ConnectionError, TimeoutError, ssl.SSLError):
            self.close_connection = True

    def answer(self):
        fake = self.server.fake
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        path, _, query = self.path.partition("?")
        fake.record(
            {
                "method": self.command,
                "path": path,
                "query": query,
                "body": body,
                "headers": {k.lower(): v for k, v in self.headers.items()},
            }
        )
        reply = fake.next_reply(path)
        if reply.delay and fake.closing.wait(reply.delay):
            return
        self.send_response(reply.status)
        for key, value in reply.headers.items():
            self.send_header(key, value)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply.data)))
        self.end_headers()
        self.wfile.write(reply.data)

    do_GET = do_POST = answer


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    block_on_close = False

    def handle_error(self, request, client_address):
        pass


class FakeEntur:
    """A local Entur. `reply(path, *replies)` queues answers; an empty queue
    answers with `fallback` (default: no departures, no stations)."""

    def __init__(self, tls=None):
        self.requests, self.lock, self.closing = [], threading.Lock(), threading.Event()
        self.queues = {API_PATH: [], GEOCODER_PATH: []}
        self.fallback = {API_PATH: Reply(trips()), GEOCODER_PATH: Reply({"features": []})}
        self.server = _Server(("127.0.0.1", 0), _Handler)
        self.server.fake = self
        self.tls = tls is not None
        if tls is not None:
            self.server.socket = tls.server_context().wrap_socket(self.server.socket, server_side=True)
        self.port = self.server.server_address[1]
        self.url = f"{'https' if self.tls else 'http'}://{'localhost' if self.tls else '127.0.0.1'}:{self.port}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def reply(self, path, *replies):
        with self.lock:
            self.queues[path].extend(r if isinstance(r, Reply) else Reply(r) for r in replies)

    def plan(self, *replies):
        self.reply(API_PATH, *replies)

    def stations(self, *replies):
        self.reply(GEOCODER_PATH, *replies)

    def next_reply(self, path):
        with self.lock:
            queue = self.queues.get(path)
            if queue:
                return queue.pop(0)
            return self.fallback.get(path) or Reply({"error": "unknown path"}, status=404)

    def record(self, request):
        with self.lock:
            self.requests.append(request)

    def taken(self, path=API_PATH):
        with self.lock:
            return [r for r in self.requests if r["path"] == path]

    def windows(self):
        return [json.loads(r["body"])["variables"]["searchWindow"] for r in self.taken(API_PATH)]

    def close(self):
        self.closing.set()
        self.server.shutdown()
        self.server.server_close()


class FakeProxy:
    """A CONNECT proxy that tunnels every request to `upstream` (host, port)
    and records the request line and headers of each tunnel. trickle=True:
    answer every CONNECT with a reply head that never ends, one byte every
    0.5 s for up to a minute."""

    def __init__(self, upstream, trickle=False):
        self.upstream, self.tunnels, self.lock = upstream, [], threading.Lock()
        self.trickle = trickle
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.closing = False
        threading.Thread(target=self.accept, daemon=True).start()

    def accept(self):
        while not self.closing:
            try:
                client, _ = self.listener.accept()
            except OSError:
                return
            threading.Thread(target=self.tunnel, args=(client,), daemon=True).start()

    def tunnel(self, client):
        with client:
            head = b""
            while b"\r\n\r\n" not in head and len(head) < 65536:
                chunk = client.recv(4096)
                if not chunk:
                    return
                head += chunk
            lines = head.split(b"\r\n\r\n", 1)[0].decode("latin-1").split("\r\n")
            headers = {}
            for line in lines[1:]:
                key, _, value = line.partition(":")
                headers[key.strip().lower()] = value.strip()
            with self.lock:
                self.tunnels.append({"request": lines[0], "headers": headers})
            if not lines[0].startswith("CONNECT "):
                client.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nContent-Length: 0\r\n\r\n")
                return
            if self.trickle:
                try:
                    client.sendall(b"HTTP/1.1 200 Connection established\r\nX-Slow: ")
                    for _ in range(120):
                        time.sleep(0.5)
                        client.sendall(b"x")
                except OSError:
                    pass
                return
            with socket.create_connection(self.upstream) as server:
                client.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
                rest = head.split(b"\r\n\r\n", 1)[1]
                if rest:
                    server.sendall(rest)
                sockets = [client, server]
                while True:
                    ready, _, _ = select.select(sockets, [], [], 30)
                    if not ready:
                        return
                    for source in ready:
                        data = source.recv(65536)
                        if not data:
                            return
                        (server if source is client else client).sendall(data)

    def seen(self):
        with self.lock:
            return list(self.tunnels)

    def close(self):
        self.closing = True
        self.listener.close()


class CertAuthority:
    """A CA and a server certificate for localhost, 127.0.0.1 and api.entur.io."""

    available = shutil.which("openssl") is not None

    def __init__(self, directory):
        self.dir = Path(directory)
        self.ca, self.cert, self.key = self.dir / "ca.pem", self.dir / "server.pem", self.dir / "server.key"
        extensions = self.dir / "server.ext"
        extensions.write_text(
            "subjectAltName=DNS:localhost,DNS:api.entur.io,IP:127.0.0.1\n"
            "basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature\n"
            "extendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\n"
            "authorityKeyIdentifier=keyid:always\n"
        )
        ec = ["-newkey", "ec", "-pkeyopt", "ec_paramgen_curve:prime256v1", "-nodes"]
        self.openssl(
            "req",
            "-x509",
            *ec,
            "-keyout",
            self.dir / "ca.key",
            "-out",
            self.ca,
            "-days",
            "30",
            "-subj",
            "/CN=foamy-train test CA",
            "-addext",
            "basicConstraints=critical,CA:TRUE",
            "-addext",
            "keyUsage=critical,keyCertSign,cRLSign",
        )
        self.openssl("req", *ec, "-keyout", self.key, "-out", self.dir / "server.csr", "-subj", "/CN=localhost")
        self.openssl(
            "x509",
            "-req",
            "-in",
            self.dir / "server.csr",
            "-CA",
            self.ca,
            "-CAkey",
            self.dir / "ca.key",
            "-CAcreateserial",
            "-out",
            self.cert,
            "-days",
            "30",
            "-extfile",
            extensions,
        )

    def openssl(self, *args):
        subprocess.run(["openssl", *map(str, args)], check=True, capture_output=True, timeout=30)

    def server_context(self):
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(self.cert, self.key)
        return context


# --- the helper as a process ------------------------------------------------------


class Result:
    def __init__(self, completed):
        self.code, self.stdout, self.stderr = completed.returncode, completed.stdout, completed.stderr

    def json(self):
        return json.loads(self.stdout)


class Helper:
    """Runs the helper in a private temporary home."""

    def __init__(self, directory, endpoint):
        self.root = Path(directory)
        self.home = self.root / "home"
        self.cache = self.root / "cache"
        self.cache_dir = self.cache / "foamy.train"
        self.home.mkdir()
        empty = self.root / "bin"
        empty.mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": str(empty),
            "LANG": "C.UTF-8",
            "TZ": "America/New_York",
            "XDG_CACHE_HOME": str(self.cache),
            "XDG_CONFIG_HOME": str(self.root / "config"),
            "XDG_STATE_HOME": str(self.root / "state"),
            ENDPOINT_ENV: endpoint,
        }

    def run(self, *args, stdin=b"", env=None, timeout=30):
        environment = dict(self.env)
        for key, value in (env or {}).items():
            if value is None:
                environment.pop(key, None)
            else:
                environment[key] = value
        if isinstance(stdin, str):
            stdin = stdin.encode()
        completed = subprocess.run(
            [*HELPER, *args], input=stdin, env=environment, capture_output=True, timeout=timeout, cwd=self.root
        )
        return Result(completed)

    def json(self, *args, **kwargs):
        """Runs the helper and checks the reply contract: exit 0, empty
        stderr, exactly one line of JSON in Python's json.dump format."""
        result = self.run(*args, **kwargs)
        assert result.code == 0, (result.code, result.stderr)
        assert result.stderr == b"", result.stderr
        text = result.stdout.decode()
        value = json.loads(text)
        assert text == python_json(value), text
        return value

    def fetch(self, *args, route=ROUTE, **kwargs):
        stdin = route if isinstance(route, (str, bytes)) else json.dumps(route)
        return self.json("--route-stdin", *args, stdin=stdin, **kwargs)

    def cache_file(self, route=ROUTE, language="en", hours=24):
        return self.cache_dir / cache_name(route, language, hours)

    def write_cache(self, value, route=ROUTE, language="en", hours=24):
        path = self.cache_file(route, language, hours)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        path.write_text(python_json(value))
        path.chmod(0o600)
        return path

    def read_cache(self, route=ROUTE, language="en", hours=24):
        return json.loads(self.cache_file(route, language, hours).read_text())


def basic(user, password):
    return "Basic " + base64.b64encode(f"{user}:{password}".encode()).decode()


def temporary():
    return tempfile.TemporaryDirectory(prefix="foamy-train-test-")
