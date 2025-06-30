# http_gateway.py
import os
import logging
import sys
import hmac
import hashlib
import time
import json

import grpc
import uvicorn
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import PlainTextResponse
from dotenv import load_dotenv

import slackbot_pb2
import slackbot_pb2_grpc

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout
)
logger = logging.getLogger(__name__)


SIGNING_SECRET = os.getenv("SIGNING_SECRET")
if not SIGNING_SECRET:
    logger.error("FATAL: SIGNING_SECRET environment variable not set.")
    sys.exit(1)

PROCESSING_SERVER_ADDRESS = "localhost:50051" # Address of the main worker server
GATEWAY_NOTIFIER_ADDRESS = "localhost:50052" # The gRPC server on the gateway


app = FastAPI()


def verify_slack_request(timestamp: str, signature: str, request_body: bytes):
    """
    https://api.slack.com/authentication/verifying-requests-from-slack
    implemented 5 STEPS from here only
    """
    # STEP 1 grab signing secret

    # STEP 2 timestamp is recent (within 5 minutes)
    if not timestamp or abs(time.time() - int(timestamp)) > 60 * 5:
        logger.warning("Request timestamp is invalid or too old.")
        return False

    # STEP 3 the base string
    base_string = f"v0:{timestamp}:".encode('utf-8') + request_body

    # STEP 4 Create the HMAC-SHA256 hash
    secret = SIGNING_SECRET.encode('utf-8')
    my_signature = 'v0=' + hmac.new(secret, base_string, hashlib.sha256).hexdigest()

    # STEP 5 Compare signatures
    if hmac.compare_digest(my_signature, signature):
        return True
    else:
        logger.warning("Request signature verification failed.")
        return False

def handle_app_mention(event):
    """
    Handles the logic for an app_mention event. This is where the core work happens.
    """
    if event.get("bot_id") or event.get("subtype"):
        logger.info("Ignoring message from a bot or a subtype event.")
        return

    message_text = event.get("text", "").strip()
    channel = event["channel"]
    user = event["user"]
    ts = event["ts"]
    thread_to_reply_in = event.get("thread_ts", ts)

    logger.info(f"Gateway received message: '{message_text}'")

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
        logger.info("Attempting to send failure notification back to user...")
        try:
            with grpc.insecure_channel(GATEWAY_NOTIFIER_ADDRESS) as grpc_channel:
                stub = slackbot_pb2_grpc.NotifierStub(grpc_channel)
                text = f"Sorry, <@{user}>, I can't connect to my processing service right now. Please try again later."
                request = slackbot_pb2.ReplyRequest(
                    channel=channel,
                    thread_ts=thread_to_reply_in,
                    text=text
                )
                response = stub.PostReply(request)
                if response.ok:
                    logger.info("Successfully posted failure notification.")
                else:
                    logger.error("Notifier service reported an error posting the reply.")
        except grpc.RpcError as e_notify:
            logger.error(f"gRPC Error: Could not send failure notification. {e_notify}")


@app.post("/slack/events")
async def slack_events(request: Request):
    """
    Handles all incoming HTTP requests from Slack.
    It verifies the request, handles URL verification challenges,
    and dispatches events to the appropriate handlers.
    """
    # 1. Get headers and body for verification
    timestamp = request.headers.get('X-Slack-Request-Timestamp')
    signature = request.headers.get('X-Slack-Signature')
    body = await request.body()

    # 2. Verify the request signature
    if not verify_slack_request(timestamp, signature, body):
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    # 3. Handle Slack's URL Verification challenge
    data = json.loads(body)
    if data and data.get("type") == "url_verification":
        logger.info("Received URL verification challenge from Slack.")
        return PlainTextResponse(content=data["challenge"])

    # 4. Handle actual events
    if data and data.get("type") == "event_callback":
        event = data.get("event", {})
        if event.get("type") == "app_mention":
            handle_app_mention(event)

    # 5. Acknowledge the request to Slack
    return Response(status_code=status.HTTP_200_OK)

# --- Start the Gateway ---
if __name__ == "__main__":
    logger.info("🤖 Slack HTTP gateway starting on port 3000...")
    uvicorn.run(app, host="0.0.0.0", port=3000)