import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Settings:
    slack_bot_token: str
    openai_api_key: str
    transport: str = "http"
    slack_signing_secret: str | None = None
    slack_app_token: str | None = None
    host: str = "0.0.0.0"
    port: int = 3002
    research_model: str = "gpt-5.2"
    manager_model: str = "gpt-5.2"
    smalltalk_model: str = "gpt-5-mini"
    memory_db_path: str = "data/conversation_memory.db"

    @classmethod
    def from_env(cls) -> "Settings":
        slack_bot_token = os.getenv("SLACK_BOT_TOKEN", "").strip()
        openai_api_key = os.getenv("OPENAI_API_KEY", "").strip()
        transport = os.getenv("SLACK_TRANSPORT", "http").strip().lower()

        if transport not in {"http", "socket"}:
            raise ValueError("SLACK_TRANSPORT must be either 'http' or 'socket'.")

        if not slack_bot_token:
            raise ValueError("SLACK_BOT_TOKEN is required.")
        if not openai_api_key:
            raise ValueError("OPENAI_API_KEY is required.")

        slack_signing_secret = os.getenv("SLACK_SIGNING_SECRET", "").strip() or None
        slack_app_token = os.getenv("SLACK_APP_TOKEN", "").strip() or None

        if transport == "http" and not slack_signing_secret:
            raise ValueError("SLACK_SIGNING_SECRET is required for http transport.")
        if transport == "socket" and not slack_app_token:
            raise ValueError("SLACK_APP_TOKEN is required for socket transport.")

        return cls(
            slack_bot_token=slack_bot_token,
            openai_api_key=openai_api_key,
            transport=transport,
            slack_signing_secret=slack_signing_secret,
            slack_app_token=slack_app_token,
            host=os.getenv("HOST", "0.0.0.0").strip(),
            port=int(os.getenv("PORT", "3002").strip()),
            research_model=os.getenv("OPENAI_RESEARCH_MODEL", "gpt-5.2").strip(),
            manager_model=os.getenv("OPENAI_MANAGER_MODEL", "gpt-5.2").strip(),
            smalltalk_model=os.getenv("OPENAI_SMALLTALK_MODEL", "gpt-5-mini").strip(),
            memory_db_path=os.getenv("MEMORY_DB_PATH", "data/conversation_memory.db").strip(),
        )
