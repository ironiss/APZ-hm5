import uuid
import httpx
import asyncio
import logging
import random
import json
import consul
import socket
import requests

from typing import Dict, Union, List

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from aiokafka import AIOKafkaProducer

producer = None
CONSUL = "http://consul:8500/v1/agent/service/register"


app = FastAPI()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


@app.on_event("startup")
async def startup_event():
    global producer
    producer = AIOKafkaProducer(
        bootstrap_servers=["kafka1:9092", "kafka2:9093", "kafka3:9094"]
    )
    await producer.start()

    service_id = f"{"facade"}-{str(uuid.uuid4())[:8]}"
    ip_address = socket.gethostbyname(socket.gethostname())

    data = {
        "ID": service_id,
        "Name": "facade",
        "Address": ip_address,
        "Port": 5001,
        "Check": {
            "HTTP": f"http://{ip_address}:{5001}/health",
            "Interval": "20s",
        },
    }
    
    requests.put(CONSUL, json=data)
    
    

@app.on_event("shutdown")
async def shutdown_kafka_producer():
    if producer:
        await producer.stop()


class MessageRequestQuery(BaseModel):
    msg: str

class MessageResponseQuery(BaseModel):
    all_msgs: str


class AvailableAPI(BaseModel):
    log_s: List[str]
    mes_s: List[str]


@app.get("/")
def read_root():
    return {"Hello": "World"}


def serv_url(service_name: str):
    res = requests.get(
        f"http://consul:8500/v1/health/service/{service_name}?passing=true"
    )
    
    instance = random.choice(res.json())["Service"]
    return f"http://{instance['Address']}:{instance['Port']}"



@app.post("/send_to_logging_service")
async def generate_uuid(query: MessageRequestQuery) -> Dict[str, str]: 
    """
    Generating UUID for message and sending to the logging-service.
    HTTP POST to the loggining service with query: {UUID (str), msg(str)}

    Args:
        query (.msg (str)) -- message from the client
    Returns:
        {"status": "<status code>"}
    """

    unique_id = str(uuid.uuid4())
    data_query = {"UUID": unique_id, "msg": query.msg}

    async with httpx.AsyncClient() as client:
        url = serv_url("logging")

        response = await client.post(url=f"{url}/fetching_message", json=data_query)

        await producer.send_and_wait("message-topic", json.dumps(data_query).encode("utf-8"))
                   
        if response.status_code == 200:
            return {"status": str(response.status_code)}
        

    return {"status": "500"}

  
@app.get("/get_resulted_messages")
async def get_messages() -> Union[MessageResponseQuery, Dict[str, str]]:
    """
    Gets all messages that was saved by logging-service.

    Args:
        None
    Returns:
        {"all_msgs": "<all messages from loggining service separated by ',' and from message service separated by '\n'>"}
        or 
        {"status": "<status code>"} if errors occured
    """

    url = serv_url("logging")
    url_msg = serv_url("messages")
    

    async with httpx.AsyncClient() as client:
        all_messages_response = await client.get(url=f"{url}/get_fetched_messages")
        static_text_response = await client.get(url=f"{url_msg}/message_handler")
        
        if static_text_response.status_code != 200 or all_messages_response.status_code != 200:
            return {"status": static_text_response.status_code}
        
    all_messages_json = all_messages_response.json()
    static_text_json = static_text_response.json()

    response = all_messages_json["msgs"] + "\n" + static_text_json["static_text"]
    return {"all_msgs": response}


@app.get("/health")
def health_check():
    return {"status": "ok"}