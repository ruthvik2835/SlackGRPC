# grpc_server.py
import os
import logging
from concurrent import futures

import grpc
from slack_sdk import WebClient
from slack_sdk.errors import SlackApiError

import slackbot_pb2
import slackbot_pb2_grpc

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.DEBUG)

BOT_TOKEN = os.getenv("BOT_TOKEN")


message_store = {}
slack_client = WebClient(token=BOT_TOKEN)


# --- gRPC Servicer Implementation ---
class SlackBotServicer(slackbot_pb2_grpc.SlackBotServicer):
    """
    Implements the SlackBot gRPC service.
    """

    def HandleMessage(self, request, context):
        """
        Processes an incoming message request and determines the appropriate response.
        """
        message_text = request.text.strip()
        is_in_thread = bool(request.thread_ts)  # Check if the message is in a thread
        
        logging.info(f"gRPC Server received message: '{message_text}'")

        reply_text = ""
        should_reply = False

        # If the message is a duplicate and NOT in a thread, point to the original.
        if message_text in message_store and not is_in_thread:
            try:
                original_message_info = message_store[message_text]
                original_ts = original_message_info["ts"]
                original_channel = original_message_info["channel"]
                
                # Use the Slack client to get a permalink to the original message.
                permalink_response = slack_client.chat_getPermalink(
                    channel=original_channel,
                    message_ts=original_ts
                )
                permalink = permalink_response["permalink"]
                
                reply_text = f"I've seen this message before! You can find the original here: {permalink}"
                should_reply = True
                logging.info(f"Found duplicate. Responding with link: {permalink}")

            except SlackApiError as e:
                logging.error(f"Error getting permalink: {e.response['error']}")
                # Fallback reply if the API call fails
                reply_text = "I've seen that message before, but I couldn't get the link."
                should_reply = True

        # If it's a new message, store it and craft a welcome reply.
        else:
            # Only store the message if it's not already there.
            if message_text not in message_store:
                 logging.info(f"Storing new message: '{message_text}'")
                 message_store[message_text] = {
                    "ts": request.ts,
                    "channel": request.channel
                 }
            
            # This is the logic for the simple "Hi there" response for new messages
            reply_text = f"Hi there, <@{request.user}>!"
            should_reply = True

        return slackbot_pb2.MessageResponse(reply_text=reply_text, should_reply=should_reply)


# --- Start the Server ---
def serve():
    """
    Starts the gRPC server and waits for requests.
    """
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    slackbot_pb2_grpc.add_SlackBotServicer_to_server(SlackBotServicer(), server)
    
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    
    print(f"✅ gRPC server started and listening on port {port}...")
    logging.info(f"gRPC server listening on port {port}")
    
    server.start()
    server.wait_for_termination()


if __name__ == "__main__":
    serve()
