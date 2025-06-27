# notifier_server.py
import os
import logging
import sys
from concurrent import futures

import grpc
from slack_sdk import WebClient
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

# Slack client to post messages
BOT_TOKEN = os.getenv("BOT_TOKEN")
slack_client = WebClient(token=BOT_TOKEN)

# Port for this gRPC server
NOTIFIER_PORT = "50052"

# --- gRPC Notifier Service ---
class NotifierServicer(slackbot_pb2_grpc.NotifierServicer):
    """
    gRPC service that the processing server calls back to when a task is complete.
    """
    def PostReply(self, request, context):
        """
        Receives a processed reply and posts it to the correct Slack thread.
        """
        logging.info(f"Notifier service received callback to post reply in channel {request.channel}")
        try:
            slack_client.chat_postMessage(
                channel=request.channel,
                thread_ts=request.thread_ts,
                text=request.text
            )
            logging.info("NOTIFIER: Successfully posted final reply to Slack.")
            return slackbot_pb2.ReplyResponse(ok=True)
        except SlackApiError as e:
            logging.error(f"Failed to post Slack message via notifier: {e.response['error']}")
            return slackbot_pb2.ReplyResponse(ok=False)

# --- Start the Server ---
def serve():
    """Starts the gRPC server for receiving notifications."""
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    slackbot_pb2_grpc.add_NotifierServicer_to_server(NotifierServicer(), server)
    server.add_insecure_port(f"0.0.0.0:{NOTIFIER_PORT}")
    
    logging.info(f"✅ gRPC Notifier server started and listening on port {NOTIFIER_PORT}...")
    
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()