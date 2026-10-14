# EduStream

Real-time lecture transcription and note generation on Apache Kafka.


```
lecture video -> audio chunks -> Kafka -> Whisper workers -> Kafka Streams (30 s windows)
              -> Note Agent (free LLM API, extractive fallback) -> SQLite -> Streamlit dashboard
```

**Status:**  The pipeline code still being worked





## Requirements

- Windows 10/11, PowerShell 5.1+
- Python 3.10 (`py -3.10`)
- JDK 17 or newer
- Kafka 4.3.1 extracted to a path **without spaces** (default `C:\kafka_2.13-4.3.1`)
- No Docker and no GPU needed. Everything used is free.

## Setup

```powershell
# from the repo root
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1            # venv, packages, .env, Whisper models
powershell -ExecutionPolicy Bypass -File scripts\setup.ps1 -SkipModels  # same, without the ~600 MB model download
powershell -ExecutionPolicy Bypass -File scripts\preflight.ps1        # read-only environment checks
```

`setup.ps1` creates `.env` from `.env.example`. Put your free API keys
(Cerebras, Groq) in `.env` only, and never share that file.

## Layout

| Folder | Contents |
|---|---|
| `producer/` | Lecture source (Kafka producer) |
| `summarizer/transcription/` | Whisper transcription worker |
| `stream_processor/` | Kafka Streams app (Java 17) |
| `agents/` | Note Agent, Study Agent, LLM client |
| `storage/` | SQLite schema and the sink (only DB writer) |
| `dashboard/` | Streamlit dashboard |
| `common/` | Shared config, Kafka helpers, schema validation |
| `schemas/` | Message contract: JSON Schemas and golden fixtures |
| `tools/` | Small CLI helpers (tap, partition_of, send_flush, ...) |
| `bench/` | Benchmarks and evaluation scripts |
| `analysis/` | Dataset EDA |
| `infra/kafka/` | Broker configuration |
| `scripts/` | setup, preflight, start/stop/reset |
| `tests/` | pytest tests |
| `data/`, `models/`, `run/` | Local only: dataset, Whisper models, logs and PIDs |
