import base64
import http.client
import json
import logging
import threading
import time
import unittest
import urllib.parse

import broker

# cspell:ignore REFRESHTOKENSENTINEL ACCESSTOKENSENTINEL AUTHCODESENTINEL
# cspell:ignore PROVIDERERRORSENTINEL OTHERTOKENSENTINEL
# cspell:ignore vvkdljkejllufrvbhgeiegrnvufrhvrffnkvcknjvfid
# pylint: disable=protected-access

REFRESH = "REFRESHTOKENSENTINEL"
ACCESS = "ACCESSTOKENSENTINEL"
CODE = "AUTHCODESENTINEL"
DETAIL = "PROVIDERERRORSENTINEL"
KEY = "keystring-value"
SCOPES = "listings_r listings_w shops_r shops_w"


def token_body(refresh=REFRESH, access=ACCESS, **overrides):
    payload = {
        "access_token": access,
        "expires_in": 3600,
        "refresh_token": refresh,
        "scope": SCOPES,
        "token_type": "Bearer",
    }
    payload.update(overrides)
    return json.dumps(payload).encode("utf-8")


def good_exchange(form):
    del form
    return 200, "application/json", token_body()


class MemoryStore:

    def __init__(self):
        self.record = None
        self.down = False
        self._now = time.time

    def bind(self, now):
        self._now = now

    def snapshot(self):
        if self.down:
            return "unavailable", []
        if self.record is None:
            return None, []
        payload, exported = self.record
        row = (broker.REFRESH_SECRET_NAME, len(payload), exported)
        if self._now() - exported >= broker.HANDOFF_TTL_SECONDS:
            return "expired", [row]
        return "outstanding", [row]

    def publish(self, payload):
        reason, _rows = self.snapshot()
        if reason is not None:
            raise broker.HandoffBlocked
        self.record = (bytes(payload), self._now())


