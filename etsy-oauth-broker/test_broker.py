import http.client
import json
import logging
import os
import stat
import tempfile
import threading
import time
import unittest
import urllib.parse
from pathlib import Path

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


class BrokerCase(unittest.TestCase):

    def setUp(self):
        # pylint: disable-next=consider-using-with
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        self.logs = []
        self.handler = logging.Handler()
        self.handler.emit = self.logs.append
        logger = logging.getLogger("etsy.oauth")
        logger.setLevel(logging.INFO)
        logger.addHandler(self.handler)

    def tearDown(self):
        logging.getLogger("etsy.oauth").removeHandler(self.handler)
        self.temporary.cleanup()

    def _make(self, **kwargs):
        values = {"exchange": good_exchange}
        values.update(kwargs)
        return broker.Broker(KEY, self.directory, **values)

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
        written = list(self.directory.iterdir())
        self.assertEqual(1, len(written))
        self.assertEqual(REFRESH.encode("ascii"), written[0].read_bytes())
        self.assertFalse(written[0].name.startswith("."))
        self.assertEqual(0o600, stat.S_IMODE(written[0].stat().st_mode))
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
        self.assertEqual([], list(self.directory.iterdir()))

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
        self.assertEqual(1, len(list(self.directory.iterdir())))
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
                self.assertEqual([], list(self.directory.iterdir()))
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
        self.assertEqual([], list(self.directory.iterdir()))

    def test_second_handoff_does_not_replace_the_first(self):
        first = self._make(
            exchange=lambda _form: (200, "application/json", token_body())
        )
        callback, _state, _verifier = self._callback_of(first)
        self.assertEqual((200, b"ok"), first.callback(callback))
        original = next(self.directory.iterdir()).read_bytes()
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
        self.assertEqual(
            [original], [path.read_bytes() for path in self.directory.iterdir()]
        )
        self.assertNotIn("OTHERTOKENSENTINEL", json.dumps(second.status()))

    def test_restart_ignores_existing_bytes_and_expired_files_stay(self):
        existing = self.directory / "handoff-existing"
        existing.write_bytes(REFRESH.encode("ascii"))
        os.chmod(existing, 0o600)
        restarted = self._make()
        status = restarted.status()
        self.assertEqual("outstanding", status["blocked"])
        self.assertEqual(len(REFRESH), status["handoffs"][0]["bytes"])
        self.assertNotIn(REFRESH, json.dumps(status))
        old = time.time() - broker.HANDOFF_TTL_SECONDS - 5
        os.utime(existing, (old, old))
        aged = self._make(now=lambda: old + broker.HANDOFF_TTL_SECONDS + 10)
        self.assertEqual("expired", aged.status()["blocked"])
        self.assertEqual(REFRESH.encode("ascii"), existing.read_bytes())
        self.assertEqual(409, aged.start_flow()[0])

    def test_partial_blocks_without_a_read_of_its_bytes(self):
        partial = self.directory / ".partial-left"
        partial.write_bytes(REFRESH.encode("ascii"))
        instance = self._make()
        status = instance.status()
        self.assertEqual("partial", status["blocked"])
        self.assertEqual([], status["handoffs"])
        self.assertNotIn(REFRESH, json.dumps(status))
        self.assertEqual(409, instance.start_flow()[0])

    def test_directory_failures(self):
        outside = Path(self.temporary.name + "-link")
        outside.mkdir()
        self.addCleanup(outside.rmdir)
        link = self.directory / "linked"
        link.symlink_to(outside, target_is_directory=True)
        linked = broker.Broker(KEY, link, exchange=good_exchange)
        self.assertEqual("symlink", linked.directory_problem())
        self.assertEqual(409, linked.start_flow()[0])
        loose = Path(self.temporary.name + "-loose")
        loose.mkdir()
        loose.chmod(0o755)
        self.addCleanup(loose.rmdir)
        opened = broker.Broker(KEY, loose, exchange=good_exchange)
        self.assertEqual("mode", opened.directory_problem())
        missing = broker.Broker(KEY, self.directory / "missing", exchange=good_exchange)
        self.assertEqual("missing", missing.directory_problem())

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
                if key != "_keystring"
            },
            default=str,
        )
        self.assertNotIn(ACCESS, stored)
        self.assertNotIn(REFRESH, stored)


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
