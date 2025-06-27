# processing_server.py
import logging
import time
import queue
import threading
from concurrent import futures

import grpc

import slackbot_pb2
import slackbot_pb2_grpc

logging.basicConfig(level=logging.DEBUG)
GATEWAY_NOTIFIER_ADDRESS = "localhost:50052" # The gRPC server on the gateway

message_queue = queue.Queue()

def send_final_reply(channel, thread_ts, text):
    """
    Calls the Notifier service on the HTTP gateway to post the final message.
    """
    logging.info("Attempting to send final reply back to gateway...")
    try:
        with grpc.insecure_channel(GATEWAY_NOTIFIER_ADDRESS) as grpc_channel:
            stub = slackbot_pb2_grpc.NotifierStub(grpc_channel)
            request = slackbot_pb2.ReplyRequest(
                channel=channel,
                thread_ts=thread_ts,
                text=text
            )
            response = stub.PostReply(request)
            if response.ok:
                logging.info("Successfully sent final reply to gateway.")
            else:
                logging.error("Gateway reported an error posting the reply.")
    except grpc.RpcError as e:
        logging.error(f"gRPC Error: Could not send final reply to gateway. {e}")

# --- Worker Thread ---
def process_message_queue():
    """
    Worker function that processes messages from the queue.
    """
    while True:
        try:
            # Get a message from the queue. This is a ProcessRequest object.
            request = message_queue.get() 
            
            logging.info(f"Worker is processing message: '{request.text}'. This will take 10 seconds.")
            time.sleep(10)

            final_reply_text = f"Hi there, <@{request.user}>! I have finished processing your message."

            send_final_reply(
                channel=request.channel,
                thread_ts=request.thread_ts,
                text=final_reply_text
            )

        except Exception as e:
            logging.error(f"Error processing message from queue: {e}")
        finally:
            message_queue.task_done()

class ProcessorServicer(slackbot_pb2_grpc.ProcessorServicer):
    """
    Implements the Processor gRPC service.
    """
    def ProcessMessage(self, request, context):
        """
        Receives a message from the gateway, adds it to the queue,
        and returns an immediate acknowledgment.
        """
        logging.info(f"Processor service received message: '{request.text}' and adding it to the queue.")
        message_queue.put(request)
        text="Message received! I'm working on it and will get back to you shortly."
        send_final_reply(
            channel=request.channel,
            thread_ts=request.thread_ts,
            text=text
        )
        return slackbot_pb2.ProcessResponse()

def serve():
    """
    Starts the gRPC server and the background worker thread.
    """

    worker_thread = threading.Thread(target=process_message_queue)
    worker_thread.daemon = True
    worker_thread.start()
    
    server = grpc.server(futures.ThreadPoolExecutor(max_workers=10))
    slackbot_pb2_grpc.add_ProcessorServicer_to_server(ProcessorServicer(), server)
    
    port = "50051"
    server.add_insecure_port(f"[::]:{port}")
    
    print(f"✅ Processing server started and listening on port {port}...")
    logging.info(f"gRPC Processor server listening on port {port}")
    
    server.start()
    server.wait_for_termination()

if __name__ == "__main__":
    serve()
