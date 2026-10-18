# 합격자 조회 — Flask 로그인 웹사이트

로그인 화면에 **합격자 조회**를 표시하며, 로그인한 사용자만 글 하나를 읽을 수 있는 작은 사이트입니다.
화면은 아이보리 배경과 딥그린 포인트를 사용하고 모바일에서는 한 열로 배치합니다. 회원가입과 데이터베이스는 사용하지 않습니다.
현재 저장소에서 새로 구현했으며, 기존 EC2 코드를 확인하거나 EC2에 배포한 상태는 아닙니다.

## 파일과 역할

```text
aws-/
├── app.py                  # 환경변수, 인증, 세션, URL 처리
├── configure.py            # 비밀값을 표시하지 않고 설정 파일 생성
├── requirements.txt        # 실행 패키지와 고정 버전
├── templates/
│   ├── base.html           # 공통 레이아웃과 CSS 연결
│   ├── login.html          # 로그인 폼과 오류 메시지
│   └── post.html           # 환영 문구, 글, 로그아웃 폼
├── static/style.css        # 색상, 카드, 버튼, 모바일 대응
└── tests/test_app.py       # 인증·세션·CSRF 등 동작 검증
```

Python은 요청 처리, HTML은 화면 구조, CSS는 디자인을 맡습니다. 따라서 인증 코드를 건드리지 않고 화면을 수정할 수 있습니다.

## 1. 로컬 설치와 테스트

Python **3.10 이상**이 필요합니다. 현재 환경에서는 Python 3.12로 검증했습니다. 저장소 루트에서 Bash로 실행합니다.

```bash
cd /workspace/aws-
python3 --version
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
```

- `-m venv .venv`: 프로젝트 전용 패키지 공간을 만듭니다.
- `pip install -r`: 파일에 적힌 패키지를 설치합니다. `pip check`는 의존성 충돌을 확인합니다.
- `unittest discover -s tests -v`: `tests`에서 테스트를 찾아 각각의 결과를 표시합니다. 테스트 계정은 메모리에서만 무작위로 생성됩니다.

## 2. 설정과 실행

개인 터미널에서 **다른 서비스에서 사용하지 않는 테스트 비밀번호**로 설정을 만드세요.

```bash
.venv/bin/python configure.py
set -a
source ./.env
set +a
.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8000 'app:create_app()'
```

- 생성기는 아이디와 비밀번호를 질문합니다. 비밀번호는 화면에 표시하지 않고 해시만 저장합니다.
- `.env`는 소유자만 읽고 쓸 수 있는 권한(`600`)으로 생성하며, 기존 파일은 덮어쓰지 않습니다. Git에서도 제외합니다.
- `set -a`와 `source`는 설정을 현재 셸과 이후 실행하는 프로세스에 전달합니다. 이후 `set +a`로 자동 내보내기를 끕니다.
- `--workers 2`는 요청 처리 프로세스 두 개를 사용합니다.
- `--bind 127.0.0.1:8000`은 같은 컴퓨터에서만 접근 가능한 8000번 포트에서 수신합니다.
- `'app:create_app()'`은 `app.py`의 앱 생성 함수를 호출합니다. 이전의 `app:app` 대신 이 값을 사용하세요.
- 종료는 해당 터미널에서 `Ctrl+C`입니다. 가상환경 활성화 대신 `.venv/bin/`을 직접 지정해 Python 혼동을 피합니다.

일반 로컬 PC에서는 브라우저 주소창에 `http://127.0.0.1:8000`을 입력합니다. Codex 온보딩 화면은 이 주소의 웹 미리보기를 제공하지 않습니다.
앱이 `.env`를 자동으로 읽지는 않습니다. 새 셸에서는 설정을 다시 불러오세요.
`set -x`, 환경변수 전체 출력, `.env` 내용 출력은 비밀값을 로그에 남길 수 있으므로 사용하지 마세요.

| 환경변수 | 역할 |
| --- | --- |
| `LOGIN_USER` | 로그인 아이디 한 개 |
| `PASSWORD_HASH` | Werkzeug로 생성한 비밀번호 해시 |
| `SECRET_KEY` | 세션 서명용 무작위 비밀키 |
| `APP_HTTPS` | `false`: 제한된 HTTP 테스트, `true`: HTTPS용 Secure 쿠키 |

필수 설정이 없거나 키·해시 형식이 잘못되면 시작을 중단합니다. 비밀값은 오류에 출력하지 않습니다.
`APP_HTTPS`의 기본값은 `true`이며, 생성기는 로컬 테스트용으로 `false`를 저장합니다.
HTTP에서 `true`를 사용하면 브라우저가 세션 쿠키를 보내지 않아 로그인 상태가 유지되지 않습니다.
**이 변수는 쿠키 설정일 뿐, HTTPS 연결이나 인증서를 만들어 주지는 않습니다.**

## 3. 요청 흐름과 핵심 문법

1. `GET /`: Flask가 `login.html`을 렌더링하고 브라우저는 CSS를 별도로 받습니다.
2. 로그인 버튼: 폼의 `username`, `password`, 숨겨진 `csrf_token`을 `POST /`로 보냅니다.
3. 서버가 CSRF 토큰을 확인하고 `check_password_hash()`로 비밀번호를 검증합니다. 실패하면 계정 존재 여부를 구별하지 않는 오류를 표시합니다.
4. 성공하면 이전 세션을 비우고 사용자명과 만료 정보를 넣은 다음 `/post`로 리다이렉트합니다.
5. `GET /post`: 매번 인증을 확인합니다. 로그인하지 않았다면 `/`로 돌아갑니다.
6. `POST /logout`: CSRF를 확인하고 세션을 비웁니다. 이후 `/post` 접근이 차단됩니다.

