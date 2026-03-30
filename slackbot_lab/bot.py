import json
import re
from typing import Iterable

from slack_sdk import WebClient

from slackbot_lab.config import Settings
from slackbot_lab.memory import ConversationMemory
from slackbot_lab.openai_client import OpenAIResponsesClient


USER_NAME = "\uc8fc\uc131\ub2d8"
KIM_NAME = "\uae40\ub300\ub9ac"
PARK_NAME = "\ubc15\uacfc\uc7a5"
KIM_LABEL = ":male-technologist: \uae40\ub300\ub9ac"
PARK_LABEL = ":male-office-worker: \ubc15\uacfc\uc7a5"
DEFAULT_CLARIFICATION = "\ud655\uc778\uc774 \ud544\uc694\ud55c \ub0b4\uc6a9\uc774 \uc788\uc2b5\ub2c8\ub2e4. \ud55c \ubc88\ub9cc \ub354 \uc54c\ub824\uc8fc\uc2dc\uaca0\uc2b5\ub2c8\uae4c?"
ERROR_PREFIX = "\uc624\ub958\uac00 \ubc1c\uc0dd\ud588\uc2b5\ub2c8\ub2e4: "


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
                question = self._trim_response(plan.get("clarification_question", DEFAULT_CLARIFICATION))
                self._post_chunks(channel, thread_ts, PARK_LABEL, question)
                self.memory.add(memory_key, PARK_NAME, question)
                return

            mode = plan.get("mode", "solo_park")
            if self._wants_links_or_images(cleaned_text):
                mode = "kim_then_park"

            if mode == "solo_park":
                park_final = self._ask_park(
                    phase="final",
                    user_request=cleaned_text,
                    memory_context=memory_context,
                )
                park_final = self._trim_response(park_final)
                self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                self.memory.add(memory_key, PARK_NAME, park_final)
                return

            if mode == "park_then_kim_then_park":
                park_opening = self._ask_park(
                    phase="opening",
                    user_request=cleaned_text,
                    memory_context=memory_context,
                )
                park_opening = self._trim_response(park_opening)
                if self._has_meaningful_content(park_opening):
                    self._post_chunks(channel, thread_ts, PARK_LABEL, park_opening)
                    self.memory.add(memory_key, PARK_NAME, park_opening)

                kim_reply = self._ask_kim(
                    phase="response",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=[park_opening] if self._has_meaningful_content(park_opening) else None,
                )
                kim_reply = self._trim_response(kim_reply)
                if self._has_meaningful_content(kim_reply):
                    self._post_chunks(channel, thread_ts, KIM_LABEL, kim_reply)
                    self.memory.add(memory_key, KIM_NAME, kim_reply)

                park_final = self._ask_park(
                    phase="final",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=[kim_reply] if self._has_meaningful_content(kim_reply) else None,
                )
                park_final = self._trim_response(park_final)
                if self._has_meaningful_content(park_final) and not self._is_redundant(park_final, [kim_reply]):
                    self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                    self.memory.add(memory_key, PARK_NAME, park_final)
                return

            kim_answer = self._ask_kim(
                phase="answer",
                user_request=cleaned_text,
                memory_context=memory_context,
            )
            kim_answer = self._trim_response(kim_answer)
            if self._has_meaningful_content(kim_answer):
                self._post_chunks(channel, thread_ts, KIM_LABEL, kim_answer)
                self.memory.add(memory_key, KIM_NAME, kim_answer)

            review = self._review_kim_answer(
                user_request=cleaned_text,
                kim_answer=kim_answer,
                memory_context=self.memory.render_context(memory_key),
            )

            if review.get("action") == "revise":
                correction = self._trim_response(review.get("message", "\ud575\uc2ec \uc694\uccad\uc744 \ub2e4\uc2dc \ub9de\ucdb0\uc8fc\uc2ed\uc2dc\uc624."))
                self._post_chunks(channel, thread_ts, PARK_LABEL, correction)
                self.memory.add(memory_key, PARK_NAME, correction)

                kim_revision = self._ask_kim(
                    phase="revision",
                    user_request=cleaned_text,
                    memory_context=self.memory.render_context(memory_key),
                    partner_messages=[kim_answer, correction],
                )
                kim_revision = self._trim_response(kim_revision)
                if self._has_meaningful_content(kim_revision) and not self._is_redundant(kim_revision, [kim_answer]):
                    self._post_chunks(channel, thread_ts, KIM_LABEL, kim_revision)
                    self.memory.add(memory_key, KIM_NAME, kim_revision)
                    kim_answer = kim_revision

            park_final = self._ask_park(
                phase="final",
                user_request=cleaned_text,
                memory_context=self.memory.render_context(memory_key),
                partner_messages=[kim_answer] if self._has_meaningful_content(kim_answer) else None,
            )
            park_final = self._trim_response(park_final)
            if self._has_meaningful_content(park_final) and not self._is_redundant(park_final, [kim_answer]):
                self._post_chunks(channel, thread_ts, PARK_LABEL, park_final)
                self.memory.add(memory_key, PARK_NAME, park_final)
        except Exception as exc:
            self._post_message(channel, thread_ts, f"{ERROR_PREFIX}{exc}")

    def _normalize_text(self, text: str) -> str:
        text = re.sub(r"<@[A-Z0-9]+>", "", text)
        return " ".join(text.split()).strip()

    def _wants_links_or_images(self, text: str) -> bool:
        lowered = text.lower()
        keywords = [
            "\ub9c1\ud06c",
            "\uc0ac\uc9c4",
            "\uc774\ubbf8\uc9c0",
            "url",
            "\ubcf4\uc5ec\uc918",
            "\ucc3e\uc544\uc918",
        ]
        return any(keyword in lowered for keyword in keywords)

    def _is_smalltalk(self, text: str) -> bool:
        lowered = text.lower()
        keywords = ["\uc548\ub155", "\ubc18\uac00", "hello", "hi", "\uace0\ub9c8", "thanks", "\uc774\ub984", "\ubb50\ud574"]
        return any(keyword in lowered for keyword in keywords) and len(lowered) < 30

    def _smalltalk_reply(self, text: str, memory_context: str) -> str:
        context_block = f"\n\uac19\uc740 \uc2a4\ub808\ub4dc\uc758 \uc774\uc804 \ub300\ud654\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.smalltalk_model,
            input_text=f"""
\ub2f9\uc2e0\uc740 \ud68c\uc0ac \uc5c5\ubb34\ub97c \ub3d5\ub294 \uc2ac\ub799\ubd07\uc785\ub2c8\ub2e4.
{USER_NAME}\uaed8 \uc790\uc5f0\uc2a4\ub7fd\uace0 \uc9e7\uac8c \ub2f5\ud558\uc138\uc694.
\uac19\uc740 \uc2a4\ub808\ub4dc\uc758 \ub9e5\ub77d\uc774 \uc788\uc73c\uba74 \uc774\uc5b4\ubc1b\ub418, \uc4f8\ub370\uc5c6\uc774 \uae38\uac8c \ub9d0\ud558\uc9c0 \ub9c8\uc138\uc694.{context_block}

\uc0ac\uc6a9\uc790 \uba54\uc2dc\uc9c0:
{text}
""",
        )
        return self._to_slack_text(response)

    def _plan_conversation(self, user_request: str, memory_context: str) -> dict:
        context_block = f"\n\uac19\uc740 \uc2a4\ub808\ub4dc\uc758 \uc774\uc804 \ub300\ud654\n{memory_context}\n" if memory_context else ""
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
\ub2f9\uc2e0\uc740 \uc2ac\ub799 \uc5c5\ubb34 \uc9c4\ud589 \uc124\uacc4\uc790\uc785\ub2c8\ub2e4.
JSON\ub9cc \ucd9c\ub825\ud558\uc138\uc694.

