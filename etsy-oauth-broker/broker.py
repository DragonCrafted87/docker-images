"""One-shot Etsy authorization-code broker.

State stays in memory. A successful exchange writes the raw refresh
token into one namespace Secret and drops the access token. Nothing
in this process returns a token.
"""

import base64
import hashlib
import json
import logging
import os
import secrets
import signal
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer

REDIRECT_URI = "https://etsy.stealthdragonland.net/oauth/callback"
SCOPES = "listings_r listings_w shops_r shops_w"
AUTH_ENDPOINT = "https://www.etsy.com/oauth/connect"
TOKEN_ENDPOINT = "https://api.etsy.com/v3/public/oauth/token"
ISSUER = "https://openapi.etsy.com"

STATE_TTL_SECONDS = 600
HANDOFF_TTL_SECONDS = 24 * 60 * 60
MAX_PENDING = 3
MAX_QUERY_BYTES = 4096
MAX_TOKEN_BODY = 65536
MAX_REFRESH_BYTES = 2048
EXCHANGE_TIMEOUT_SECONDS = 10
CALLBACK_LIMIT = 30
CALLBACK_WINDOW_SECONDS = 60
REFRESH_SECRET_NAME = "etsy-refresh-token"
REFRESH_DATA_KEY = "refresh-token"
EXPORTED_AT = "etsy.stealthdragonland.net/exported-at"
MAX_SECRET_BODY = 65536

_LOG = logging.getLogger("etsy.oauth")
_UNRESERVED = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~")
_QUERY_KEYS = {"code", "error", "error_description", "error_uri", "iss", "state"}
_TOKEN_FIELDS = (
    "access_token",
    "expires_in",
    "refresh_token",
    "scope",
    "token_type",
)


class ExchangeFailed(Exception):
    pass


class HandoffBlocked(Exception):
    pass


class StoreError(Exception):
    pass


class _Flow:

    def __init__(self, verifier, scopes, redirect_uri, expires):
        self.verifier = verifier
        self.scopes = scopes
        self.redirect_uri = redirect_uri
        self.expires = expires


class _NoRedirect(urllib.request.HTTPRedirectHandler):

    def redirect_request(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, req, fp, code, msg, headers, newurl
    ):
        del req, fp, code, msg, headers, newurl
        raise ExchangeFailed


def challenge_for(verifier):
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


def new_verifier():
    verifier = secrets.token_urlsafe(32)
    if not 43 <= len(verifier) <= 128:
        raise RuntimeError
    if any(character not in _UNRESERVED for character in verifier):
        raise RuntimeError
    return verifier


def new_state():
    return secrets.token_urlsafe(32)


def authorization_url(client_id, state, challenge):
    # Etsy requires a space in scope to be %20. urlencode's default
    # quote_plus writes +, and Etsy then rejects the permission list.
    query = urllib.parse.urlencode(
        (
            ("response_type", "code"),
            ("client_id", client_id),
            ("redirect_uri", REDIRECT_URI),
            ("scope", SCOPES),
            ("state", state),
            ("code_challenge", challenge),
            ("code_challenge_method", "S256"),
        ),
        quote_via=urllib.parse.quote,
    )
    return AUTH_ENDPOINT + "?" + query


def token_request(form):
    if "client_secret" in form:
        raise ExchangeFailed
    encoded = urllib.parse.urlencode(form).encode("ascii")
    return urllib.request.Request(
        TOKEN_ENDPOINT,
        data=encoded,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )


