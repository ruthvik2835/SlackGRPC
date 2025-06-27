# http_gateway.py
import os
import logging

import grpc
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler

import slackbot_pb2
import slackbot_pb2_grpc

from flask import Flask, request

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO)


BOT_TOKEN = os.getenv("BOT_TOKEN")
SIGNING_SECRET = os.getenv("SIGNING_SECRET")

# gRPC server address
GRPC_SERVER_ADDRESS = "localhost:50051"

# --- Initialize the Slack App ---
app = App(
    token=BOT_TOKEN,
    signing_secret=SIGNING_SECRET
)

# --- Slack Event Handlers ---
@app.event("app_mention")
def handle_message_events(event, say, logger):
    """
    This handler listens for messages, sends them to the gRPC server for processing,
    and replies in Slack based on the server's response.
    """
    # Ignore messages from bots or message subtypes (e.g., channel joins)
    if event.get("bot_id") or event.get("subtype") is not None:
        return

    logger.info(f"Gateway received message: '{event.get('text', '')}'")

    thread_to_reply_in = event.get("thread_ts", event["ts"])

    try:
        # --- gRPC Client Logic ---
        with grpc.insecure_channel(GRPC_SERVER_ADDRESS) as channel:
            stub = slackbot_pb2_grpc.SlackBotStub(channel)
            
            # Create a request object from the Slack event data.
            grpc_request = slackbot_pb2.MessageRequest(
                text=event.get("text", ""),
                channel=event["channel"],
                ts=event["ts"],
                thread_ts=event.get("thread_ts", ""), # Pass the original thread_ts
                user=event["user"]
            )
            
            # Call the gRPC server
            grpc_response = stub.HandleMessage(grpc_request)

            # If the server determined a reply is needed, send it.
            if grpc_response.should_reply:
                say(
                    text=grpc_response.reply_text,
                    channel=event["channel"],
                    thread_ts=thread_to_reply_in
                )

    except grpc.RpcError as e:
        logger.error(f"gRPC Error: Could not connect to the server at {GRPC_SERVER_ADDRESS}. {e}")
        # Optionally, send an error message to Slack
        say(
            text=f"Sorry, <@{event['user']}>, I'm having trouble connecting to my brain right now. Please try again later.",
            channel=event["channel"],
            thread_ts=thread_to_reply_in
        )

# @app.event("message")
# def handle_app_mention(event, say, logger):
#     """

#     """
#     logger.info(f"Received an app_mention event: {event}")
#     user = event["user"]
#     thread_ts = event.get("thread_ts", event["ts"])
#     say(
#         channel=event["channel"],
#         thread_ts=thread_ts,
#         text=f"Hi there, <@{user}>! I'm a gRPC-powered bot. If you repeat a message, I'll point you to the first time it was sent."
#     )


# --- Start the Gateway ---
# Use Flask to handle incoming HTTP requests from Slack
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    """
    This route listens for incoming events from Slack.
    """
    return handler.handle(request)


#    Run with a production-ready WSGI server like Gunicorn:
#    gunicorn http_gateway:flask_app -b 0.0.0.0:3000
if __name__ == "__main__":
    print("🤖 Slack HTTP gateway starting...")
    # This is for local development only.
    flask_app.run(host="0.0.0.0", port=3000)

