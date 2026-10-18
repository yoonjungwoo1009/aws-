"""외부 서버나 실제 계정 없이 인증 흐름과 보안 설정을 검사한다."""

import os
import secrets
import time
import unittest
from html.parser import HTMLParser
from unittest.mock import patch

from flask import render_template
from werkzeug.security import generate_password_hash

from app import create_app


class PageParser(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.stylesheets = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == "input" and "name" in attributes:
            self.inputs[attributes["name"]] = attributes
        if tag == "link" and attributes.get("rel") == "stylesheet":
            self.stylesheets.append(attributes.get("href", ""))


class LoginAppTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.username = "test-reader"
        # 앞뒤 공백도 비밀번호의 일부인지 정상 로그인으로 함께 검증한다.
        cls.password = " " + secrets.token_urlsafe(24) + " "
        cls.password_hash = generate_password_hash(cls.password)
        cls.secret_key = secrets.token_urlsafe(48)

    def settings(self, **overrides):
        config = {
            "TESTING": True,
            "LOGIN_USER": self.username,
            "PASSWORD_HASH": self.password_hash,
            "SECRET_KEY": self.secret_key,
            # Flask test_client의 HTTP 요청에서도 세션을 사용할 테스트 설정.
            "SESSION_COOKIE_SECURE": False,
        }
        config.update(overrides)
        return config

    def setUp(self):
        with patch.dict(os.environ, {"APP_HTTPS": "true"}):
            self.app = create_app(self.settings())
        self.client = self.app.test_client()

    def token(self, client=None, path="/"):
        response = (client or self.client).get(path)
        self.assertEqual(response.status_code, 200)
        page = PageParser(response.get_data(as_text=True))
        self.assertIn("csrf_token", page.inputs)
        token = page.inputs["csrf_token"].get("value", "")
        self.assertTrue(token, "CSRF hidden input에 토큰이 필요합니다.")
        return token

    def login(self, client=None, username=None):
        client = client or self.client
        return client.post("/", data={
            "username": self.username if username is None else username,
            "password": self.password,
            "csrf_token": self.token(client),
        })

    def assert_redirect(self, response, location):
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.headers["Location"], location)

    def test_required_environment_variables_fail_closed(self):
        required = {
            "LOGIN_USER": self.username,
            "PASSWORD_HASH": self.password_hash,
            "SECRET_KEY": self.secret_key,
        }
        for missing in required:
            with self.subTest(variable=missing):
                environment = dict(required)
                del environment[missing]
                with patch.dict(os.environ, environment, clear=True):
                    with self.assertRaisesRegex(RuntimeError, missing):
                        create_app()

    def test_short_secret_key_prevents_startup(self):
        with self.assertRaisesRegex(RuntimeError, "SECRET_KEY"):
            create_app(self.settings(SECRET_KEY="too-short"))

    def test_invalid_login_user_prevents_startup(self):
        for invalid in ("", "   ", " leading-space", "trailing-space ", "u" * 101):
            with self.subTest(length=len(invalid), padded=invalid != invalid.strip()):
                with self.assertRaisesRegex(RuntimeError, "LOGIN_USER"):
                    create_app(self.settings(LOGIN_USER=invalid))

    def test_invalid_https_setting_prevents_startup(self):
        with patch.dict(os.environ, {"APP_HTTPS": "sometimes"}):
            with self.assertRaisesRegex(RuntimeError, "APP_HTTPS"):
                create_app(self.settings())

    def test_invalid_password_hash_prevents_startup(self):
        invalid_hashes = (
            ("missing-separators", "not-a-hash"),
            ("unsupported-method", "unsupported$invalid$hash"),
            ("scrypt-empty-salt", "scrypt:32768:8:1$$" + "a" * 128),
            ("scrypt-nonhex-digest", "scrypt:32768:8:1$salt$" + "g" * 128),
            ("scrypt-short-digest", "scrypt:32768:8:1$salt$" + "a" * 126),
            ("pbkdf2-empty-salt", "pbkdf2:sha256:1000$$" + "a" * 64),
            ("pbkdf2-nonhex-digest", "pbkdf2:sha256:1000$salt$" + "g" * 64),
            ("pbkdf2-short-digest", "pbkdf2:sha256:1000$salt$" + "a" * 62),
        )
        for label, invalid in invalid_hashes:
            with self.subTest(format=label):
                with self.assertRaisesRegex(RuntimeError, "PASSWORD_HASH"):
                    create_app(self.settings(PASSWORD_HASH=invalid))

    def test_login_page_has_fields_and_external_stylesheet(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        page = PageParser(response.get_data(as_text=True))
        self.assertTrue({"username", "password", "csrf_token"} <= page.inputs.keys())
        self.assertEqual(page.inputs["password"].get("type"), "password")
        self.assertFalse(page.inputs["password"].get("value"))
        self.assertIn("/static/style.css", page.stylesheets)
        with self.client.get("/static/style.css") as stylesheet:
            self.assertEqual(stylesheet.status_code, 200)

    def test_anonymous_visitor_cannot_read_post(self):
        self.assert_redirect(self.client.get("/post"), "/")

    def test_login_rotates_session_and_displays_private_post(self):
        old_token = self.token()
        with self.client.session_transaction() as session:
            session["untrusted_old_value"] = "discard-me"
        response = self.client.post("/", data={
            "username": self.username,
            "password": self.password,
            "csrf_token": old_token,
        })
        self.assert_redirect(response, "/post")
        with self.client.session_transaction() as session:
            self.assertEqual(session.get("username"), self.username)
            self.assertTrue(session.permanent)
            self.assertNotIn("untrusted_old_value", session)
            self.assertNotIn("csrf_token", session)
        response = self.client.get("/post")
        self.assertEqual(response.status_code, 200)
        self.assertIn(self.username, response.get_data(as_text=True))
        self.assertNotEqual(self.token(path="/post"), old_token)
        self.assert_redirect(self.client.get("/"), "/post")

    def test_wrong_credentials_share_error_and_never_redisplay_password(self):
        cases = (
            (self.username, "incorrect-" + secrets.token_urlsafe(12)),
            ("unknown-user", self.password),
        )
        for username, password in cases:
            with self.subTest(case="password" if username == self.username else "username"):
                response = self.client.post("/", data={
                    "username": username,
                    "password": password,
                    "csrf_token": self.token(),
                })
                self.assertEqual(response.status_code, 401)
                body = response.get_data(as_text=True)
                self.assertIn("아이디 또는 비밀번호를 확인해 주세요.", body)
                self.assertTrue(password not in body, "입력한 비밀번호를 재표시하면 안 됩니다.")
                self.assertFalse(PageParser(body).inputs["password"].get("value"))
                self.assert_redirect(self.client.get("/post"), "/")

    def test_long_username_is_not_truncated_before_authentication(self):
        username = "u" * 100
        with patch.dict(os.environ, {"APP_HTTPS": "true"}):
            app = create_app(self.settings(LOGIN_USER=username))
        client = app.test_client()
        response = self.login(client, username=username + "-different-user")
        self.assertEqual(response.status_code, 401)
        self.assert_redirect(client.get("/post"), "/")
        self.assert_redirect(self.login(client, username=username), "/post")
        self.assertEqual(client.get("/post").status_code, 200)

    def test_login_rejects_missing_mismatched_and_unicode_csrf(self):
        self.token()
        for invalid in (None, "not-the-session-token", "한글-토큰"):
            with self.subTest(case="missing" if invalid is None else "invalid"):
                data = {"username": self.username, "password": self.password}
                if invalid is not None:
                    data["csrf_token"] = invalid
                response = self.client.post("/", data=data)
                self.assertEqual(response.status_code, 400)
                self.assert_redirect(self.client.get("/post"), "/")

    def test_logout_requires_post_and_clears_authentication(self):
        self.assert_redirect(self.login(), "/post")
        self.assertEqual(self.client.get("/logout").status_code, 405)
        self.assertEqual(self.client.get("/post").status_code, 200)
        token = self.token(path="/post")
        self.assert_redirect(self.client.post("/logout", data={"csrf_token": token}), "/")
        with self.client.session_transaction() as session:
            self.assertNotIn("username", session)
        self.assert_redirect(self.client.get("/post"), "/")

    def test_invalid_logout_csrf_keeps_existing_login(self):
        self.login()
        self.token(path="/post")
        for invalid in (None, "different-token", "잘못된-토큰"):
            with self.subTest(case="missing" if invalid is None else "invalid"):
                data = {} if invalid is None else {"csrf_token": invalid}
                self.assertEqual(self.client.post("/logout", data=data).status_code, 400)
                self.assertEqual(self.client.get("/post").status_code, 200)

    def test_https_cookie_configuration_and_protective_flags(self):
        for https in (None, "true", "false"):
            with self.subTest(https="default" if https is None else https):
                config = self.settings()
                del config["SESSION_COOKIE_SECURE"]
                with patch.dict(os.environ, {}, clear=True):
                    if https is not None:
                        os.environ["APP_HTTPS"] = https
                    app = create_app(config)
                cookie = app.test_client().get("/").headers["Set-Cookie"]
                self.assertIn("HttpOnly", cookie)
                self.assertIn("SameSite=Lax", cookie)
                self.assertEqual("Secure" in cookie, https != "false")

    def test_modified_session_signature_is_rejected(self):
        self.login()
        cookie_name = self.app.config["SESSION_COOKIE_NAME"]
        cookie = self.client.get_cookie(cookie_name)
        self.assertIsNotNone(cookie)
        payload, signature = cookie.value.rsplit(".", 1)
        replacement = "A" if signature[0] != "A" else "B"
        self.client.set_cookie(cookie_name, payload + "." + replacement + signature[1:])
        self.assert_redirect(self.client.get("/post"), "/")

    def test_expired_signed_session_is_rejected(self):
        serializer = self.app.session_interface.get_signing_serializer(self.app)
        past = time.time() - self.app.permanent_session_lifetime.total_seconds() - 60
        with patch("itsdangerous.timed.time.time", return_value=past):
            expired = serializer.dumps({"username": self.username, "_permanent": True})
        self.client.set_cookie(self.app.config["SESSION_COOKIE_NAME"], expired)
        self.assert_redirect(self.client.get("/post"), "/")

    def test_username_and_post_content_are_html_escaped(self):
        unsafe = '<script>alert("example")</script>'
        with patch.dict(os.environ, {"APP_HTTPS": "true"}):
            app = create_app(self.settings(LOGIN_USER=unsafe))
        client = app.test_client()
        rejected = client.post("/", data={
            "username": unsafe,
            "password": "wrong-password",
            "csrf_token": self.token(client),
        })
        self.assertEqual(rejected.status_code, 401)
        self.assertNotIn(unsafe, rejected.get_data(as_text=True))
        self.assertIn("&lt;script&gt;", rejected.get_data(as_text=True))
        self.assert_redirect(self.login(client, username=unsafe), "/post")
        post = client.get("/post").get_data(as_text=True)
        self.assertNotIn(unsafe, post)
        self.assertIn("&lt;script&gt;", post)
        with app.test_request_context():
            rendered = render_template("post.html", username=unsafe,
                                       post_title=unsafe, post_body=unsafe)
        self.assertNotIn(unsafe, rendered)
        self.assertGreaterEqual(rendered.count("&lt;script&gt;"), 3)

    def test_pages_disable_caching_and_send_security_headers(self):
        self.login()
        for path in ("/", "/post"):
            with self.subTest(path=path):
                headers = self.client.get(path).headers
                self.assertIn("no-store", headers.get("Cache-Control", ""))
                self.assertEqual(headers.get("X-Content-Type-Options"), "nosniff")
                self.assertEqual(headers.get("X-Frame-Options"), "DENY")
                self.assertIn("form-action 'self'", headers.get("Content-Security-Policy", ""))


if __name__ == "__main__":
    unittest.main()
