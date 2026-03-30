import re
from typing import Iterable

from slack_sdk import WebClient

from slackbot_lab.config import Settings
from slackbot_lab.memory import ConversationMemory
from slackbot_lab.openai_client import OpenAIResponsesClient


class SlackDualAgentBot:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.slack_client = WebClient(token=settings.slack_bot_token)
        self.openai_client = OpenAIResponsesClient(api_key=settings.openai_api_key)
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

            complexity = self._classify_complexity(cleaned_text)

            if self._route_speaker(cleaned_text) == "park":
                park_opening = self._ask_park_opening(cleaned_text, memory_context=memory_context)
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_opening)
                self.memory.add(memory_key, "박과장", park_opening)

                if complexity == "simple":
                    park_final = self._ask_park_final(
                        cleaned_text,
                        park_opening=park_opening,
                        kim_review="",
                        memory_context=self.memory.render_context(memory_key),
                    )
                    self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_final)
                    self.memory.add(memory_key, "박과장", park_final)
                    return

                kim_review = self._ask_kim_review(
                    cleaned_text,
                    park_opening,
                    memory_context=self.memory.render_context(memory_key),
                )
                if self._has_substance(kim_review):
                    self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_review)
                    self.memory.add(memory_key, "김대리", kim_review)

                park_final = self._ask_park_final(
                    cleaned_text,
                    park_opening=park_opening,
                    kim_review=kim_review,
                    memory_context=self.memory.render_context(memory_key),
                )
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_final)
                self.memory.add(memory_key, "박과장", park_final)
                return

            kim_research = self._ask_kim_research(cleaned_text, memory_context=memory_context)
            self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_research)
            self.memory.add(memory_key, "김대리", kim_research)

            park_review = self._ask_park_review(
                cleaned_text,
                kim_research,
                memory_context=self.memory.render_context(memory_key),
            )
            self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_review)
            self.memory.add(memory_key, "박과장", park_review)

            kim_reply = ""
            if complexity == "complex":
                kim_reply = self._ask_kim_reply(
                    cleaned_text,
                    kim_research=kim_research,
                    park_review=park_review,
                    memory_context=self.memory.render_context(memory_key),
                )
                if self._has_substance(kim_reply):
                    self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_reply)
                    self.memory.add(memory_key, "김대리", kim_reply)

            park_final = self._ask_park_final(
                cleaned_text,
                park_opening=park_review,
                kim_review=kim_reply,
                memory_context=self.memory.render_context(memory_key),
            )
            self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_final)
            self.memory.add(memory_key, "박과장", park_final)
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

    def _classify_complexity(self, text: str) -> str:
        lowered = text.lower()
        complex_signals = [
            "비교",
            "전략",
            "정리",
            "분석",
            "추천",
            "근거",
            "리스크",
            "장단점",
            "검토",
            "여러",
            "복수",
            "비용",
            "일정",
            "뉴스",
            "동향",
            "plan",
            "strategy",
            "compare",
            "analysis",
        ]
        score = sum(signal in lowered for signal in complex_signals)
        if len(text) > 80 or score >= 2:
            return "complex"
        return "simple"

    def _smalltalk_reply(self, text: str, memory_context: str) -> str:
        context_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.smalltalk_model,
            input_text=f"""
너는 회사 업무 자동화를 돕는 슬랙봇이다.
주성님께 짧고 자연스럽고 공손한 한국어로 답한다.
같은 스레드 안에서 이미 오간 대화가 있으면 그 문맥만 이어받는다.{context_block}

주성님 메시지:
{text}
""",
        )
        return self._to_slack_text(response)

    def _ask_kim_research(self, text: str, memory_context: str | None = None) -> str:
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.research_model,
            tools=[{"type": "web_search"}],
            input_text=f"""
너는 김대리다.
박과장과는 상호 존대한다.
주성님의 요청에 대해 사실관계, 최신 근거, 비교 포인트, 주의사항을 조사해서 정리한다.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드에서 오간 대화만 이어받는다.
한국어로 답한다.
차분하고 실무적인 말투를 유지한다.
마크다운 표는 쓰지 말고, 표가 필요하면 bullet list로 풀어서 쓴다.
시의성이 있는 정보는 가능하면 구체적인 날짜를 적는다.
바로 본론으로 답한다.{memory_block}

주성님 요청:
{text}
""",
        )
        return self._to_slack_text(response)

    def _ask_park_review(self, text: str, kim_research: str, memory_context: str | None = None) -> str:
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
너는 박과장이다.
김대리와는 상호 존대한다.
방금 받은 김대리 자료를 검토해서 실무 판단, 빠진 점, 우선순위를 짚는다.
간단한 작업이면 짧고 분명하게 말하고, 복잡한 작업이면 김대리가 더 보완해야 할 지점을 남긴다.
시간 정보는 김대리 자료에 있는 최신 근거만 사용한다. 근거 없이 학습시점 표현을 쓰지 마라.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드 대화만 이어받는다.
한국어로 간결하게 답한다.
바로 본론으로 답한다.{memory_block}

