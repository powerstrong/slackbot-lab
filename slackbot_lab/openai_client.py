from typing import Any

import httpx


class OpenAIResponsesClient:
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = "https://api.openai.com/v1/responses"
        self.client = httpx.Client(timeout=120.0)

    def create(self, model: str, input_text: str, tools: list[dict[str, Any]] | None = None) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "input": input_text,
        }
        if tools:
            payload["tools"] = tools

        response = self.client.post(
            self.base_url,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
        )
        response.raise_for_status()
        data = response.json()

        output_text = data.get("output_text")
        if isinstance(output_text, str) and output_text.strip():
            return output_text

        parts: list[str] = []
        for item in data.get("output", []):
            for content in item.get("content", []):
                text = content.get("text")
                if text:
                    parts.append(text)
        return "\n".join(parts).strip()
