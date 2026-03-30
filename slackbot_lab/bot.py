import json
import re
from typing import Iterable

from slack_sdk import WebClient

from slackbot_lab.config import Settings
from slackbot_lab.memory import ConversationMemory
from slackbot_lab.openai_client import OpenAIResponsesClient


USER_NAME = "주성님"
KIM_NAME = "김대리"
PARK_NAME = "박과장"
KIM_LABEL = ":male-technologist: 김대리"
PARK_LABEL = ":male-office-worker: 박과장"


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
            self.memory.add(memory_key, USER_NAME, cleaned_text)

            if self._is_smalltalk(cleaned_text):
                reply = self._smalltalk_reply(cleaned_text, memory_context)
                self._post_message(channel, thread_ts, reply[:1500])
                self.memory.add(memory_key, PARK_NAME, reply[:1500])
                return

            plan = self._plan_conversation(cleaned_text, memory_context)
            if plan.get("need_clarification"):
                question = self._trim_response(plan.get("clarification_question", "확인이 필요한 내용이 있습니다. 한 번만 더 알려주시겠습니까?"))
                self._post_chunks(channel, thread_ts, PARK_LABEL, question)
                self.memory.add(memory_key, PARK_NAME, question)
                return

            lead = plan.get("lead", "park")
            complexity = plan.get("complexity", "simple")

            kim_turns: list[str] = []
            park_turns: list[str] = []

            if complexity == "simple":
                if lead == "kim":
                    kim_answer = self._ask_persona(
                        persona="kim",
                        phase="answer",
                        user_request=cleaned_text,
                        memory_context=memory_context,
                    )
                    kim_answer = self._trim_response(kim_answer)
                    if self._has_meaningful_content(kim_answer):
                        self._post_chunks(channel, thread_ts, KIM_LABEL, kim_answer)
                        self.memory.add(memory_key, KIM_NAME, kim_answer)
                        kim_turns.append(kim_answer)

                    park_final = self._ask_persona(
                        persona="park",
                        phase="final",
                        user_request=cleaned_text,
                        memory_context=self.memory.render_context(memory_key),
                        partner_messages=kim_turns,
                    )
                    park_final = self._trim_response(park_final)
                    if self._has_meaningful_content(park_final) and not self._is_redundant(park_final, kim_turns):
                        self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                        self.memory.add(memory_key, PARK_NAME, park_final)
                    return

                park_final = self._ask_persona(
                    persona="park",
                    phase="final",
                    user_request=cleaned_text,
                    memory_context=memory_context,
                )
                park_final = self._trim_response(park_final)
                self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                self.memory.add(memory_key, PARK_NAME, park_final)
                return

            if lead == "park":
                park_opening = self._ask_persona(
                    persona="park",
                    phase="opening",
                    user_request=cleaned_text,
                    memory_context=memory_context,
                )
                park_opening = self._trim_response(park_opening)
                if self._has_meaningful_content(park_opening):
                    self._post_chunks(channel, thread_ts, PARK_LABEL, park_opening)
                    self.memory.add(memory_key, PARK_NAME, park_opening)
                    park_turns.append(park_opening)

                kim_reply = self._ask_persona(
                    persona="kim",
                    phase="response",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=park_turns,
                )
                kim_reply = self._trim_response(kim_reply)
                if self._has_meaningful_content(kim_reply) and not self._is_redundant(kim_reply, park_turns):
                    self._post_chunks(channel, thread_ts, KIM_LABEL, kim_reply)
                    self.memory.add(memory_key, KIM_NAME, kim_reply)
                    kim_turns.append(kim_reply)

                park_final = self._ask_persona(
                    persona="park",
                    phase="final",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=kim_turns or park_turns,
                )
                park_final = self._trim_response(park_final)
                if self._has_meaningful_content(park_final) and not self._is_redundant(park_final, park_turns):
                    self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                    self.memory.add(memory_key, PARK_NAME, park_final)
                return

            kim_opening = self._ask_persona(
                persona="kim",
                phase="opening",
                user_request=cleaned_text,
                memory_context=memory_context,
            )
            kim_opening = self._trim_response(kim_opening)
            if self._has_meaningful_content(kim_opening):
                self._post_chunks(channel, thread_ts, KIM_LABEL, kim_opening)
                self.memory.add(memory_key, KIM_NAME, kim_opening)
                kim_turns.append(kim_opening)

            park_final = self._ask_persona(
                persona="park",
                phase="final",
                user_request=cleaned_text,
                memory_context=self.memory.render_context(memory_key),
                partner_messages=kim_turns,
            )
            park_final = self._trim_response(park_final)
            if self._has_meaningful_content(park_final) and not self._is_redundant(park_final, kim_turns):
                self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                self.memory.add(memory_key, PARK_NAME, park_final)
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
        context_block = f"\n같은 스레드의 이전 대화\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.smalltalk_model,
            input_text=f"""
당신은 회사 업무를 돕는 슬랙봇입니다.
{USER_NAME}께 자연스럽고 짧게 답하세요.
같은 스레드의 맥락이 있으면 이어받되, 쓸데없이 길게 말하지 마세요.{context_block}

사용자 메시지:
{text}
""",
        )
        return self._to_slack_text(response)

    def _plan_conversation(self, user_request: str, memory_context: str) -> dict:
        context_block = f"\n같은 스레드의 이전 대화\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
