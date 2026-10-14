from kafka import KafkaProducer
import json
import time

producer = KafkaProducer(
    bootstrap_servers="localhost:9092",

    acks="all",

    retries=5,

    enable_idempotence=True,

    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)

for i in range(10):

    message = {
        "video_id": "lecture_01",
        "chunk_id": i,
        "timestamp": i * 5,
        "text": f"This is lecture audio chunk {i}"
    }

    producer.send("video_audio", value=message)

    print("Sent:", message)

    time.sleep(1)

producer.flush()
producer.close()