from slackbot_lab.bot import SlackDualAgentBot
from slackbot_lab.config import Settings
from slackbot_lab.http_transport import create_http_app
from slackbot_lab.socket_transport import run_socket_mode

settings = Settings.from_env()
bot = SlackDualAgentBot(settings)
app = create_http_app(bot, settings)


if __name__ == "__main__":
    if settings.transport == "socket":
        run_socket_mode(bot, settings)
    else:
        import uvicorn

        uvicorn.run("main:app", host=settings.host, port=settings.port, reload=False)
