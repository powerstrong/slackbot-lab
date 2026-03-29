import re
from typing import Iterable

from openai import OpenAI
from slack_sdk import WebClient

from slackbot_lab.config import Settings


class SlackDualAgentBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.slack_client = WebClient(token=settings.slack_bot_token)
        self.openai_client = OpenAI(api_key=settings.openai_api_key)

    def handle_mention(self, channel: str, thread_ts: str, text: str) -> None:
        cleaned_text = self._normalize_text(text)

        try:
            if self._is_smalltalk(cleaned_text):
                reply = self._smalltalk_reply(cleaned_text)
                self._post_message(channel, thread_ts, reply[:1500])
                return

            first_speaker = self._route_speaker(cleaned_text)

            if first_speaker == "park":
                self._post_message(
                    channel,
                    thread_ts,
                    "Park Manager: 먼저 방향과 판단을 정리하겠습니다. 이어서 Assistant Manager Kim이 필요한 근거를 보완하겠습니다.",
                )
                park_result = self._ask_park(cleaned_text)
                self._post_chunks(channel, thread_ts, "Park Manager", "Initial direction", park_result)

                self._post_message(
                    channel,
                    thread_ts,
                    "Assistant Manager Kim: 박과장님 의견에 맞춰 근거와 참고사항을 보완하겠습니다.",
                )
                kim_result = self._ask_kim(cleaned_text, context=park_result)
                self._post_chunks(channel, thread_ts, "Assistant Manager Kim", "Supporting research", kim_result)
                return

            self._post_message(
                channel,
                thread_ts,
                "Assistant Manager Kim: 먼저 자료와 근거를 확인하겠습니다. 이어서 Park Manager가 실행 관점에서 정리하겠습니다.",
            )
            kim_result = self._ask_kim(cleaned_text)
            self._post_chunks(channel, thread_ts, "Assistant Manager Kim", "Research", kim_result)

            self._post_message(
                channel,
                thread_ts,
                "Park Manager: 김대리 자료를 바탕으로 결론과 우선순위를 정리하겠습니다.",
            )
            park_result = self._ask_park(cleaned_text, context=kim_result)
            self._post_chunks(channel, thread_ts, "Park Manager", "Decision", park_result)
        except Exception as exc:
            self._post_message(channel, thread_ts, f"오류가 발생했습니다: {exc}")

    def post_ack(self, channel: str, text: str = "요청 접수했습니다. 스레드에서 순서대로 답변드리겠습니다.") -> None:
        self.slack_client.chat_postMessage(channel=channel, text=text)

    def _normalize_text(self, text: str) -> str:
        text = re.sub(r"<@[A-Z0-9]+>", "", text)
        return " ".join(text.split()).strip()

    def _is_smalltalk(self, text: str) -> bool:
        lowered = text.lower()
        keywords = ["안녕", "반가", "hello", "hi", "고마", "thanks", "이름", "뭐해"]
        return any(keyword in lowered for keyword in keywords) and len(lowered) < 30

    def _route_speaker(self, text: str) -> str:
        lowered = text.lower()
        park_keywords = [
            "어떻게",
            "해야",
            "할까",
            "결론",
            "추천",
            "우선순위",
            "판단",
            "실행",
            "전략",
            "정리",
            "plan",
            "strategy",
            "recommend",
        ]
        kim_keywords = [
            "찾아",
            "조사",
            "비교",
            "뉴스",
            "동향",
            "자료",
            "근거",
            "출처",
            "검색",
            "research",
            "compare",
            "source",
        ]

        park_score = sum(keyword in lowered for keyword in park_keywords)
        kim_score = sum(keyword in lowered for keyword in kim_keywords)
        return "park" if park_score > kim_score else "kim"

    def _smalltalk_reply(self, text: str) -> str:
        response = self.openai_client.responses.create(
            model=self.settings.smalltalk_model,
            input=f"""
You are a Slack bot for internal company workflow automation.
Reply briefly, naturally, and politely in Korean.

User message:
{text}
""",
        )
        return response.output_text

    def _ask_kim(self, text: str, context: str | None = None) -> str:
        context_block = f"\n박과장 메모:\n{context}\n" if context else ""
        response = self.openai_client.responses.create(
            model=self.settings.research_model,
            tools=[{"type": "web_search"}],
            input=f"""
You are Assistant Manager Kim.
You and Park Manager speak politely to each other.
Your role is to gather factual context, evidence, comparisons, and caveats for the user's request.
Write in Korean.
Keep the tone calm and practical.
If you cite time-sensitive facts, mention concrete dates when useful.
If Park Manager already left guidance, align your research to it.{context_block}

User request:
{text}
""",
        )
        return response.output_text

    def _ask_park(self, text: str, context: str | None = None) -> str:
        context_block = f"\n김대리 자료:\n{context}\n" if context else ""
        response = self.openai_client.responses.create(
            model=self.settings.manager_model,
            input=f"""
You are Park Manager.
You and Assistant Manager Kim speak politely to each other.
Your role is to provide a practical conclusion, recommendation, and next action.
Do not just praise Kim's work.
Give a real decision, tradeoff, and recommended next step.
Write in Korean.
Be concise and useful.
If Kim's research is present, use it to make a grounded recommendation.{context_block}

User request:
{text}
""",
        )
        return response.output_text

    def _post_message(self, channel: str, thread_ts: str, text: str) -> None:
        self.slack_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)

    def _post_chunks(self, channel: str, thread_ts: str, speaker: str, title: str, body: str) -> None:
        for part in self._chunk_text(f"{speaker} {title}:\n{body}"):
            self._post_message(channel, thread_ts, part)

    def _chunk_text(self, text: str, size: int = 1800) -> Iterable[str]:
        return [text[index:index + size] for index in range(0, len(text), size)]
