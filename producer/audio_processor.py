import subprocess
from pathlib import Path


# --------------------------------------------------
# CONFIGURATION
# --------------------------------------------------

VIDEO_PATH = Path("../data/videos/lecture.mp4")

OUTPUT_DIR = Path("../data/audio_chunks/lecture_01")

CHUNK_DURATION = 5


# --------------------------------------------------
# AUDIO EXTRACTION
# --------------------------------------------------

def extract_audio_chunks():

    # Create output directory if it doesn't exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    output_pattern = OUTPUT_DIR / "chunk_%04d.wav"

    command = [
        "ffmpeg",

        "-i", str(VIDEO_PATH),

        # Remove video
        "-vn",

        # Mono audio
        "-ac", "1",

        # 16 kHz sampling rate
        "-ar", "16000",

        # Split into segments
        "-f", "segment",
        "-segment_time", str(CHUNK_DURATION),

        # PCM WAV
        "-c:a", "pcm_s16le",

        str(output_pattern)
    ]

    print("Starting audio extraction...")

    subprocess.run(command, check=True)

    print("Audio extraction completed.")


# --------------------------------------------------
# MAIN
# --------------------------------------------------

if __name__ == "__main__":
    extract_audio_chunks()