\uae30\uc900:
- \uac04\ub2e8\ud55c \uc694\uccad\uc740 park\uac00 \ud63c\uc790 \uc9e7\uac8c \ub05d\ub0c5\ub2c8\ub2e4.
- \uc870\uc0ac, \ub9c1\ud06c, \ucd5c\uc2e0 \uc815\ubcf4, \ube44\uad50 \uc815\ub9ac\uac00 \ud544\uc694\ud558\uba74 kim_then_park\ub85c \ub461\ub2c8\ub2e4.
- \uba3c\uc800 \ubc15\uacfc\uc7a5\uc774 \ubc29\ud5a5\uc744 \uc7a1\uc544\uc57c \ud558\uba74 park_then_kim_then_park\ub85c \ub461\ub2c8\ub2e4.
- \uc815\ubcf4\uac00 \ubd80\uc871\ud558\uba74 need_clarification\uc744 true\ub85c \ub450\uace0 \uc9c8\ubb38\uc740 1\uac1c\ub9cc \ud569\ub2c8\ub2e4.

\ucd9c\ub825 \ud615\uc2dd:
{{
  "mode": "solo_park" \ub610\ub294 "kim_then_park" \ub610\ub294 "park_then_kim_then_park",
  "need_clarification": true \ub610\ub294 false,
  "clarification_question": "\uc5c6\uc73c\uba74 \ube48 \ubb38\uc790\uc5f4"
}}
{context_block}

