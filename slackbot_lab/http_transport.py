import json
import threading

from flask import Flask, jsonify, request
from slack_sdk.signature import SignatureVerifier

from slackbot_lab.bot import SlackDualAgentBot
from slackbot_lab.config import Settings


def create_http_app(bot: SlackDualAgentBot, settings: Settings) -> Flask:
    app = Flask(__name__)
    signature_verifier = SignatureVerifier(signing_secret=settings.slack_signing_secret or "")
    processed_event_ids: set[str] = set()

    @app.get("/healthz")
    def healthz():
        return jsonify({"ok": True, "transport": settings.transport})

    @app.post("/slack/events")
    def slack_events():
        raw_body = request.get_data()

        if not signature_verifier.is_valid_request(raw_body, request.headers):
            return jsonify({"detail": "Invalid Slack signature"}), 401

        data = json.loads(raw_body.decode("utf-8"))

        if "challenge" in data:
            return jsonify({"challenge": data["challenge"]})

        event_id = data.get("event_id")
        if event_id and event_id in processed_event_ids:
            return jsonify({"ok": True})

        if event_id:
            processed_event_ids.add(event_id)
            if len(processed_event_ids) > 1000:
                processed_event_ids.pop()

        event = data.get("event", {})
        if event.get("bot_id") or event.get("subtype"):
            return jsonify({"ok": True})

        channel = event.get("channel")
        thread_ts = event.get("thread_ts") or event.get("ts")
        text = event.get("text", "")

        should_handle = False
        if event.get("type") == "app_mention":
            should_handle = True
        elif event.get("type") == "message" and event.get("thread_ts") and bot.should_reply_in_thread(channel, thread_ts):
            should_handle = True

        if should_handle:
            worker = threading.Thread(
                target=bot.handle_mention,
                args=(channel, thread_ts, text),
                daemon=True,
            )
            worker.start()

        return jsonify({"ok": True})

    return app
