from kafka import KafkaProducer
import json
from pathlib import Path


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

KAFKA_SERVER = "127.0.0.1:9092"
TOPIC = "video_audio"

AUDIO_DIR = Path("../data/audio_chunks/lecture_01")

VIDEO_ID = "lecture_01"
CHUNK_DURATION = 5


# --------------------------------------------------
# KAFKA PRODUCER
# --------------------------------------------------

producer = KafkaProducer(
    bootstrap_servers=KAFKA_SERVER,

    # Wait for Kafka to acknowledge the message
    acks="all",

    # Retry failed sends
    retries=5,

    # Prevent duplicates caused by producer retries
    enable_idempotence=True,

    # Convert Python dictionary → JSON bytes
    value_serializer=lambda v: json.dumps(v).encode("utf-8")
)


# --------------------------------------------------
# PUBLISH AUDIO CHUNKS
# --------------------------------------------------

def publish_audio_chunks():

    audio_files = sorted(AUDIO_DIR.glob("*.wav"))

    print(f"Found {len(audio_files)} audio chunks.")

    for chunk_id, audio_file in enumerate(audio_files):

        start_time = chunk_id * CHUNK_DURATION
        end_time = start_time + CHUNK_DURATION

        event = {
            "video_id": VIDEO_ID,
            "chunk_id": chunk_id,
            "start_time": start_time,
            "end_time": end_time,
            "audio_path": str(audio_file)
        }

        producer.send(
            TOPIC,
            value=event,
            key=VIDEO_ID.encode("utf-8")
        )

        print("Published:", event)

    producer.flush()
    producer.close()

    print("All chunks published successfully.")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    publish_audio_chunks()