def accepted_refresh(status, content_type, body):
    if status != 200 or len(body) > MAX_TOKEN_BODY:
        raise ExchangeFailed
    media = content_type.split(";", 1)[0].strip().lower()
    if media != "application/json":
        raise ExchangeFailed
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError):
        raise ExchangeFailed from None
    if not isinstance(parsed, dict):
        raise ExchangeFailed
    if any(field not in parsed for field in _TOKEN_FIELDS):
        raise ExchangeFailed
    expires = parsed["expires_in"]
    if isinstance(expires, bool) or not isinstance(expires, int):
        raise ExchangeFailed
    if expires <= 0 or expires > HANDOFF_TTL_SECONDS:
        raise ExchangeFailed
    if parsed["token_type"] != "Bearer":
        raise ExchangeFailed
    if not isinstance(parsed["access_token"], str) or not parsed["access_token"]:
        raise ExchangeFailed
    if not isinstance(parsed["scope"], str):
        raise ExchangeFailed
    if set(parsed["scope"].split()) != set(SCOPES.split()):
        raise ExchangeFailed
    refresh = parsed["refresh_token"]
    if not isinstance(refresh, str):
        raise ExchangeFailed
    if not refresh.isascii() or not 1 <= len(refresh) <= MAX_REFRESH_BYTES:
        raise ExchangeFailed
    if any(ord(character) < 33 or ord(character) == 127 for character in refresh):
        raise ExchangeFailed
    return refresh.encode("ascii")


def _post_token(form):
    request = token_request(form)
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=EXCHANGE_TIMEOUT_SECONDS) as response:
            payload = response.read(MAX_TOKEN_BODY + 1)
            header = response.headers.get("Content-Type", "")
            return response.status, header, payload
    except urllib.error.HTTPError as exc:
        payload = exc.read(MAX_TOKEN_BODY + 1)
        header = ""
        if exc.headers is not None:
            header = exc.headers.get("Content-Type", "")
        return exc.code, header, payload
    except (OSError, TimeoutError, urllib.error.URLError):
        raise ExchangeFailed from None


class _NoKubeRedirect(urllib.request.HTTPRedirectHandler):

    def redirect_request(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self, req, fp, code, msg, headers, newurl
    ):
        del req, fp, code, msg, headers, newurl
        raise StoreError


def secret_document(name, namespace, payload, exported_at):
    encoded = base64.b64encode(payload).decode("ascii")
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "annotations": {EXPORTED_AT: str(int(exported_at))},
        },
        "type": "Opaque",
        "data": {REFRESH_DATA_KEY: encoded},
    }


def _secret_data(document):
    if not isinstance(document, dict):
        return None
    if document.get("kind") != "Secret" or document.get("type") != "Opaque":
        return None
    metadata = document.get("metadata")
    data = document.get("data")
    if not isinstance(metadata, dict) or not isinstance(data, dict):
        return None
    if set(data) != {REFRESH_DATA_KEY}:
        return None
    raw = data[REFRESH_DATA_KEY]
    if not isinstance(raw, str):
        return None
    return raw


def describe_secret(document, now):
    raw = _secret_data(document)
    if raw is None:
        return "unexpected", None
    name = document["metadata"].get("name")
    if not isinstance(name, str) or not name:
        return "unexpected", None
    try:
        size = len(base64.b64decode(raw, validate=True))
    except ValueError:
        return "unexpected", None
    annotations = document["metadata"].get("annotations")
    if not isinstance(annotations, dict):
        annotations = {}
    stamp = annotations.get(EXPORTED_AT)
    if not isinstance(stamp, str) or not stamp.isdecimal():
        return "outstanding", (name, size, None)
    exported = int(stamp)
    reason = "outstanding"
    if now - exported >= HANDOFF_TTL_SECONDS:
        reason = "expired"
    return reason, (name, size, exported)


