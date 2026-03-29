import json

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request
from slack_sdk.signature import SignatureVerifier

from slackbot_lab.bot import SlackDualAgentBot
from slackbot_lab.config import Settings


def create_http_app(bot: SlackDualAgentBot, settings: Settings) -> FastAPI:
    app = FastAPI(title="slackbot-lab")
    signature_verifier = SignatureVerifier(signing_secret=settings.slack_signing_secret or "")
    processed_event_ids: set[str] = set()

    @app.get("/healthz")
    async def healthz():
        return {"ok": True, "transport": settings.transport}

    @app.post("/slack/events")
    async def slack_events(req: Request, background_tasks: BackgroundTasks):
        raw_body = await req.body()

        if not signature_verifier.is_valid_request(raw_body, req.headers):
            raise HTTPException(status_code=401, detail="Invalid Slack signature")

        data = json.loads(raw_body.decode("utf-8"))

        if "challenge" in data:
            return {"challenge": data["challenge"]}

        event_id = data.get("event_id")
        if event_id and event_id in processed_event_ids:
            return {"ok": True}

        if event_id:
            processed_event_ids.add(event_id)
            if len(processed_event_ids) > 1000:
                processed_event_ids.pop()

        event = data.get("event", {})
        if event.get("bot_id") or event.get("subtype"):
            return {"ok": True}

        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = event.get("text", "")

        if event.get("type") == "app_mention":
            background_tasks.add_task(bot.handle_mention, channel, thread_ts, text)
            return {"ok": True}

        if event.get("type") == "message" and event.get("thread_ts") and bot.should_reply_in_thread(channel, thread_ts):
            background_tasks.add_task(bot.handle_mention, channel, thread_ts, text)

        return {"ok": True}

    return app
