# http_gateway.py
import os
import logging
import sys

import grpc
from flask import Flask, request
from slack_bolt import App
from slack_bolt.adapter.flask import SlackRequestHandler
from slack_sdk.errors import SlackApiError
from dotenv import load_dotenv

import slackbot_pb2
import slackbot_pb2_grpc

# --- Configuration & Initialization ---
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)

GATEWAY_NOTIFIER_ADDRESS = "localhost:50052" # The gRPC server on the gateway

BOT_TOKEN = os.getenv("BOT_TOKEN")
SIGNING_SECRET = os.getenv("SIGNING_SECRET")
PROCESSING_SERVER_ADDRESS = "localhost:50051" # Address of the main worker server

app = App(token=BOT_TOKEN, signing_secret=SIGNING_SECRET)
flask_app = Flask(__name__)
handler = SlackRequestHandler(app)

# A simple in-memory store for duplicate message detection
message_store = {}

@app.event("app_mention")
def handle_app_mention(event, say, logger):
    """
    Handles mentions, sends tasks to the processing server via gRPC,
    and provides an initial acknowledgment in Slack.
    """
    if event.get("bot_id") or event.get("subtype"):
        return

    message_text = event.get("text", "").strip()
    channel = event["channel"]
    user = event["user"]
    ts = event["ts"]
    thread_to_reply_in = event.get("thread_ts", ts)

    logger.info(f"Gateway received message: '{message_text}'")

    # is_in_thread = bool(event.get("thread_ts"))
    # if not is_in_thread and message_text in message_store:
    #     try:
    #         original_ts = message_store[message_text]["ts"]
    #         permalink_response = app.client.chat_getPermalink(channel=channel, message_ts=original_ts)
    #         permalink = permalink_response["permalink"]
    #         logger.info(f"Found duplicate. Responding with link: {permalink}")
    #         say(text=f"I've seen this message before! Find the original here: {permalink}", thread_ts=thread_to_reply_in)
    #     except SlackApiError as e:
    #         logger.error(f"Error getting permalink for duplicate: {e.response['error']}")
    #         say(text="I've seen that message before, but I couldn't get the link.", thread_ts=thread_to_reply_in)
    #     return

    # # Store new, non-thread message to prevent future duplicates
    # if not is_in_thread:
    #     message_store[message_text] = {"ts": ts, "channel": channel}
    #     logger.info(f"Stored new message: '{message_text}'")

    # --- Send to Processing Server via gRPC ---
    try:
        with grpc.insecure_channel(PROCESSING_SERVER_ADDRESS) as grpc_channel:
            stub = slackbot_pb2_grpc.ProcessorStub(grpc_channel)
            grpc_request = slackbot_pb2.ProcessRequest(
                text=message_text,
                channel=channel,
                ts=ts,
                thread_ts=thread_to_reply_in,
                user=user
            )
            stub.ProcessMessage(grpc_request) # Fire and forget
            logger.info("Successfully sent message to processing server.")
    except grpc.RpcError as e:
        logger.error(f"gRPC Error: Could not send message to the processing server. {e}")
        logging.info("Attempting to send acknowledgement to gateway...")
        try:
            with grpc.insecure_channel(GATEWAY_NOTIFIER_ADDRESS) as grpc_channel:
                stub = slackbot_pb2_grpc.NotifierStub(grpc_channel)
                text=f"Sorry, <@{user}>, I can't connect to my processing service right now. Please try again later."
                request = slackbot_pb2.ReplyRequest(
                    channel=channel,
                    thread_ts=thread_to_reply_in,
                    text=text
                )
                response = stub.PostReply(request)
                if response.ok:
                    logging.info("Successfully sent final reply to gateway.")
                else:
                    logging.error("Gateway reported an error posting the reply.")
        except grpc.RpcError as e:
            logging.error(f"gRPC Error: Could not send final reply to gateway. {e}")

# --- Flask Route for Slack Events ---
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():
    """Passes incoming Slack HTTP requests to the Bolt app handler."""
    return handler.handle(request)

# --- Start the Gateway ---
if __name__ == "__main__":
    logger.info("🤖 Slack HTTP gateway starting on port 3000...")
    flask_app.run(host="0.0.0.0", port=3000)