class SecretStore:

    def __init__(  # pylint: disable=too-many-arguments,too-many-positional-arguments
        self,
        namespace,
        name,
        api,
        token_path,
        ca_path,
        now,
        opener=None,
    ):
        self._namespace = namespace
        self._name = name
        self._api = api.rstrip("/")
        self._token_path = token_path
        self._ca_path = ca_path
        self._now = now
        self._opener = opener

    def bind(self, now):
        self._now = now

    def snapshot(self):
        reason, row = self._read()
        if row is None:
            return reason, []
        return reason, [row]

    def publish(self, payload):
        reason, _row = self._read()
        if reason is not None:
            raise HandoffBlocked
        body = json.dumps(
            secret_document(self._name, self._namespace, payload, self._now())
        ).encode("utf-8")
        try:
            status, _ignored = self._call("POST", self._collection(), body)
        except StoreError:
            raise HandoffBlocked from None
        if status not in (200, 201):
            raise HandoffBlocked

    def _collection(self):
        return self._api + "/api/v1/namespaces/" + self._namespace + "/secrets"

    def _item(self):
        return self._collection() + "/" + self._name

    def _read(self):
        try:
            status, payload = self._call("GET", self._item(), None)
        except StoreError:
            return "unavailable", None
        if status == 404:
            return None, None
        if status != 200:
            return "unavailable", None
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError):
            return "unavailable", None
        return describe_secret(document, self._now())

    def _call(self, method, url, body):
        if self._opener is not None:
            status, payload = self._opener(method, url, body)
        else:
            status, payload = self._http(method, url, body)
        if method == "GET" and status == 200:
            return 200, payload[:MAX_SECRET_BODY]
        return status, b""

    def _http(self, method, url, body):
        try:
            with open(self._token_path, encoding="utf-8") as handle:
                token = handle.read()
        except OSError:
            raise StoreError from None
        if token.endswith("\n"):
            token = token[:-1]
        if not token or any(character.isspace() for character in token):
            raise StoreError
        request = urllib.request.Request(url, data=body, method=method)
        request.add_header("Accept", "application/json")
        request.add_header("Authorization", "Bearer " + token)
        if body is not None:
            request.add_header("Content-Type", "application/json")
        context = ssl.create_default_context(cafile=self._ca_path)
        handler = urllib.request.HTTPSHandler(context=context)
        opener = urllib.request.build_opener(handler, _NoKubeRedirect)
        try:
            with opener.open(request, timeout=EXCHANGE_TIMEOUT_SECONDS) as response:
                return response.status, response.read(MAX_SECRET_BODY + 1)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read(MAX_SECRET_BODY + 1)
        except (OSError, TimeoutError, urllib.error.URLError, StoreError):
            raise StoreError from None