\uc0ac\uc6a9\uc790 \uc694\uccad:
{user_request}
""",
        )

        default = {
            "mode": "solo_park",
            "need_clarification": False,
            "clarification_question": "",
        }

        try:
            start = response.find("{")
            end = response.rfind("}")
            if start == -1 or end == -1:
                return default
            parsed = json.loads(response[start:end + 1])
            mode = parsed.get("mode", "solo_park")
            need_clarification = bool(parsed.get("need_clarification", False))
            clarification_question = str(parsed.get("clarification_question", "")).strip()
            if mode not in {"solo_park", "kim_then_park", "park_then_kim_then_park"}:
                mode = "solo_park"
            if not need_clarification:
                clarification_question = ""
            return {
                "mode": mode,
                "need_clarification": need_clarification,
                "clarification_question": clarification_question,
            }
        except Exception:
            return default

    def _review_kim_answer(self, user_request: str, kim_answer: str, memory_context: str) -> dict:
        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
\ub2f9\uc2e0\uc740 {PARK_NAME}\uc785\ub2c8\ub2e4.
{KIM_NAME} \ub2f5\ubcc0\uc744 \uac80\ud1a0\ud558\uace0 JSON\ub9cc \ucd9c\ub825\ud558\uc138\uc694.
- \uc694\uccad\uc5d0 \ub9de\uace0, \ub9c1\ud06c/\uc0ac\uc9c4 \uc694\uccad\uc774 \uc788\uc73c\uba74 URL\uc774 \ub4e4\uc5b4\uac00 \uc788\uc73c\uba74 ok
- \ubc29\ud5a5\uc774 \ube57\ub098\uac14\uac70\ub098 \uc694\uccad\ud55c \ud575\uc2ec\uc774 \ube60\uc84c\uc73c\uba74 revise
- revise\uc77c \ub54c message\ub294 1~2\ubb38\uc7a5, \uc9e7\uace0 \uad6c\uccb4\uc801\uc774\uac8c

{{"action":"ok" \ub610\ub294 "revise","message":"..."}}

\uc0ac\uc6a9\uc790 \uc694\uccad:
{user_request}

{KIM_NAME} \ub2f5\ubcc0:
{kim_answer}

\uac19\uc740 \uc2a4\ub808\ub4dc \ub9e5\ub77d:
{memory_context}
""",
        )

        default = {"action": "ok", "message": ""}
        try:
            start = response.find("{")
            end = response.rfind("}")
            if start == -1 or end == -1:
                return default
            parsed = json.loads(response[start:end + 1])
            action = parsed.get("action", "ok")
            message = str(parsed.get("message", "")).strip()
            if action not in {"ok", "revise"}:
                action = "ok"
            return {"action": action, "message": message}
        except Exception:
            return default

    def _ask_kim(
        self,
        phase: str,
        user_request: str,
        memory_context: str,
        partner_messages: list[str] | None = None,
    ) -> str:
        partner_messages = partner_messages or []
        context_block = f"\n\uac19\uc740 \uc2a4\ub808\ub4dc \ub9e5\ub77d\n{memory_context}\n" if memory_context else ""
        partner_block = ""
        if partner_messages:
            partner_block = "\n\ucc38\uace0\ud560 \ub0b4\uc6a9:\n" + "\n\n".join(partner_messages) + "\n"

        phase_instruction = {
            "answer": "\uc8fc\uc131\ub2d8\uc774 \ubc14\ub85c \uc4f8 \uc218 \uc788\uac8c \ud575\uc2ec\ub9cc \uc815\ub9ac\ud558\uc138\uc694. 3~5\uc904 \uc815\ub3c4\ub85c \uc9e7\uac8c.",
            "response": "\ubc15\uacfc\uc7a5 \ubc29\ud5a5\uc5d0 \ub530\ub77c \uc790\ub8cc\ub098 \uadfc\uac70\ub9cc \ubcf4\ud0dc\uc138\uc694. 3~5\uc904 \uc774\ub0b4.",
            "revision": "\ubc15\uacfc\uc7a5 \uc694\uccad\uc744 \ubc18\uc601\ud574 \ubc29\ud5a5\uc744 \ubc14\ub85c\uc7a1\uc544 \ub2e4\uc2dc \uc815\ub9ac\ud558\uc138\uc694. \ud575\uc2ec \ubc14\ub85c \ub2f5\ud558\uace0, 3~5\uc904 \uc774\ub0b4.",
        }[phase]

        response = self.openai_client.create(
            model=self.settings.research_model,
            tools=[{"type": "web_search"}],
            input_text=f"""
\ub2f9\uc2e0\uc740 {KIM_NAME}\uc785\ub2c8\ub2e4.
{PARK_NAME}\uacfc \uc0c1\ud638 \uc874\ub300\ud569\ub2c8\ub2e4.
\uc5ed\ud560\uc740 \uc0ac\uc2e4 \ud655\uc778, \uadfc\uac70 \uc815\ub9ac, \ub9c1\ud06c \uc81c\uacf5\uc785\ub2c8\ub2e4.
\ub9c1\ud06c\ub098 \uc0ac\uc9c4 \uc694\uccad\uc774 \uc788\uc73c\uba74 \uc2e4\uc81c URL\uc744 \ud3ec\ud568\ud558\uc138\uc694.
\ube48 \uc5f0\uacb0 \uba58\ud2b8\ub294 \uae08\uc9c0\ud558\uace0 \ubc14\ub85c \ubcf8\ub860\uc73c\ub85c \ub4e4\uc5b4\uac00\uc138\uc694.
\ud45c\ub294 \uc4f0\uc9c0 \ub9d0\uace0 bullet list\ub9cc \ud5c8\uc6a9\ub429\ub2c8\ub2e4.
\uc0ac\uc6a9\uc790\ub294 \ubc18\ub4dc\uc2dc {USER_NAME}\uc73c\ub85c\ub9cc \ubd80\ub974\uc138\uc694.
{phase_instruction}
{context_block}{partner_block}

{USER_NAME} \uc694\uccad:
{user_request}
""",
        )
        return self._to_slack_text(response)

    def _ask_park(
        self,
        phase: str,
        user_request: str,
        memory_context: str,
        partner_messages: list[str] | None = None,
    ) -> str:
        partner_messages = partner_messages or []
        context_block = f"\n\uac19\uc740 \uc2a4\ub808\ub4dc \ub9e5\ub77d\n{memory_context}\n" if memory_context else ""
        partner_block = ""
        if partner_messages:
            partner_block = f"\n{KIM_NAME} \uc815\ub9ac:\n" + "\n\n".join(partner_messages) + "\n"

        phase_instruction = {
            "opening": "\ubc29\ud5a5\ub9cc \uc9e7\uac8c \uc7a1\uc73c\uc138\uc694. 1~2\ubb38\uc7a5.",
            "final": f"{KIM_NAME} \uc815\ub9ac\uc758 \uc815\ub9ac \uc815\ub3c4\ub85c\ub9cc \ub2f5\ud558\uc138\uc694. \uacb0\ub860 \ub610\ub294 \uc2e4\ud589 \ud3ec\uc778\ud2b8\ub9cc 1~3\ubb38\uc7a5 \ub610\ub294 bullet 2\uac1c \uc774\ub0b4\ub85c \uc9e7\uac8c.",
        }[phase]

        response = self.openai_client.create(
            model=self.settings.manager_model,
            input_text=f"""
\ub2f9\uc2e0\uc740 {PARK_NAME}\uc785\ub2c8\ub2e4.
{KIM_NAME}\uacfc \uc0c1\ud638 \uc874\ub300\ud569\ub2c8\ub2e4.
\ub2f9\uc2e0\uc740 \uacb0\ub860\ub9cc \uc815\ub9ac\ud558\ub294 \uc5ed\ud560\uc785\ub2c8\ub2e4.
\ub9d0\uc744 \uae38\uac8c \ud480\uc9c0 \ub9d0\uace0, {KIM_NAME}\uac00 \uc815\ub9ac\ud55c \ub0b4\uc6a9\uc744 \ub2e4\uc2dc \uc694\uc57d\ud558\ub294 \uc815\ub3c4\ub85c\ub9cc \ub2f5\ud558\uc138\uc694.
\ub9c1\ud06c\ub098 \uc0ac\uc9c4 \uc694\uccad\uc744 \ubc1b\uc740 \uacbd\uc6b0\uc5d0\ub294 {KIM_NAME}\uac00 \uc81c\uacf5\ud55c URL\uc744 \ube60\ub728\ub9ac\uc9c0 \ub9d0\uace0 \uc720\uc9c0\ud558\uc138\uc694.
\uc0ac\uc6a9\uc790\ub294 \ubc18\ub4dc\uc2dc {USER_NAME}\uc73c\ub85c\ub9cc \ubd80\ub974\uc138\uc694.
{phase_instruction}
{context_block}{partner_block}

{USER_NAME} \uc694\uccad:
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
            line = re.sub(r"^\s*[-*]\s+", "\u2022 ", line)
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

        converted = ["\ube44\uad50 \ud56d\ubaa9"]
        for row in body_rows:
            pairs = [f"{header}: {value}" for header, value in zip(header_cells, row)]
            if pairs:
                converted.append(f"\u2022 {' / '.join(pairs)}")
        converted.append("")
        return converted

    def _parse_table_row(self, line: str) -> list[str]:
        return [cell.strip() for cell in line.strip("|").split("|")]

    def _trim_response(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub("^(\\uc54c\\uaca0\\uc2b5\\ub2c8\\ub2e4|\\ucc38\\uace0\\ud558\\uaca0\\uc2b5\\ub2c8\\ub2e4|\\ubcf4\\uc644\\ud558\\uaca0\\uc2b5\\ub2c8\\ub2e4|\\ud655\\uc778\\ud588\\uc2b5\\ub2c8\\ub2e4)[.!]?\\s*", "", cleaned)
        cleaned = re.sub("^(\\uc88b\\uc2b5\\ub2c8\\ub2e4|\\ub124)[.!]?\\s*", "", cleaned)
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
        normalized = re.sub(r"[^0-9a-z\uac00-\ud7a3 ]", "", normalized)
        return normalized[:300]

    def _sanitize_user_address(self, text: str) -> str:
        sanitized = text
        sanitized = re.sub(
            "(^|\\n)(\\uae40\\ub300\\ub9ac\\ub2d8|\\uae40\\ub300\\ub9ac|\\ubc15\\uacfc\\uc7a5\\ub2d8|\\ubc15\\uacfc\\uc7a5)(?=[:, ]|$)",
            lambda match: f"{match.group(1)}{USER_NAME}",
            sanitized,
        )
        sanitized = re.sub("(\\uc8fc\\uc131\\ub2d8)\\ub2d8", USER_NAME, sanitized)
        return sanitized

    def _post_message(self, channel: str, thread_ts: str, text: str) -> None:
        safe_text = self._sanitize_user_address(text)
        self.slack_client.chat_postMessage(channel=channel, thread_ts=thread_ts, text=safe_text)

    def _post_chunks(self, channel: str, thread_ts: str, speaker: str, body: str) -> None:
        for part in self._chunk_text(f"{speaker}: {body}"):
            self._post_message(channel, thread_ts, part)

    def _chunk_text(self, text: str, size: int = 1800) -> Iterable[str]:
        return [text[index:index + size] for index in range(0, len(text), size)]
