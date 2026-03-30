# slackbot-lab

회사 업무를 자동화하기 위해 만든 슬랙봇입니다. OpenAI API를 이용해 웹 정보를 찾아보고, `김대리`와 `박과장`이 역할을 나눠 대화하듯 답변하며, 마지막에는 `박과장`이 명확한 최종안을 정리해 슬랙 스레드에 전달하도록 만든 프로젝트입니다.

같은 스레드 안에서 이어지는 질문은 이전 맥락을 반영해 답변합니다. 그래서 후속 질문, 정정 요청, 추가 확인이 이어져도 더 자연스럽게 대화를 이어갈 수 있습니다.

## 주요 특징

- 슬랙 스레드 중심 응답
- OpenAI 기반 웹 검색 및 정보 정리
- `김대리`와 `박과장`의 역할 분담형 답변
- 같은 스레드 안에서 문맥 유지
- 업무용 질문에 맞춘 간결하고 실무적인 결과 정리

## 준비물

- OpenAI API 키
- Slack Bot Token
- Slack Signing Secret
- 외부에서 접근 가능한 HTTP 주소

## 포트

기본 포트는 `3002`입니다.

`3000`은 다른 개발 서버와 자주 겹치고, `3001`도 함께 쓰는 경우가 많아서 이 프로젝트는 기본값을 `3002`로 두었습니다. 특별한 이유가 없으면 그대로 사용하면 됩니다.

## 실행 방법

먼저 필요한 패키지를 설치합니다.

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

Windows PowerShell에서는 아래처럼 실행하면 됩니다.

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

그 다음 `.env.example`를 참고해서 `.env` 파일을 만들고 필요한 값을 채웁니다.

서버는 아래 명령으로 실행합니다.

```bash
python main.py
```

외부 공개 주소를 준비한 뒤 Slack 이벤트 주소를 아래처럼 연결하면 됩니다.

```text
https://your-domain/slack/events
```

## 안내

- 실제 API 키와 토큰은 `.env`에만 넣고 외부에 공개하지 않는 것을 권장합니다.
- 최신 정보가 필요한 질문은 웹 검색 결과에 따라 답변이 달라질 수 있습니다.
- 같은 스레드 안에서 대화를 이어갈수록 더 자연스럽고 맥락 있는 답변을 받을 수 있습니다.