class Broker:  # pylint: disable=too-many-instance-attributes

    def __init__(  # pylint: disable=too-many-arguments
        self,
        keystring,
        store,
        *,
        exchange=None,
        now=None,
        monotonic=None,
        ttl=STATE_TTL_SECONDS,
        max_pending=MAX_PENDING,
        callback_limit=CALLBACK_LIMIT,
    ):
        if not isinstance(keystring, str) or not keystring:
            raise ValueError
        if any(character.isspace() for character in keystring):
            raise ValueError
        self._keystring = keystring
        self._store = store
        self._exchange = exchange
        self._now = time.time if now is None else now
        self._store.bind(self._now)
        self._monotonic = time.monotonic if monotonic is None else monotonic
        self._ttl = ttl
        self._max_pending = max_pending
        self._callback_limit = callback_limit
        self._flows = {}
        self._hits = deque()
        self._last_export = None
        self._lock = threading.Lock()

    def start_flow(self):
        with self._lock:
            self._sweep()
            reason = self._block_reason()
            if reason is not None:
                return 409, {"error": reason}
            if len(self._flows) >= self._max_pending:
                return 429, {"error": "pending-limit"}
            verifier = new_verifier()
            state = new_state()
            expires = self._monotonic() + self._ttl
            self._flows[state] = _Flow(verifier, SCOPES, REDIRECT_URI, expires)
            url = authorization_url(self._keystring, state, challenge_for(verifier))
        _LOG.info("flow-started")
        return 200, {"authorization_url": url, "expires_in": self._ttl}

    def callback(self, query):  # pylint: disable=too-many-return-statements
        if not self._allow_callback():
            return 429, b"error"
        try:
            params = _parse_query(query)
        except ValueError:
            _LOG.info("callback-rejected")
            return 400, b"error"
        if "error" in params:
            if self._consume(params.get("state", "")) is None:
                return 400, b"error"
            _LOG.info("denial")
            return 400, b"error"
        code = params.get("code")
        state = params.get("state")
        if code is None or state is None:
            return 400, b"error"
        flow = self._consume(state)
        if flow is None:
            _LOG.info("callback-unknown-state")
            return 400, b"error"
        if flow.scopes != SCOPES or flow.redirect_uri != REDIRECT_URI:
            self._mark("failed")
            return 500, b"error"
        if self._block_reason() is not None:
            self._mark("failed")
            return 500, b"error"
        refresh = b""
        try:
            status, content_type, body = self._exchange_code(flow, code)
            refresh = accepted_refresh(status, content_type, body)
            self._publish(refresh)
        except (
            ExchangeFailed,
            HandoffBlocked,
            StoreError,
            OSError,
            TimeoutError,
            ValueError,
        ):
            self._mark("failed")
            return 500, b"error"
        finally:
            refresh = b""
        self._mark("completed")
        _LOG.info("export-completed")
        return 200, b"ok"

    def status(self):
        with self._lock:
            self._sweep()
            reason, handoffs = self._store.snapshot()
            pending = len(self._flows)
            last_export = self._last_export
        rows = []
        for name, size, exported in handoffs:
            row = {"bytes": size, "name": name}
            if exported is not None:
                row["age_seconds"] = int(self._now() - exported)
            rows.append(row)
        return {
            "blocked": reason,
            "handoffs": rows,
            "last_export": last_export,
            "pending": pending,
        }

    def ready_problem(self):
        reason, _rows = self._store.snapshot()
        if reason == "unavailable":
            return "unavailable"
        return None

    def _exchange_code(self, flow, code):
        form = {
            "client_id": self._keystring,
            "code": code,
            "code_verifier": flow.verifier,
            "grant_type": "authorization_code",
            "redirect_uri": flow.redirect_uri,
        }
        if self._exchange is not None:
            return self._exchange(form)
        return _post_token(form)

    def _allow_callback(self):
        with self._lock:
            moment = self._monotonic()
            while self._hits and moment - self._hits[0] > CALLBACK_WINDOW_SECONDS:
                self._hits.popleft()
            if len(self._hits) >= self._callback_limit:
                return False
            self._hits.append(moment)
        return True

    def _consume(self, state):
        with self._lock:
            self._sweep()
            flow = self._flows.pop(state, None)
            if flow is None:
                return None
            if flow.expires <= self._monotonic():
                return None
        return flow

    def _sweep(self):
        moment = self._monotonic()
        expired = [
            state for state, flow in self._flows.items() if flow.expires <= moment
        ]
        for state in expired:
            del self._flows[state]

    def _block_reason(self):
        reason, _rows = self._store.snapshot()
        return reason

    def _publish(self, payload):
        with self._lock:
            self._store.publish(payload)

    def _mark(self, result):
        with self._lock:
            self._last_export = result
            if result == "failed":
                _LOG.info("export-failed")


def _parse_query(query):
    if not isinstance(query, str) or len(query) > MAX_QUERY_BYTES:
        raise ValueError
    try:
        parsed = urllib.parse.parse_qs(
            query,
            errors="strict",
            keep_blank_values=True,
            max_num_fields=8,
            separator="&",
        )
    except ValueError:
        raise ValueError from None
    if not set(parsed).issubset(_QUERY_KEYS):
        raise ValueError
    flat = {}
    for key, values in parsed.items():
        if len(values) != 1 or values[0] == "":
            raise ValueError
        flat[key] = values[0]
    if "error" in flat and "code" in flat:
        raise ValueError
    issuer = flat.pop("iss", None)
    if issuer is not None and issuer != ISSUER:
        raise ValueError
    return flat