당신은 슬랙 업무 에이전트의 진행 설계자입니다.
아래 요청을 보고 JSON만 출력하세요.

판단 기준:
- 간단한 요청이면 complexity는 simple로 두고, 말 수를 최소화합니다.
- 복잡한 요청, 조사/판단이 모두 필요한 요청이면 complexity는 collaborative로 둡니다.
- 정보가 부족해 답을 밀어붙이면 위험하면 need_clarification을 true로 두고, 질문은 한 번만 합니다.
- 간단한 업무 판단/작성/정리 요청은 park가 직접 마무리하는 쪽을 우선합니다.
- 조사나 최신 정보 확인이 핵심이면 kim이 먼저 말할 수 있습니다.

출력 형식:
{{
  "complexity": "simple" 또는 "collaborative",
  "lead": "kim" 또는 "park",
  "need_clarification": true 또는 false,
  "clarification_question": "사용자에게 꼭 필요한 확인 질문 1개, 없으면 빈 문자열"
}}
{context_block}

사용자 요청:
{user_request}
""",
        )

        default = {
            "complexity": "simple",
            "lead": "park",
            "need_clarification": False,
            "clarification_question": "",
        }

        try:
            start = response.find("{")
            end = response.rfind("}")
            if start == -1 or end == -1:
                return default
            parsed = json.loads(response[start:end + 1])
            complexity = parsed.get("complexity", "simple")
            lead = parsed.get("lead", "park")
            need_clarification = bool(parsed.get("need_clarification", False))
            clarification_question = str(parsed.get("clarification_question", "")).strip()
            if complexity not in {"simple", "collaborative"}:
                complexity = "simple"
            if lead not in {"kim", "park"}:
                lead = "park"
            if not need_clarification:
                clarification_question = ""
            return {
                "complexity": complexity,
                "lead": lead,
                "need_clarification": need_clarification,
                "clarification_question": clarification_question,
            }
        except Exception:
            return default

    def _ask_persona(
        self,
        persona: str,
        phase: str,
        user_request: str,
        memory_context: str,
        partner_messages: list[str] | None = None,
    ) -> str:
        partner_messages = partner_messages or []
        context_block = f"\n같은 스레드의 이전 대화\n{memory_context}\n" if memory_context else ""
        partner_block = ""
        if partner_messages:
            joined = "\n\n".join(partner_messages)
            partner_block = f"\n상대방의 직전 메시지 또는 참고 내용:\n{joined}\n"

        if persona == "kim":
            instructions = f"""
