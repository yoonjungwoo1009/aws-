"""환경변수로 설정하는 단일 사용자 Flask 사이트."""

import hashlib
import os
import secrets
from datetime import timedelta

from flask import Flask, abort, redirect, render_template, request, session, url_for
from werkzeug.security import check_password_hash


def create_app(test_config=None):
    """Gunicorn과 테스트에서 각각 앱을 만들 수 있게 구성한다."""
    app = Flask(__name__)
    https = os.environ.get("APP_HTTPS", "true").lower()
    if https not in {"true", "false"}:
        raise RuntimeError("APP_HTTPS must be true or false.")

    app.config.from_mapping(
        LOGIN_USER=os.environ.get("LOGIN_USER"),
        PASSWORD_HASH=os.environ.get("PASSWORD_HASH"),
        SECRET_KEY=os.environ.get("SECRET_KEY"),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=https == "true",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=1),
        MAX_CONTENT_LENGTH=16 * 1024,
    )
    if test_config is not None:
        app.config.update(test_config)

    missing = [name for name in ("LOGIN_USER", "PASSWORD_HASH", "SECRET_KEY")
               if not app.config.get(name)]
    if missing:
        raise RuntimeError("Required environment variables are missing: " + ", ".join(missing))
    login_user = app.config["LOGIN_USER"]
    if not 1 <= len(login_user) <= 100 or login_user != login_user.strip():
        raise RuntimeError("LOGIN_USER must be 1-100 characters without surrounding whitespace.")
    if len(app.config["SECRET_KEY"]) < 32:
        raise RuntimeError("SECRET_KEY must contain at least 32 characters.")
    try:
        password_hash = app.config["PASSWORD_HASH"]
        method, salt, digest = password_hash.split("$")
        if method.startswith("scrypt:"):
            digest_length = 128
        elif method.startswith("pbkdf2:"):
            digest_length = hashlib.new(method.split(":")[1]).digest_size * 2
        else:
            raise ValueError
        if not salt or len(digest) != digest_length or any(
            char not in "0123456789abcdef" for char in digest
        ):
            raise ValueError
        check_password_hash(password_hash, "")
    except (ValueError, TypeError):
        raise RuntimeError("PASSWORD_HASH must be generated with Werkzeug.") from None

    def csrf_token():
        if "csrf_token" not in session:
            session["csrf_token"] = secrets.token_urlsafe(32)
        return session["csrf_token"]

    app.jinja_env.globals["csrf_token"] = csrf_token

    def authenticated():
        return session.get("username") == app.config["LOGIN_USER"]

    def valid_csrf():
        expected = session.get("csrf_token")
        supplied = request.form.get("csrf_token", "")
        return isinstance(expected, str) and secrets.compare_digest(
            expected.encode("utf-8"), supplied.encode("utf-8")
        )

    @app.after_request
    def response_headers(response):
        # 로그아웃 후에도 브라우저 캐시에 회원 전용 글이 남지 않도록 한다.
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; style-src 'self'; img-src 'self'; "
            "script-src 'none'; object-src 'none'; base-uri 'none'; "
            "frame-ancestors 'none'; form-action 'self'"
        )
        return response

    @app.route("/", methods=["GET", "POST"])
    def login():
        if authenticated():
            return redirect(url_for("post"))

        error = None
        username = ""
        status = 200
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")
            if not valid_csrf():
                error = "요청이 만료되었습니다. 페이지를 새로고침한 뒤 다시 로그인해 주세요."
                status = 400
            else:
                # 비밀번호는 입력 그대로 검증한다. 공백을 임의로 제거하지 않는다.
                password_matches = 1 <= len(username) <= 100 and len(password) <= 1024 and check_password_hash(
                    app.config["PASSWORD_HASH"], password
                )
                if username == app.config["LOGIN_USER"] and password_matches:
                    session.clear()
                    session["username"] = username
                    session.permanent = True
                    return redirect(url_for("post"))
                error = "아이디 또는 비밀번호를 확인해 주세요."
                status = 401

        return render_template("login.html", error=error, username=username[:100]), status

    @app.get("/post")
    def post():
        if not authenticated():
            return redirect(url_for("login"))
        return render_template(
            "post.html",
            username=session["username"],
            post_title="나의 첫 번째 기록",
            post_body=(
                "작은 시작이 새로운 가능성을 만듭니다.\n\n"
                "이곳은 잠시 숨을 고르고, 생각과 이야기를 담아 두는 나만의 공간입니다.\n"
                "오늘의 작은 발견부터 천천히 기록해 보세요."
            ),
        )

    @app.post("/logout")
    def logout():
        if not valid_csrf():
            abort(400, description="Invalid or expired form. Reload the page and try again.")
        session.clear()
        return redirect(url_for("login"))

    return app