class BrokerCase(unittest.TestCase):  # pylint: disable=too-many-public-methods

    def setUp(self):
        self.store = MemoryStore()
        self.logs = []
        self.handler = logging.Handler()
        self.handler.emit = self.logs.append
        logger = logging.getLogger("etsy.oauth")
        logger.setLevel(logging.INFO)
        logger.addHandler(self.handler)

    def tearDown(self):
        logging.getLogger("etsy.oauth").removeHandler(self.handler)

    def _make(self, **kwargs):
        values = {"exchange": good_exchange}
        values.update(kwargs)
        return broker.Broker(KEY, self.store, **values)

    def _log_text(self):
        return " ".join(record.getMessage() for record in self.logs)

    def _assert_clean(self, *extra):
        text = self._log_text()
        for sentinel in (REFRESH, ACCESS, CODE, DETAIL, KEY, *extra):
            self.assertNotIn(sentinel, text)

    def _callback_of(self, instance):
        _query, parsed = self._flow_query(instance)
        state = parsed["state"][0]
        verifier = instance._flows[state].verifier
        return "code=" + CODE + "&state=" + state, state, verifier

    def _flow_query(self, instance):
        status, payload = instance.start_flow()
        self.assertEqual(200, status)
        self.assertNotIn("verifier", payload)
        self.assertNotIn(REFRESH, json.dumps(payload))
        parts = urllib.parse.urlsplit(payload["authorization_url"])
        self.assertEqual("https", parts.scheme)
        self.assertEqual("www.etsy.com", parts.netloc)
        self.assertEqual("/oauth/connect", parts.path)
        query = urllib.parse.parse_qs(parts.query)
        self.assertEqual(["code"], query["response_type"])
        self.assertEqual([KEY], query["client_id"])
        self.assertEqual([broker.REDIRECT_URI], query["redirect_uri"])
        self.assertEqual([SCOPES], query["scope"])
        self.assertEqual(["S256"], query["code_challenge_method"])
        self.assertEqual(
            [broker.challenge_for(self._verifier_for(instance, query["state"][0]))],
            query["code_challenge"],
        )
        return parts.query, query

    def test_issuer_parameter_is_accepted(self):
        instance = self._make()
        callback, _state, _verifier = self._callback_of(instance)
        issued = callback + "&iss=" + urllib.parse.quote(broker.ISSUER, safe="")
        self.assertEqual((200, b"ok"), instance.callback(issued))
        self.assertEqual(REFRESH.encode("ascii"), self.store.record[0])
        self.assertNotIn(broker.ISSUER, self._log_text())

    def test_wrong_issuer_does_not_consume_the_flow(self):
        instance = self._make()
        callback, state, _verifier = self._callback_of(instance)
        rejected = callback + "&iss=https://evil.example"
        self.assertEqual((400, b"error"), instance.callback(rejected))
        self.assertIn(state, instance._flows)
        self.assertIsNone(self.store.record)
        self.assertIn("callback-rejected", self._log_text())

    def test_scope_encoding_uses_percent_twenty(self):
        instance = self._make()
        _status, payload = instance.start_flow()
        parts = urllib.parse.urlsplit(payload["authorization_url"])
        self.assertIn(
            "scope=listings_r%20listings_w%20shops_r%20shops_w",
            parts.query,
        )
        self.assertNotIn("listings_r+", parts.query)

    def _verifier_for(self, instance, state):
        return instance._flows[state].verifier

    def test_pkce_vectors(self):
        vectors = {
            "dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk": (
                "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"
            ),
            "vvkdljkejllufrvbhgeiegrnvufrhvrffnkvcknjvfid": (
                "DSWlW2Abh-cf8CeLL8-g3hQ2WQyYdKyiu83u_s7nRhI"
            ),
        }
        for verifier, challenge in vectors.items():
            self.assertEqual(challenge, broker.challenge_for(verifier))

    def test_verifier_and_state_are_unreserved(self):
        seen = set()
        for _ in range(40):
            verifier = broker.new_verifier()
            state = broker.new_state()
            self.assertGreaterEqual(len(verifier), 43)
            self.assertLessEqual(len(verifier), 128)
            self.assertTrue(verifier.isascii())
            self.assertNotIn(verifier, seen)
            self.assertNotEqual(verifier, state)
            seen.add(verifier)

    def test_redirect_is_exact(self):
        self.assertEqual(
            "https://etsy.stealthdragonland.net/oauth/callback",
            broker.REDIRECT_URI,
        )
        rejected = (
            "https://etsy.stealthdragonland.net/oauth/callback/",
            "https://etsy.stealthdragonland.net/oauth/Callback",
            "https://etsy.stealthdragonland.net/oauth/callback?",
            "http://etsy.stealthdragonland.net/oauth/callback",
            "https://Etsy.stealthdragonland.net/oauth/callback",
        )
        for value in rejected:
            self.assertNotEqual(broker.REDIRECT_URI, value)

    def test_authorization_request_and_exchange_form(self):
        seen = {}

        def exchange(form):
            seen.update(form)
            return 200, "application/json", token_body()

        instance = self._make(exchange=exchange)
        callback, state, verifier = self._callback_of(instance)
        self.assertEqual((200, b"ok"), instance.callback(callback))
        self.assertEqual(
            {
                "client_id": KEY,
                "code": CODE,
                "code_verifier": verifier,
                "grant_type": "authorization_code",
                "redirect_uri": broker.REDIRECT_URI,
            },
            seen,
        )
        self.assertNotIn("client_secret", seen)
        request = broker.token_request(seen)
        self.assertEqual(broker.TOKEN_ENDPOINT, request.full_url)
        self.assertNotIn(b"client_secret", request.data)
        self.assertEqual(REFRESH.encode("ascii"), self.store.record[0])
        self._assert_clean(state)

    def test_bad_state_leaves_a_valid_flow(self):
        instance = self._make()
        _query, parsed = self._flow_query(instance)
        state = parsed["state"][0]
        self.assertEqual((400, b"error"), instance.callback(""))
        self.assertEqual((400, b"error"), instance.callback("code=" + CODE))
        self.assertEqual(
            (400, b"error"),
            instance.callback("code=" + CODE + "&state=not-the-flow"),
        )
        self.assertEqual(
            (400, b"error"),
            instance.callback("code=one&code=two&state=" + state),
        )
        self.assertIn(state, instance._flows)
        self.assertIsNone(self.store.record)

    def test_expired_state_does_not_drop_another_flow(self):
        clock = {"now": 0}

        def monotonic():
            return clock["now"]

        instance = self._make(monotonic=monotonic, ttl=10)
        _query, first = self._flow_query(instance)
        clock["now"] = 11
        _second, later = self._flow_query(instance)
        self.assertEqual(
            (400, b"error"),
            instance.callback("code=" + CODE + "&state=" + first["state"][0]),
        )
        self.assertNotIn(first["state"][0], instance._flows)
        self.assertIn(later["state"][0], instance._flows)

    def test_replay_and_concurrent_exchange_once(self):
        calls = {"count": 0}

        def exchange(_form):
            calls["count"] += 1
            time.sleep(0.05)
            return 200, "application/json", token_body()

        instance = self._make(exchange=exchange)
        callback, _state, _verifier = self._callback_of(instance)
        results = []

        def hit():
            results.append(instance.callback(callback))

        threads = [threading.Thread(target=hit) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(1, calls["count"])
        self.assertEqual(REFRESH.encode("ascii"), self.store.record[0])
        self.assertIn((200, b"ok"), results)
        self.assertIn((400, b"error"), results)

    def test_provider_failures_keep_the_sentinel_out_of_status(self):
        cases = (
            (400, "application/json", b'{"error":"' + DETAIL.encode() + b'"}'),
            (200, "text/plain", token_body()),
            (200, "application/json", b"not-json-" + DETAIL.encode()),
            (
                200,
                "application/json",
                b'{"refresh_token": "' + REFRESH.encode() + b'"}',
            ),
            (200, "application/json", token_body(expires_in=True)),
            (200, "application/json", token_body(expires_in="3600")),
            (200, "application/json", token_body(expires_in=0)),
            (200, "application/json", token_body(token_type="bearer")),
            (200, "application/json", token_body(scope="listings_r")),
            (200, "application/json", token_body(refresh=REFRESH + "\n")),
            (200, "application/json", b" " * (broker.MAX_TOKEN_BODY + 1)),
        )

        def exchange(_form):
            return cases[exchange.index]

        for index, _case in enumerate(cases):
            with self.subTest(index=index):
                exchange.index = index
                instance = self._make(exchange=exchange)
                callback, _state, _verifier = self._callback_of(instance)
                self.assertEqual((500, b"error"), instance.callback(callback))
                self.assertIsNone(self.store.record)
                self.assertEqual("failed", instance.status()["last_export"])
                self.assertNotIn(DETAIL, json.dumps(instance.status()))
                self.assertNotIn(REFRESH, json.dumps(instance.status()))
                self.assertEqual(0, instance.status()["pending"])

    def test_denial_and_timeout_do_not_reflect_details(self):
        def explode(_form):
            raise TimeoutError(DETAIL)

        instance = self._make(exchange=explode)
        _query, parsed = self._flow_query(instance)
        denied = "error=access_denied&error_description=" + DETAIL
        denied += "&state=" + parsed["state"][0]
        self.assertEqual((400, b"error"), instance.callback(denied))
        self.assertNotIn(parsed["state"][0], instance._flows)
        callback, _state, _verifier = self._callback_of(instance)
        self.assertEqual((500, b"error"), instance.callback(callback))
        self._assert_clean()
        self.assertIsNone(self.store.record)

    def test_second_handoff_does_not_replace_the_first(self):
        first = self._make(
            exchange=lambda _form: (200, "application/json", token_body())
        )
        callback, _state, _verifier = self._callback_of(first)
        self.assertEqual((200, b"ok"), first.callback(callback))
        original = self.store.record[0]
        second = self._make(
            exchange=lambda _form: (
                200,
                "application/json",
                token_body(refresh="OTHERTOKENSENTINEL"),
            )
        )
        status, payload = second.start_flow()
        self.assertEqual(409, status)
        self.assertEqual("outstanding", payload["error"])
        self.assertEqual(original, self.store.record[0])
        self.assertNotIn("OTHERTOKENSENTINEL", json.dumps(second.status()))

    def test_restart_reports_metadata_and_expired_tokens_stay(self):
        self.store.record = (REFRESH.encode("ascii"), time.time())
        restarted = self._make()
        status = restarted.status()
        self.assertEqual("outstanding", status["blocked"])
        self.assertEqual(len(REFRESH), status["handoffs"][0]["bytes"])
        self.assertEqual(broker.REFRESH_SECRET_NAME, status["handoffs"][0]["name"])
        self.assertNotIn(REFRESH, json.dumps(status))
        exported = 1_700_000_000
        self.store.record = (REFRESH.encode("ascii"), exported)
        aged = self._make(now=lambda: exported + broker.HANDOFF_TTL_SECONDS + 10)
        self.assertEqual("expired", aged.status()["blocked"])
        self.assertEqual(REFRESH.encode("ascii"), self.store.record[0])
        self.assertEqual(409, aged.start_flow()[0])

    def test_api_down_blocks_without_a_write(self):
        self.store.down = True
        instance = self._make()
        self.assertEqual("unavailable", instance.ready_problem())
        self.assertEqual(409, instance.start_flow()[0])
        self.assertIsNone(self.store.record)

    def test_pending_and_callback_limits(self):
        instance = self._make(max_pending=1, callback_limit=1)
        self._flow_query(instance)
        self.assertEqual(429, instance.start_flow()[0])
        self.assertEqual((400, b"error"), instance.callback("state=unknown"))
        self.assertEqual((429, b"error"), instance.callback("state=unknown"))

    def test_public_and_private_routes(self):
        instance = self._make()
        public = broker.BoundServer(("127.0.0.1", 0), instance, "public")
        private = broker.BoundServer(("127.0.0.1", 0), instance, "private")
        threads = []
        for server in (public, private):
            thread = threading.Thread(
                target=server.serve_forever, kwargs={"poll_interval": 0.05}
            )
            thread.start()
            threads.append(thread)

        def stop():
            public.shutdown()
            private.shutdown()
            public.server_close()
            private.server_close()
            for thread in threads:
                thread.join(timeout=2)

        self.addCleanup(stop)
        public_port = public.server_address[1]
        private_port = private.server_address[1]
        self.assertEqual("127.0.0.1", private.server_address[0])
        started = _request(
            private_port,
            "POST",
            "/flows",
            headers={"Content-Length": "0"},
        )
        self.assertEqual(200, started[0])
        self.assertEqual("no-store", started[2]["Cache-Control"])
        self.assertEqual("no-referrer", started[2]["Referrer-Policy"])
        payload = json.loads(started[1])
        parsed = urllib.parse.parse_qs(
            urllib.parse.urlsplit(payload["authorization_url"]).query
        )
        saved = _request(
            public_port,
            "GET",
            "/oauth/callback?code=" + CODE + "&state=" + parsed["state"][0],
        )
        self.assertEqual(200, saved[0])
        self.assertEqual(b"ok", saved[1])
        self.assertNotIn(b"<", saved[1])
        missing = _request(public_port, "GET", "/oauth/callback/")
        self.assertEqual(404, missing[0])
        self.assertEqual(b"Not Found", missing[1])
        other = _request(public_port, "GET", "/token")
        self.assertEqual(404, other[0])
        self.assertNotIn(REFRESH.encode(), other[1])
        reflected = _request(
            public_port,
            "GET",
            "/oauth/callback?error=access_denied&error_description=" + DETAIL,
        )
        self.assertEqual(b"error", reflected[1])
        self.assertNotIn(DETAIL.encode(), reflected[1])
        private_token = _request(private_port, "GET", "/oauth/callback?code=" + CODE)
        self.assertEqual(404, private_token[0])
        status = _request(private_port, "GET", "/status")
        self.assertNotIn(REFRESH.encode(), status[1])
        self.assertNotIn(ACCESS.encode(), status[1])
        self.assertNotIn(KEY.encode(), status[1])
        self._assert_clean()

    def test_private_listener_must_be_loopback(self):
        with self.assertRaises(SystemExit):
            broker.serve(self._make(), "127.0.0.1", 0, "0.0.0.0", 9)

    def test_no_access_token_attribute_after_export(self):
        instance = self._make()
        callback, _state, _verifier = self._callback_of(instance)
        instance.callback(callback)
        stored = json.dumps(
            {
                key: value
                for key, value in instance.__dict__.items()
                if key not in ("_keystring", "_store")
            },
            default=str,
        )
        self.assertNotIn(ACCESS, stored)
        self.assertNotIn(REFRESH, stored)
        self.assertEqual(REFRESH.encode("ascii"), self.store.record[0])


def _secret_store(opener, now):
    return broker.SecretStore(
        "etsy",
        broker.REFRESH_SECRET_NAME,
        "https://kubernetes.default.svc",
        "/no-token",
        "/no-ca",
        now,
        opener=opener,
    )


def _stored_secret(exported, refresh=REFRESH, extra=None):
    raw = base64.b64encode(refresh.encode("ascii")).decode("ascii")
    data = {broker.REFRESH_DATA_KEY: raw}
    if extra:
        data.update(extra)
    return {
        "kind": "Secret",
        "type": "Opaque",
        "metadata": {
            "name": broker.REFRESH_SECRET_NAME,
            "annotations": {broker.EXPORTED_AT: str(exported)},
        },
        "data": data,
    }


class SecretCase(unittest.TestCase):

    def test_document_holds_only_the_refresh_token(self):
        document = broker.secret_document(
            broker.REFRESH_SECRET_NAME,
            "etsy",
            REFRESH.encode("ascii"),
            100,
        )
        decoded = base64.b64decode(document["data"][broker.REFRESH_DATA_KEY])
        self.assertEqual(REFRESH.encode("ascii"), decoded)
        text = json.dumps(document)
        self.assertNotIn(ACCESS, text)
        self.assertNotIn("access_token", text)
        self.assertEqual("100", document["metadata"]["annotations"][broker.EXPORTED_AT])

    def test_publish_posts_one_secret_and_discards_the_response(self):
        calls = []

        def opener(method, url, body):
            calls.append((method, url, body))
            if method == "GET":
                return 404, b'{"kind":"Status"}'
            return 201, json.dumps(_stored_secret(100)).encode("utf-8")

        store = _secret_store(opener, lambda: 100)
        store.publish(REFRESH.encode("ascii"))
        self.assertEqual(["GET", "POST"], [call[0] for call in calls])
        self.assertEqual(
            "https://kubernetes.default.svc/api/v1/namespaces/etsy/secrets",
            calls[1][1],
        )
        posted = json.loads(calls[1][2].decode("utf-8"))
        self.assertEqual(
            REFRESH.encode("ascii"),
            base64.b64decode(posted["data"][broker.REFRESH_DATA_KEY]),
        )
        self.assertNotIn(ACCESS, calls[1][2].decode("utf-8"))
        self.assertNotIn(REFRESH, _store_text(store))

    def test_existing_secret_is_not_replaced(self):
        calls = []

        def opener(method, url, body):
            calls.append(method)
            del url, body
            return 200, json.dumps(_stored_secret(100)).encode("utf-8")

        store = _secret_store(opener, lambda: 150)
        reason, rows = store.snapshot()
        self.assertEqual("outstanding", reason)
        self.assertEqual(len(REFRESH), rows[0][1])
        self.assertNotIn(REFRESH, json.dumps(rows))
        with self.assertRaises(broker.HandoffBlocked):
            store.publish(b"OTHERTOKENSENTINEL")
        self.assertEqual(["GET", "GET"], calls)

    def test_expired_secret_is_not_deleted(self):
        calls = []

        def opener(method, url, body):
            calls.append(method)
            del url, body
            return 200, json.dumps(_stored_secret(100)).encode("utf-8")

        store = _secret_store(opener, lambda: 100 + broker.HANDOFF_TTL_SECONDS + 1)
        reason, _rows = store.snapshot()
        self.assertEqual("expired", reason)
        with self.assertRaises(broker.HandoffBlocked):
            store.publish(b"next")
        self.assertNotIn("DELETE", calls)
        self.assertNotIn("PUT", calls)
        self.assertNotIn("PATCH", calls)

    def test_conflict_does_not_overwrite(self):
        calls = []

        def opener(method, url, body):
            calls.append(method)
            del url, body
            if method == "GET":
                return 404, b""
            return 409, json.dumps(_stored_secret(100)).encode("utf-8")

        store = _secret_store(opener, lambda: 100)
        with self.assertRaises(broker.HandoffBlocked):
            store.publish(REFRESH.encode("ascii"))
        self.assertEqual(["GET", "POST"], calls)
        self.assertNotIn(REFRESH, _store_text(store))

    def test_unexpected_shape_blocks_without_a_post(self):
        calls = []
        document = _stored_secret(100, extra={"note": "nope"})

        def opener(method, url, body):
            calls.append(method)
            del url, body
            return 200, json.dumps(document).encode("utf-8")

        store = _secret_store(opener, lambda: 100)
        reason, rows = store.snapshot()
        self.assertEqual("unexpected", reason)
        self.assertEqual([], rows)
        with self.assertRaises(broker.HandoffBlocked):
            store.publish(b"next")
        self.assertEqual(["GET", "GET"], calls)
        self.assertNotIn(REFRESH, json.dumps(rows))

    def test_missing_annotation_stays_outstanding(self):
        document = _stored_secret(100)
        document["metadata"]["annotations"] = {}

        def opener(method, url, body):
            del method, url, body
            return 200, json.dumps(document).encode("utf-8")

        store = _secret_store(opener, lambda: 100)
        reason, rows = store.snapshot()
        self.assertEqual("outstanding", reason)
        self.assertIsNone(rows[0][2])
        self.assertNotIn(REFRESH, json.dumps(rows))


def _store_text(store):
    visible = {
        key: value
        for key, value in store.__dict__.items()
        if key not in ("_opener", "_now")
    }
    return json.dumps(visible)


def _request(port, method, path, headers=None):
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    connection.request(method, path, headers=headers or {})
    response = connection.getresponse()
    body = response.read()
    header_map = dict(response.getheaders())
    connection.close()
    return response.status, body, header_map


if __name__ == "__main__":
    unittest.main()