class _Handler(BaseHTTPRequestHandler):  # pylint: disable=invalid-name
    protocol_version = "HTTP/1.1"
    server_version = "etsy-oauth-broker"

    def setup(self):
        super().setup()
        self.connection.settimeout(5)

    def log_message(self, format, *args):  # pylint: disable=redefined-builtin
        del format, args

    def log_error(self, format, *args):  # pylint: disable=redefined-builtin
        del format, args

    def handle_error(self):
        try:
            self._send(500, b"error")
        except OSError:
            pass

    def do_GET(self):  # pylint: disable=invalid-name
        self._route("GET")

    def do_POST(self):  # pylint: disable=invalid-name
        self._route("POST")

    def do_PUT(self):  # pylint: disable=invalid-name
        self._send(404, b"Not Found")

    def do_DELETE(self):  # pylint: disable=invalid-name
        self._send(404, b"Not Found")

    def do_HEAD(self):  # pylint: disable=invalid-name
        self._send(404, b"")

    def _route(self, method):
        if len(self.path) > MAX_QUERY_BYTES:
            self._send(414, b"error")
            return
        parsed = urllib.parse.urlsplit(self.path)
        try:
            if self.server.side == "public":
                self._public(method, parsed)
                return
            self._private(method, parsed)
        except (OSError, ValueError):
            self._send(500, b"error")

    def _public(self, method, parsed):
        if method != "GET":
            self._send(404, b"Not Found")
            return
        if parsed.path == "/healthz":
            self._send(200, b"ok")
            return
        if parsed.path == "/readyz":
            problem = self.server.broker.ready_problem()
            if problem is None:
                self._send(200, b"ok")
                return
            self._send(503, b"error")
            return
        if parsed.path != "/oauth/callback":
            self._send(404, b"Not Found")
            return
        status, body = self.server.broker.callback(parsed.query)
        self._send(status, body)

    def _private(self, method, parsed):
        if method == "GET" and parsed.path == "/status":
            payload = json.dumps(self.server.broker.status()).encode("utf-8")
            self._send(200, payload, "application/json")
            return
        if method == "POST" and parsed.path == "/flows":
            if self._content_length() != 0:
                self._send(400, b"error")
                return
            status, payload = self.server.broker.start_flow()
            body = json.dumps(payload).encode("utf-8")
            self._send(status, body, "application/json")
            return
        self._send(404, b"Not Found")

    def _content_length(self):
        raw = self.headers.get("Content-Length", "0")
        if not raw.isascii() or not raw.isdecimal():
            raise ValueError
        return int(raw)

    def _send(self, status, body, content_type="text/plain; charset=utf-8"):
        self.send_response(status)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Content-Type", content_type)
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        self.end_headers()
        if body and self.command != "HEAD":
            self.wfile.write(body)


class BoundServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True
    address_family = 2

    def __init__(self, address, broker, side):
        self.broker = broker
        self.side = side
        super().__init__(address, _Handler)


def load_keystring(path):
    with open(path, encoding="utf-8") as handle:
        value = handle.read()
    if value.endswith("\n"):
        value = value[:-1]
    if not value or any(character.isspace() for character in value):
        raise SystemExit(2)
    return value


def serve(broker, public_host, public_port, private_host, private_port):
    if private_host != "127.0.0.1":
        raise SystemExit(2)
    public = BoundServer((public_host, public_port), broker, "public")
    private = BoundServer((private_host, private_port), broker, "private")
    stop = threading.Event()

    def _shutdown(_signum, _frame):
        stop.set()
        public.shutdown()
        private.shutdown()

    signal.signal(signal.SIGTERM, _shutdown)
    signal.signal(signal.SIGINT, _shutdown)
    threads = (
        threading.Thread(
            target=public.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
        ),
        threading.Thread(
            target=private.serve_forever,
            kwargs={"poll_interval": 0.2},
            daemon=True,
        ),
    )
    for thread in threads:
        thread.start()
    _LOG.info("broker-started")
    stop.wait()
    public.server_close()
    private.server_close()


def main():
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    path = os.environ.get("ETSY_KEYSTRING_FILE", "/run/secrets/etsy/keystring")
    namespace = os.environ.get("ETSY_NAMESPACE", "etsy")
    secret_name = os.environ.get("ETSY_REFRESH_SECRET", REFRESH_SECRET_NAME)
    api = os.environ.get("KUBERNETES_API", "https://kubernetes.default.svc")
    token_path = os.environ.get(
        "KUBERNETES_TOKEN_FILE",
        "/var/run/secrets/kubernetes.io/serviceaccount/token",
    )
    ca_path = os.environ.get(
        "KUBERNETES_CA_FILE",
        "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt",
    )
    try:
        keystring = load_keystring(path)
    except OSError:
        raise SystemExit(2) from None
    store = SecretStore(namespace, secret_name, api, token_path, ca_path, time.time)
    broker = Broker(keystring, store)
    serve(broker, "0.0.0.0", 8080, "127.0.0.1", 8091)


if __name__ == "__main__":
    main()
