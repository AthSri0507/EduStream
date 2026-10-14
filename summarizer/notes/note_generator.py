import json
import re

from kafka import KafkaConsumer, KafkaProducer


# --------------------------------------------------
# Kafka configuration
# --------------------------------------------------

KAFKA_SERVER = "127.0.0.1:9092"

INPUT_TOPIC = "generated_notes"
OUTPUT_TOPIC = "final_notes"

CONSUMER_GROUP = "note-generator"


# --------------------------------------------------
# Kafka Consumer
# --------------------------------------------------

consumer = KafkaConsumer(
    INPUT_TOPIC,

    bootstrap_servers=KAFKA_SERVER,

    group_id=CONSUMER_GROUP,

    auto_offset_reset="earliest",

    enable_auto_commit=False,

    value_deserializer=lambda x: json.loads(
        x.decode("utf-8")
    )
)


# --------------------------------------------------
# Kafka Producer
# --------------------------------------------------

producer = KafkaProducer(
    bootstrap_servers=KAFKA_SERVER,

    acks="all",

    retries=5,

    enable_idempotence=True,

    value_serializer=lambda x: json.dumps(
        x
    ).encode("utf-8")
)


# --------------------------------------------------
# Simple extractive summarizer
# --------------------------------------------------

def generate_notes(transcript):

    # Split transcript into sentences
    sentences = re.split(
        r'(?<=[.!?])\s+',
        transcript
    )

    # Remove empty sentences
    sentences = [
        sentence.strip()
        for sentence in sentences
        if sentence.strip()
    ]

    notes = []

    for sentence in sentences:

        # Ignore extremely short sentences
        if len(sentence.split()) >= 5:
            notes.append(sentence)

    # Keep maximum 5 sentences
    return notes[:5]


# --------------------------------------------------
# Start processing
# --------------------------------------------------

print("Note generator started...")

for message in consumer:

    event = message.value

    transcript = event["transcript"]

    print("\nReceived transcript:")
    print(transcript)

    notes = generate_notes(transcript)

    output = {
        "video_id": event["video_id"],
        "window_start": event["window_start"],
        "window_end": event["window_end"],
        "notes": notes
    }

    # Send generated notes to Kafka
    future = producer.send(
    OUTPUT_TOPIC,
    value=output
)

    result = future.get(timeout=10)

    print(
    f"Sent to Kafka: topic={result.topic}, "
    f"partition={result.partition}, "
    f"offset={result.offset}"
    )

    producer.flush()

    

    # Commit only after successful processing
    consumer.commit()

    print("\nGenerated notes:")
    print(output)