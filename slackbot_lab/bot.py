import json
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

            plan = self._plan_conversation(cleaned_text, memory_context)
            lead = plan.get("lead", "kim")
            rounds = max(1, min(2, int(plan.get("rounds", 1))))

            kim_turns: list[str] = []
            park_turns: list[str] = []

            if lead == "park":
                park_opening = self._ask_persona(
                    persona="park",
                    phase="opening",
                    user_request=cleaned_text,
                    memory_context=memory_context,
                )
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_opening)
                self.memory.add(memory_key, "박과장", park_opening)
                park_turns.append(park_opening)

                if rounds >= 2:
                    kim_reply = self._ask_persona(
                        persona="kim",
                        phase="response",
                        user_request=cleaned_text,
                        memory_context=self.memory.render_context(memory_key),
                        partner_messages=park_turns,
                    )
                    if self._has_meaningful_content(kim_reply):
                        self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_reply)
                        self.memory.add(memory_key, "김대리", kim_reply)
                        kim_turns.append(kim_reply)

                park_final = self._ask_persona(
                    persona="park",
                    phase="final",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=kim_turns or park_turns,
                )
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_final)
                self.memory.add(memory_key, "박과장", park_final)
                return

            kim_opening = self._ask_persona(
                persona="kim",
                phase="opening",
                user_request=cleaned_text,
                memory_context=memory_context,
            )
            self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_opening)
            self.memory.add(memory_key, "김대리", kim_opening)
            kim_turns.append(kim_opening)

            park_reply = self._ask_persona(
                persona="park",
                phase="response",
                user_request=cleaned_text,
                memory_context=self.memory.render_context(memory_key),
                partner_messages=kim_turns,
            )
            if self._has_meaningful_content(park_reply):
                self._post_chunks(channel, thread_ts, ":male-office-worker: 박과장", park_reply)
                self.memory.add(memory_key, "박과장", park_reply)
                park_turns.append(park_reply)

            if rounds >= 2:
                kim_reply = self._ask_persona(
                    persona="kim",
                    phase="response",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=park_turns or kim_turns,
                )
                if self._has_meaningful_content(kim_reply):
                    self._post_chunks(channel, thread_ts, ":male-technologist: 김대리", kim_reply)
                    self.memory.add(memory_key, "김대리", kim_reply)
                    kim_turns.append(kim_reply)

            park_final = self._ask_persona(
                persona="park",
                phase="final",
                user_request=cleaned_text,
                memory_context=self.memory.render_context(memory_key),
                partner_messages=kim_turns or park_turns,
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

    def _plan_conversation(self, user_request: str, memory_context: str) -> dict:
        context_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
너는 슬랙 업무 에이전트의 대화 설계자다.
아래 사용자 요청을 보고 누가 먼저 답하면 좋은지, 몇 번 정도 주고받아야 하는지 판단한다.
김대리는 조사와 근거 정리에 강하고, 박과장은 판단과 최종 정리에 강하다.
간단한 요청이면 왕복을 최소화하고, 복잡한 요청이면 한 번 더 주고받게 한다.
다른 설명 없이 JSON만 출력한다.

출력 형식:
{{"lead":"kim" 또는 "park","rounds":1 또는 2}}
{context_block}

주성님 요청:
{user_request}
""",
        )

        try:
            start = response.find("{")
            end = response.rfind("}")
            if start != -1 and end != -1:
                parsed = json.loads(response[start:end + 1])
                lead = parsed.get("lead", "kim")
                rounds = parsed.get("rounds", 1)
                if lead in {"kim", "park"} and rounds in {1, 2}:
                    return {"lead": lead, "rounds": rounds}
        except Exception:
            pass

        return {"lead": "kim", "rounds": 1}

    def _ask_persona(
        self,
        persona: str,
        phase: str,
        user_request: str,
        memory_context: str,
        partner_messages: list[str] | None = None,
    ) -> str:
        partner_messages = partner_messages or []
        context_block = f"\n같은 스레드의 이전 대화:\n{memory_context}\n" if memory_context else ""
        partner_block = ""
        if partner_messages:
            joined = "\n\n".join(partner_messages)
            partner_block = f"\n상대의 직전 메시지 또는 참고 내용:\n{joined}\n"

        if persona == "kim":
            instructions = """
너는 김대리다.
박과장과는 상호 존대한다.
역할은 사실관계, 최신 근거, 비교 포인트, 주의사항을 조사해서 정리하는 것이다.
필요하면 웹 검색을 사용한다.
말투는 차분하고 사람처럼 자연스럽게 한다.
정해진 문구를 반복하지 말고, 상황에 맞게 실제로 할 말을 한다.
학습된 챗봇처럼 틀에 박힌 표현은 피한다.
시간 정보는 근거가 있을 때만 구체적인 날짜로 말한다.
"""
            tools = [{"type": "web_search"}]
        else:
            instructions = """
너는 박과장이다.
김대리와는 상호 존대한다.
역할은 실무 판단, 우선순위, 추천안, 최종 결론을 명확하게 정리하는 것이다.
말투는 자연스럽고 단정하게 한다.
정해진 문구를 반복하지 말고, 상황에 맞게 실제로 할 말을 한다.
학습된 챗봇처럼 틀에 박힌 표현은 피한다.
김대리의 근거나 스레드 맥락이 있으면 그 위에서 판단한다.
"""
            tools = None

        phase_instruction = {
            "opening": "첫 답변이다. 바로 본론으로 들어가고, 필요한 관점이나 핵심 포인트를 제시한다.",
            "response": "상대가 말한 내용을 받아 자연스럽게 이어서 보완하거나 반박하거나 уточ명한다. 억지로 길게 쓰지 말고 필요한 만큼만 말한다.",
            "final": "반드시 대화를 마무리하는 최종 답변이다. 결론을 분명하게 말하고, 필요하면 근거와 권장 조치를 함께 정리한다.",
        }[phase]

        response = self.openai_client.create(
            model=self.settings.research_model if persona == "kim" else self.settings.manager_model,
            tools=tools,
            input_text=f"""
{instructions}
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드에서 오간 대화만 이어받는다.
한국어로 답한다.
마크다운 표는 쓰지 말고, 표가 필요하면 bullet list로 풀어서 쓴다.
과한 형식 문구나 인사말은 넣지 말고, 사람처럼 자연스럽게 바로 답한다.
{phase_instruction}
{context_block}{partner_block}

주성님 요청:
{user_request}
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

    def _has_meaningful_content(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()
        return len(normalized) >= 20

    def _post_message(self, channel: str, thread_ts: str, text: str) -> None:
        self.slack_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)

    def _post_chunks(self, channel: str, thread_ts: str, speaker: str, body: str) -> None:
        for part in self._chunk_text(f"{speaker}: {body}"):
            self._post_message(channel, thread_ts, part)

    def _chunk_text(self, text: str, size: int = 1800) -> Iterable[str]:
        return [text[index:index + size] for index in range(0, len(text), size)]
