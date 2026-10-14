from kafka import KafkaConsumer, KafkaProducer
import json
from faster_whisper import WhisperModel
from pathlib import Path

KAFKA_SERVER = "127.0.0.1:9092"

INPUT_TOPIC = "video_audio"
OUTPUT_TOPIC = "transcriptions"

CONSUMER_GROUP = "transcription-workers"


# --------------------------------------------------
# 1. Load Whisper model
# --------------------------------------------------

print("Loading Whisper model...")

model = WhisperModel(
    "base",
    device="cpu",
    compute_type="int8"
)

print("Whisper model loaded.")


# --------------------------------------------------
# 2. Create Kafka consumer
# --------------------------------------------------

consumer = KafkaConsumer(
    INPUT_TOPIC,
    bootstrap_servers=KAFKA_SERVER,
    group_id=CONSUMER_GROUP,
    auto_offset_reset="earliest",
    enable_auto_commit=False,
    max_poll_interval_ms=600000,
    session_timeout_ms=30000,
    value_deserializer=lambda x: json.loads(x.decode("utf-8"))
)


# --------------------------------------------------
# 3. Create Kafka producer
# --------------------------------------------------

producer = KafkaProducer(
    bootstrap_servers=KAFKA_SERVER,
    acks="all",
    retries=5,
    enable_idempotence=True,
    value_serializer=lambda x: json.dumps(x).encode("utf-8")
)


# --------------------------------------------------
# 4. Process Kafka messages
# --------------------------------------------------

print("Waiting for audio chunks...")

for message in consumer:

    event = message.value

    print(
        f"Received chunk {event['chunk_id']} "
        f"from video {event['video_id']}"
    )

    PROJECT_ROOT = Path(__file__).resolve().parents[2]

    audio_path = (
    PROJECT_ROOT
    / "data"
    / "audio_chunks"
    / event["video_id"]
    / f"chunk_{event['chunk_id']:04d}.wav"
    )

    print(f"Transcribing: {audio_path}")

    segments, info = model.transcribe(str(audio_path))

    # ----------------------------------------------
    # Transcribe audio
    # ----------------------------------------------

    segments, info = model.transcribe(audio_path)

    text = " ".join(
        segment.text.strip()
        for segment in segments
    )

    print("Transcript:")
    print(text)

    # ----------------------------------------------
    # Create output event
    # ----------------------------------------------

    transcript_event = {
        "video_id": event["video_id"],
        "chunk_id": event["chunk_id"],
        "start_time": event["start_time"],
        "end_time": event["end_time"],
        "text": text
    }

    # ----------------------------------------------
    # Send to next Kafka topic
    # ----------------------------------------------

    producer.send(
        OUTPUT_TOPIC,
        value=transcript_event
    )

    producer.flush()

    print(
        f"Published transcript for chunk "
        f"{event['chunk_id']}"
    )

    # ----------------------------------------------
    # Commit only after successful processing
    # ----------------------------------------------

    consumer.commit()

    print("Offset committed.")