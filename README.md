# slackbot-lab

회사 업무를 자동화하기 위해 만든 슬랙봇입니다. OpenAI API를 이용해 웹 정보를 찾아보고, `박과장`과 `김대리`라는 두 인물이 서로 역할을 나눠 대화하듯 답변하면서 더 신뢰도 높은 결과를 슬랙 스레드로 전달하도록 만든 프로젝트입니다.

단순히 한 번 답하고 끝나는 봇이 아니라, 같은 스레드 안에서 이어지는 질문의 흐름을 따라가며 문맥을 유지하도록 구성했습니다. 그래서 추가 질문이나 정정 요청이 들어와도 앞선 대화를 바탕으로 더 자연스럽게 이어서 답할 수 있습니다.

## 주요 특징

- 슬랙 스레드 중심으로 답변
- OpenAI 기반 웹 검색과 정보 정리
- `김대리`와 `박과장`의 역할 분담형 응답
- 같은 스레드 안에서 이어지는 대화 문맥 유지
- 업무용 질문에 맞춘 간결하고 실무적인 답변

## 준비물

- OpenAI API 키
- Slack Bot Token
- Slack Signing Secret
- 외부에서 접근 가능한 HTTP 주소

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
uvicorn main:app --host 0.0.0.0 --port 3000
```

외부 공개 주소를 준비한 뒤 Slack 이벤트 주소를 아래처럼 연결하면 됩니다.

```text
https://your-domain/slack/events
```

## 안내

- 실제 API 키와 토큰은 `.env`에만 넣고 외부에 공개하지 않는 것을 권장합니다.
- 질문 내용이 최신 정보와 관련될수록 답변은 웹 검색 결과에 영향을 받을 수 있습니다.
- 같은 스레드 안에서 대화를 이어갈수록 더 자연스럽고 맥락 있는 답변을 받을 수 있습니다.