- `@app.route(...)`, `@app.get(...)`: URL과 Python 함수를 연결하는 데코레이터입니다.
- `request.form.get(...)`: 제출한 폼 값을 읽습니다. `render_template(...)`은 값을 HTML에 전달합니다.
- `{{ ... }}`: 값을 출력합니다. `{% if error %}`는 오류가 있을 때만 내용을 표시합니다.
- `{% extends "base.html" %}`와 `{% block ... %}`: 공통 레이아웃을 재사용합니다.
- `url_for(...)`: 등록한 경로에 맞는 URL을 만듭니다.
- CSS `@media`: 화면 폭에 따라 스타일을 조정합니다. `:hover`는 마우스를 올렸을 때 적용합니다.

CSRF 토큰은 다른 사이트에서 로그인·로그아웃 요청을 위조하지 못하도록 폼과 세션의 값을 비교하는 장치입니다.
Flask 기본 세션은 서버 메모리가 아닌 **서명한 쿠키**입니다. 사용자가 내용을 읽을 수 있으므로 비밀번호나 비밀키는 넣지 않습니다.
서명은 변조를 막고 유효시간은 1시간입니다. 로그아웃은 현재 브라우저의 쿠키를 지우며, 이미 복제된 쿠키를 서버에서 개별 폐기하는 기능은 없습니다.

## 4. 글과 디자인 바꾸기

- 글: `app.py`의 `post()`에 있는 `post_title`, `post_body`를 수정합니다. 문자열의 `\n`은 줄바꿈입니다.
- 로그인 문구·구조: `templates/login.html`을 수정합니다.
- 색상: `static/style.css` 맨 위의 `--accent`, `--background` 등을 변경합니다.
- 카드·버튼·모바일 여백: 같은 CSS 파일에서 수정합니다.

Jinja는 사용자명과 글의 HTML 특수문자를 자동으로 이스케이프합니다. 사용자 입력에 `|safe`를 붙이지 마세요.

## 5. EC2 적용 방법 — 아직 실행하지 않은 안내

이 작업에서 AWS 설정 변경이나 새 리소스 생성은 하지 않았습니다. 추가 AWS 서비스는 필요하지 않습니다.
기존 EC2의 실행·스토리지·네트워크 사용 요금은 계속 적용될 수 있습니다.

먼저 변경 파일을 검토해 GitHub에 커밋·푸시하거나 비밀파일을 제외한 소스만 EC2로 전송해야 합니다.
현재 로컬 변경은 자동으로 GitHub나 EC2에 반영되지 않습니다.

EC2 Instance Connect에서 OS와 Python을 확인합니다.

```bash
cat /etc/os-release
python3 --version
```

Python 3.10 미만이면 OS에 맞는 Python 3.10 이상을 먼저 준비하세요. 기존 `/home/ec2-user/.venv`를 임의로 교체하지 않습니다.
**새 코드가 GitHub에 올라간 뒤**, 기존 `/home/ec2-user/my-web/`을 보존하고 새 경로에서 먼저 테스트합니다.
아래 `git clone`은 해당 경로가 이미 있으면 중단합니다. 기존 폴더를 삭제하거나 덮어쓰지 마세요.

```bash
git clone https://github.com/yoonjungwoo1009/aws-.git /home/ec2-user/my-web-new
cd /home/ec2-user/my-web-new
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
.venv/bin/python -m pip check
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python configure.py --output /home/ec2-user/my-web-new.env
set -a
source /home/ec2-user/my-web-new.env
set +a
.venv/bin/gunicorn --workers 2 --bind 127.0.0.1:8001 'app:create_app()'
```

`--output`은 설정 파일 생성 위치입니다. EC2에서는 체크아웃 밖에 보관합니다.
8001번은 기존 서버의 8000번과 충돌을 피하기 위한 내부 확인용이며 보안 그룹을 열 필요가 없습니다.
별도 Instance Connect 터미널에서 다음 명령으로 `200` 응답을 확인합니다.

```bash
curl --fail --silent --output /dev/null --write-out '%{http_code}\n' http://127.0.0.1:8001/
```

`--fail`은 HTTP 오류를 실패로 처리하고, `--output /dev/null`은 본문을 숨기며, `--write-out`은 상태코드만 출력합니다.
이 확인은 서버 시작 여부만 검증합니다. 로그인 동작은 테스트 및 브라우저에서 별도로 확인하세요.

제한된 HTTP 브라우저 테스트가 필요하면 새 서버를 `Ctrl+C`로 종료합니다.
기존 8000번 서버도 그 프로세스를 관리하던 방법으로 안전하게 종료한 뒤 실행합니다.

```bash
.venv/bin/gunicorn --workers 2 --bind 0.0.0.0:8000 'app:create_app()'
```

`0.0.0.0`은 모든 인터페이스에서 수신한다는 뜻입니다. 브라우저에는 EC2 퍼블릭 IP와 8000번 포트를 사용합니다.
HTTP 테스트 동안 보안 그룹의 8000번 접근은 **자신의 공인 IP/32**로 제한하고 일회성 테스트 비밀번호만 사용하세요.

인터넷 공개 전에는 기존 EC2에 HTTPS 역방향 프록시를 구성하고 `APP_HTTPS=true`로 전환해야 합니다.
Gunicorn을 내부 주소에 연결하고 외부 8000번 접근을 닫으며, 로그인 시도 제한과 systemd 자동 실행도 준비해야 합니다.
이 운영 구성은 다음 단계입니다. 실제 OS·도메인·인증서를 확인한 뒤 진행하며 ALB/RDS/NAT Gateway는 추가하지 않습니다.