당신은 {KIM_NAME}입니다.
{PARK_NAME}과 상호 존대합니다.
역할은 사실 확인, 웹 검색, 비교, 근거 정리입니다.
최신 정보가 필요하면 웹 검색을 사용하세요.
말투는 자연스럽고 차분하게 유지하세요.
"알겠습니다", "참고하겠습니다", "보완하겠습니다" 같은 빈 연결 멘트로 시작하지 마세요.
상대가 이미 말한 내용을 길게 반복하지 마세요.
질문이 없으면 바로 본론으로 들어가세요.
"""
            tools = [{"type": "web_search"}]
        else:
            instructions = f"""
당신은 {PARK_NAME}입니다.
{KIM_NAME}과 상호 존대합니다.
역할은 판단, 우선순위 정리, 추천안, 최종 결론 제시입니다.
김대리가 정리한 근거가 있으면 그 위에서 판단하세요.
말투는 자연스럽고 단정하게 유지하세요.
쓸데없는 회의 진행 멘트나 연결 멘트는 금지합니다.
간단한 요청은 짧게 끝내고, 복잡한 요청만 필요한 만큼만 정리하세요.
최종 답변에서는 결론이 분명해야 합니다.
"""
            tools = None

        phase_instruction = {
            "opening": "첫 답변입니다. 필요한 핵심만 말하고, 상대에게 할 일을 지시하는 문장은 쓰지 마세요.",
            "response": "상대의 내용에 실질적으로 보탤 것이 있을 때만 답하세요. 중복 설명은 피하세요.",
            "answer": "단독 또는 짧은 보조 답변입니다. 본론만 간결하게 답하세요.",
            "final": f"마무리 답변입니다. {USER_NAME}이 바로 쓸 수 있는 결론, 권장 조치, 주의사항만 필요한 만큼 정리하세요.",
        }[phase]

        response = self.openai_client.create(
            model=self.settings.research_model if persona == "kim" else self.settings.manager_model,
            tools=tools,
            input_text=f"""
{instructions}
다른 채널이나 다른 스레드 기억은 쓰지 말고, 지금 스레드의 대화만 이어받으세요.
마크다운 표는 쓰지 말고, 필요하면 bullet list로 쓰세요.
말을 억지로 길게 늘이지 마세요.
{phase_instruction}
{context_block}{partner_block}

{USER_NAME} 요청:
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

        converted = ["비교 항목"]
        for row in body_rows:
            pairs = [f"{header}: {value}" for header, value in zip(header_cells, row)]
            if pairs:
                converted.append(f"• {' / '.join(pairs)}")
        converted.append("")
        return converted

    def _parse_table_row(self, line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    def _trim_response(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"^(알겠습니다|참고하겠습니다|보완하겠습니다|확인했습니다)[.!]?\s*", "", cleaned)
        cleaned = re.sub(r"^(좋습니다|네)[.!]?\s*", "", cleaned)
        return cleaned.strip()

    def _has_meaningful_content(self, text: str) -> bool:
        normalized = re.sub(r"\s+", " ", text).strip()
        return len(normalized) >= 12

    def _is_redundant(self, text: str, previous_messages: list[str]) -> bool:
        candidate = self._dedupe_key(text)
        if not candidate:
            return True
        for previous in previous_messages:
            other = self._dedupe_key(previous)
            if not other:
                continue
            if candidate == other:
                return True
            if candidate in other or other in candidate:
                return True
        return False

    def _dedupe_key(self, text: str) -> str:
        normalized = re.sub(r"\s+", " ", text).strip().lower()
        normalized = re.sub(r"[^0-9a-z가-힣 ]", "", normalized)
        return normalized[:300]

    def _post_message(self, channel: str, thread_ts: str, text: str) -> None:
        self.slack_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=text)

    def _post_chunks(self, channel: str, thread_ts: str, speaker: str, body: str) -> None:
        for part in self._chunk_text(f"{speaker}: {body}"):
            self._post_message(channel, thread_ts, part)

    def _chunk_text(self, text: str, size: int = 1800) -> Iterable[str]:
        return [text[index:index + size] for index in range(0, len(text), size)]
