import re
from typing import Iterable

from openai import OpenAI
from slack_sdk import WebClient

from slackbot_lab.config import Settings
from slackbot_lab.memory import ConversationMemory


class SlackDualAgentBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.slack_client = WebClient(token=settings.slack_bot_token)
        self.openai_client = OpenAI(api_key=settings.openai_api_key)
        self.memory = ConversationMemory(db_path=settings.memory_db_path)

    def should_reply_in_thread(self, channel: str, thread_ts: str | None) -> bool:
        if not thread_ts:
            return False
        return self.memory.has_context(self.memory.build_key(channel, thread_ts))

    def handle_mention(self, channel: str, thread_ts: str, text: str) -> None:
        cleaned_text = self._normalize_text(text)
        memory_key = self.memory.build_key(channel, thread_ts)
        memory_context = self.memory.render_context(memory_key)

        try:
            self.memory.add(memory_key, "주성님", cleaned_text)

            if self._is_smalltalk(cleaned_text):
                reply = self._smalltalk_reply(cleaned_text, memory_context)
                self._post_message(channel, thread_ts, reply[:1500])
                self.memory.add(memory_key, "슬랙봇", reply[:1500])
                return

            first_speaker = self._route_speaker(cleaned_text)

            if first_speaker == "park":
                park_result = self._ask_park(cleaned_text, memory_context=memory_context)
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_result)
                self.memory.add(memory_key, "박과장", park_result)

                kim_result = self._ask_kim(
                    cleaned_text,
                    context=park_result,
                    memory_context=self.memory.render_context(memory_key),
                )
                if self._has_substance(kim_result):
                    self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_result)
                    self.memory.add(memory_key, "김대리", kim_result)
                return

            kim_result = self._ask_kim(cleaned_text, memory_context=memory_context)
            self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_result)
            self.memory.add(memory_key, "김대리", kim_result)

            park_result = self._ask_park(
                cleaned_text,
                context=kim_result,
                memory_context=self.memory.render_context(memory_key),
            )
            if self._has_substance(park_result):
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_result)
                self.memory.add(memory_key, "박과장", park_result)
        except Exception as exc:
            self._post_message(channel, thread_ts, f"오류가 발생했습니다: {exc}")

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

    def _smalltalk_reply(self, text: str, memory_context: str) -> str:
        context_block = f"\n이전 대화 맥락:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.responses.create(
            model=self.settings.smalltalk_model,
            input=f"""
너는 회사 업무 자동화를 돕는 슬랙봇이다.
주성님께 짧고 자연스럽고 공손한 한국어로 답한다.
같은 스레드 안에서 이미 오간 대화가 있으면 그 문맥만 이어받는다.{context_block}

주성님 메시지:
{text}
""",
        )
        return self._to_slack_text(response.output_text)

    def _ask_kim(
        self,
        text: str,
        context: str | None = None,
        memory_context: str | None = None,
    ) -> str:
        context_block = f"\n박과장 메모:\n{context}\n" if context else ""
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.responses.create(
            model=self.settings.research_model,
            tools=[{"type": "web_search"}],
            input=f"""
너는 김대리다.
박과장과는 상호 존대한다.
주성님의 요청에 대해 사실관계, 근거, 비교 포인트, 주의사항을 조사해서 정리한다.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드에서 오간 대화만 이어받는다.
한국어로 답한다.
차분하고 실무적인 말투를 유지한다.
마크다운 표는 쓰지 말고, 표가 필요하면 항목별 bullet list로 풀어서 쓴다.
제목은 짧게 쓰고 과한 마크다운 기호는 최소화한다.
시의성이 있는 정보는 필요하면 구체적인 날짜를 적는다.
의미 없는 인사나 연결 멘트는 쓰지 말고 바로 본론으로 답한다.{memory_block}{context_block}

주성님 요청:
{text}
""",
        )
        return self._to_slack_text(response.output_text)

    def _ask_park(
        self,
        text: str,
        context: str | None = None,
        memory_context: str | None = None,
    ) -> str:
        context_block = f"\n김대리 자료:\n{context}\n" if context else ""
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.responses.create(
            model=self.settings.manager_model,
            input=f"""
너는 박과장이다.
김대리와는 상호 존대한다.
주성님의 요청에 대해 실무적인 결론, 추천안, 다음 행동을 제시한다.
김대리를 칭찬만 하고 끝내지 말고 실제 판단을 분명히 말한다.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드에서 오간 대화만 이어받는다.
한국어로 답한다.
간결하지만 도움이 되게 쓴다.
마크다운 표는 쓰지 말고, 표가 필요하면 항목별 bullet list로 풀어서 쓴다.
제목은 짧게 쓰고 과한 마크다운 기호는 최소화한다.
의미 없는 인사나 연결 멘트는 쓰지 말고 바로 본론으로 답한다.
김대리 자료가 있으면 그것을 바탕으로 판단한다.{memory_block}{context_block}

주성님 요청:
{text}
""",
        )
        return self._to_slack_text(response.output_text)

    def _has_substance(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()
        weak_patterns = [
            "알겠습니다",
            "참고하겠습니다",
            "보완하겠습니다",
            "검토하겠습니다",
        ]
        return len(normalized) >= 30 and not any(normalized == pattern for pattern in weak_patterns)

    def _to_slack_text(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").strip()
        lines = normalized.split("\n")
        converted: list[str] = []
        in_table = False
        table_lines: list[str] = []

        for raw_line in lines:
            line = raw_line.rstrip()
            stripped = line.strip()

            if self._is_markdown_table_line(stripped):
                in_table = True
                table_lines.append(stripped)
                continue

            if in_table:
                converted.extend(self._convert_table_lines(table_lines))
                table_lines = []
                in_table = False

            if not stripped:
                if converted and converted[-1] != "":
                    converted.append("")
                continue

            line = re.sub(r"^#{1,6}\s*", "", stripped)
            line = re.sub(r"\*\*(.+?)\*\*", r"*\1*", line)
            line = re.sub(r"__(.+?)__", r"*\1*", line)
            line = re.sub(r"^\s*[-*]\s+", "• ", line)

            converted.append(line)

        if table_lines:
            converted.extend(self._convert_table_lines(table_lines))

        cleaned = "\n".join(converted)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _is_markdown_table_line(self, line: str) -> bool:
        return line.startswith("|") and line.endswith("|") and line.count("|") >= 2

    def _convert_table_lines(self, table_lines: list[str]) -> list[str]:
        if len(table_lines) < 2:
            return table_lines

        header_cells = self._parse_table_row(table_lines[0])
        body_rows = [
            self._parse_table_row(line)
            for line in table_lines[2:]
            if line.strip("|").strip("-: ").strip()
        ]

        converted = ["*비교 항목*"]
        for row in body_rows:
            pairs = [f"{header}: {value}" for header, value in zip(header_cells, row)]
            if pairs:
                converted.append(f"• {' / '.join(pairs)}")
        converted.append("")
        return converted

    def _parse_table_row(self, line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    def _post_message(self, channel: str, thread_ts: str, text: str) -> None:
        self.slack_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)

    def _post_chunks(self, channel: str, thread_ts: str, speaker: str, body: str) -> None:
        for part in self._chunk_text(f"{speaker}: {body}"):
            self._post_message(channel, thread_ts, part)

    def _chunk_text(self, text: str, size: int = 1800) -> Iterable[str]:
        return [text[index:index + size] for index in range(0, len(text), size)]
