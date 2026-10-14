from kafka import KafkaConsumer
import json

consumer = KafkaConsumer(
    "video_audio",

    bootstrap_servers="localhost:9092",

    group_id="transcription-workers",

    auto_offset_reset="earliest",

    enable_auto_commit=False,

    value_deserializer=lambda v: json.loads(v.decode("utf-8"))
)

print("Consumer started...")

for message in consumer:

    try:
        print("Processing:", message.value)

        # Our processing logic will eventually go here
        # Example:
        # transcribe_audio(message.value)

        print("Processing successful")

        consumer.commit()

    except Exception as e:

        print("Processing failed:", e)