주성님 요청:
{text}

김대리 자료:
{kim_research}
""",
        )
        return self._to_slack_text(response)

    def _ask_kim_reply(
        self,
        text: str,
        kim_research: str,
        park_review: str,
        memory_context: str | None = None,
    ) -> str:
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.research_model,
            tools=[{"type": "web_search"}],
            input_text=f"""
너는 김대리다.
박과장과는 상호 존대한다.
박과장 검토를 반영해 필요한 근거만 추가 보완한다.
새로운 정보, 날짜, 근거가 없으면 억지로 길게 쓰지 말고 핵심 보완만 짧게 쓴다.
시간 정보는 웹 검색이나 이미 주어진 근거를 바탕으로만 적는다.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드 대화만 이어받는다.
한국어로 답한다.
바로 본론으로 답한다.{memory_block}

주성님 요청:
{text}

기존 김대리 자료:
{kim_research}

박과장 검토:
{park_review}
""",
        )
        return self._to_slack_text(response)

    def _ask_park_opening(self, text: str, memory_context: str | None = None) -> str:
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
너는 박과장이다.
김대리와는 상호 존대한다.
먼저 실무 판단의 방향과 핵심 쟁점을 짚는다.
간단한 작업이면 짧게 방향만 말해도 된다.
복잡한 작업이면 김대리가 보완해야 할 근거나 확인 포인트를 남긴다.
시간 정보는 근거 없이 단정하지 말고, 학습시점 표현도 쓰지 마라.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드 대화만 이어받는다.
한국어로 답한다.
바로 본론으로 답한다.{memory_block}

주성님 요청:
{text}
""",
        )
        return self._to_slack_text(response)

    def _ask_kim_review(self, text: str, park_opening: str, memory_context: str | None = None) -> str:
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.research_model,
            tools=[{"type": "web_search"}],
            input_text=f"""
너는 김대리다.
박과장과는 상호 존대한다.
박과장이 짚은 쟁점에 맞춰 최신 근거와 보완사항만 정리한다.
시간 정보는 웹 검색이나 주어진 근거에 있는 것만 사용한다.
근거 없이 학습시점 표현은 쓰지 마라.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드 대화만 이어받는다.
한국어로 답한다.
바로 본론으로 답한다.{memory_block}

주성님 요청:
{text}

박과장 의견:
{park_opening}
""",
        )
        return self._to_slack_text(response)

    def _ask_park_final(
        self,
        text: str,
        park_opening: str,
        kim_review: str,
        memory_context: str | None = None,
    ) -> str:
        memory_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
너는 박과장이다.
김대리와는 상호 존대한다.
반드시 최종안을 명확하게 정리해서 끝낸다.
간단한 작업이면 짧아도 되지만 결론은 분명해야 한다.
복잡한 작업이면 아래 구조를 최대한 따른다.
최종안
결론: 한두 문장
근거: 핵심 근거 2~4개
권장 조치: 바로 해야 할 행동 1~3개
주의사항: 있으면 짧게

시간 정보는 김대리 자료나 스레드 내 최신 근거만 사용한다.
근거 없이 학습시점 표현을 쓰지 마라.
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드 대화만 이어받는다.
한국어로 간결하고 분명하게 쓴다.
바로 본론으로 답한다.{memory_block}

주성님 요청:
{text}

박과장 이전 의견:
{park_opening}

김대리 보완:
{kim_review}
""",
        )
        return self._to_slack_text(response)

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

    def _has_substance(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()
        weak_patterns = [
            "알겠습니다",
            "참고하겠습니다",
            "보완하겠습니다",
            "검토하겠습니다",
        ]
        return len(normalized) >= 30 and not any(normalized == pattern for pattern in weak_patterns)

    def _post_message(self, channel: str, thread_ts: str, text: str) -> None:
        self.slack_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)

    def _post_chunks(self, channel: str, thread_ts: str, speaker: str, body: str) -> None:
        for part in self._chunk_text(f"{speaker}: {body}"):
            self._post_message(channel, thread_ts, part)

    def _chunk_text(self, text: str, size: int = 1800) -> Iterable[str]:
        return [text[index:index + size] for index in range(0, len(text), size)]
