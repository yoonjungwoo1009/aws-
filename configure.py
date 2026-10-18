"""비밀번호를 표시하지 않고 로컬 환경변수 파일을 한 번 생성한다."""

import argparse
import getpass
import os
import secrets
import shlex
from pathlib import Path

from werkzeug.security import generate_password_hash


def main():
    parser = argparse.ArgumentParser(description="로그인 설정 파일 생성 (기존 파일 덮어쓰기 금지)")
    parser.add_argument("--output", type=Path, default=Path(".env"))
    args = parser.parse_args()
    if args.output.exists():
        parser.error("설정 파일이 이미 있습니다. 기존 설정을 보존하고 별도 경로를 사용하세요.")

    username = input("로그인 아이디: ").strip()
    if not username or len(username) > 100:
        parser.error("아이디는 1~100자로 입력하세요.")
    password = getpass.getpass("새 테스트 비밀번호 (12자 이상, 입력 내용은 보이지 않음): ")
    if len(password) < 12 or len(password) > 1024:
        parser.error("비밀번호는 12~1024자로 입력하세요.")
    if password != getpass.getpass("비밀번호 확인: "):
        parser.error("비밀번호가 일치하지 않습니다.")

    values = {
        "LOGIN_USER": username,
        "PASSWORD_HASH": generate_password_hash(password),
        "SECRET_KEY": secrets.token_urlsafe(48),
        "APP_HTTPS": "false",  # 로컬/제한된 HTTP 테스트용. HTTPS 적용 시 true로 변경.
    }
    # O_EXCL은 이미 있는 파일을 덮어쓰지 않는다. 0o600은 소유자만 읽고 쓰게 한다.
    try:
        fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError:
        parser.error("파일을 생성할 수 없습니다. 경로와 권한을 확인하세요.")
    with os.fdopen(fd, "w", encoding="utf-8") as file:
        for name, value in values.items():
            # $가 포함된 해시도 셸에서 원문 그대로 읽도록 인용한다.
            file.write(f"{name}={shlex.quote(value)}\n")
    print("설정 파일을 생성했습니다. Git에 올리거나 내용을 공유하지 마세요.")


if __name__ == "__main__":
    main()
