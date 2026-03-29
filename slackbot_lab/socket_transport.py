import threading
from threading import Event

from slack_sdk.socket_mode import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.web import WebClient

from slackbot_lab.bot import SlackDualAgentBot
from slackbot_lab.config import Settings


def run_socket_mode(bot: SlackDualAgentBot, settings: Settings) -> None:
    client = SocketModeClient(
        app_token=settings.slack_app_token or "",
        web_client=WebClient(token=settings.slack_bot_token),
    )

    def process(client_: SocketModeClient, request: SocketModeRequest) -> None:
        if request.type != "events_api":
            return

        client_.send_socket_mode_response(SocketModeResponse(envelope_id=request.envelope_id))

        payload = request.payload or {}
        event = payload.get("event", {})

        if event.get("bot_id"):
            return

        if event.get("type") == "app_mention":
            channel = event.get("channel")
            thread_ts = event.get("thread_ts") or event.get("ts")
            text = event.get("text", "")

            worker = threading.Thread(
                target=bot.handle_mention,
                args=(channel, thread_ts, text),
                daemon=True,
            )
            worker.start()

    client.socket_mode_request_listeners.append(process)
    client.connect()
    Event().wait()
