# slackbot-lab

회사 업무를 자동화하기 위해 만든 슬랙봇이다. OpenAI API를 이용해 웹을 찾아주고, 2개의 자아처럼 동작하는 `박과장`과 `김대리`가 서로 역할을 나눠 대화하며, 신뢰도 높은 답변을 슬랙 스레드로 제공하기 위해 만든 프로그램이다.

지금 구조는 두 가지 실행 방식을 지원한다.

- `http`: FastAPI로 Slack Events API를 받고, 필요하면 `ngrok` 같은 터널을 붙여 테스트한다.
- `socket`: Slack Socket Mode로 동작하며 공인 URL이 필요 없다. PC를 껐다 켜거나 Termux에서 실행할 때 더 안정적이다.

## 왜 ngrok 주소가 문제인가

무료 `ngrok` HTTP 주소는 세션이 바뀔 때마다 바뀔 수 있다. 그래서 PC를 재부팅하거나 `ngrok`를 다시 띄우면 Slack Event Subscription URL도 다시 바꿔야 한다.

가장 현실적인 해결책은 아래 셋 중 하나다.

1. Slack Socket Mode로 전환한다.
2. `ngrok` 유료 고정 도메인이나 다른 고정 터널 서비스를 쓴다.
3. 항상 켜져 있는 서버나 VPS에 배포한다.

이 프로젝트는 1번을 바로 쓸 수 있게 구조를 바꿔두었다. Termux에서 돌릴 계획이라면 `socket` 모드가 가장 잘 맞는다.

## 동작 방식

- 사용자가 슬랙에서 봇을 멘션한다.
- 질문 유형을 보고 `박과장` 또는 `김대리` 중 더 적절한 쪽이 먼저 답한다.
- `김대리`는 자료 조사, 비교, 근거, 웹 검색 쪽을 담당한다.
- `박과장`은 실무 판단, 추천, 우선순위, 다음 액션을 담당한다.
- 두 사람은 서로 존댓말로 대화한다.
- 최종 결과는 슬랙 스레드에 순서대로 올라간다.

## 파일 구조

- `main.py`: 실행 진입점
- `slackbot_lab/config.py`: 환경변수와 실행 모드 설정
- `slackbot_lab/bot.py`: 박과장/김대리 응답 로직
- `slackbot_lab/http_transport.py`: Slack Events API용 FastAPI 서버
- `slackbot_lab/socket_transport.py`: Slack Socket Mode 실행기

## 설치

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell에서는:

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

## 환경변수

`.env.example`를 참고해서 `.env`를 만든다.

HTTP 모드에서 필요한 값:

- `OPENAI_API_KEY`
- `SLACK_BOT_TOKEN`
- `SLACK_SIGNING_SECRET`
- `SLACK_TRANSPORT=http`

Socket Mode에서 필요한 값:

- `OPENAI_API_KEY`
- `SLACK_BOT_TOKEN`
- `SLACK_APP_TOKEN`
- `SLACK_TRANSPORT=socket`

공통 선택값:

- `HOST`
- `PORT`
- `OPENAI_RESEARCH_MODEL`
- `OPENAI_MANAGER_MODEL`
- `OPENAI_SMALLTALK_MODEL`

## 실행 방법

### 1. HTTP 모드

```bash
uvicorn main:app --host 0.0.0.0 --port 3000
```

그 다음 `ngrok http 3000` 등으로 외부 URL을 만들고 Slack Event Subscription URL을 다음처럼 설정한다.

```text
https://your-domain/slack/events
```

### 2. Socket Mode

```bash
python main.py
```

`.env`에서 `SLACK_TRANSPORT=socket`으로 두면 Socket Mode로 실행된다. 이 모드에서는 외부 공개 URL이 필요 없다.

## Termux 운영 메모

Termux에서 장기 운영하려면 `socket` 모드를 권장한다.

- 휴대폰 재부팅 후 재실행이 필요하므로 `termux-wake-lock`, `tmux`, `termux-services` 등을 같이 고려하면 좋다.
- 네트워크가 자주 바뀌어도 Socket Mode는 공인 URL 고정 문제를 피할 수 있다.
- 배터리 최적화 예외 설정이 필요할 수 있다.

## Slack 설정 팁

- HTTP 모드: Event Subscriptions를 켜고 Request URL을 설정한다.
- Socket Mode: 앱 설정에서 Socket Mode를 켜고 App Token을 발급받는다.
- 봇이 멘션을 받으려면 `app_mentions:read`, `chat:write` 권한이 필요하다.

## 주의

- `.env`에는 실제 토큰과 키가 들어 있으므로 Git에 올리지 않는다.
- 시간 민감한 질문은 OpenAI 웹 검색 결과에 따라 답이 달라질 수 있다.
- 모바일 장기 운영은 편하지만, 안정성만 보면 작은 VPS나 항상 켜진 서버가 더 낫다.
