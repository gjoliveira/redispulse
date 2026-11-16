
# RedisPulse

**Real-Time LLM Inference Monitoring with Redis**

RedisPulse is an academic project developed for the
Non-Relational Databases (BDNR) course at FEUP.

The goal is to design and implement a Redis-based system
for monitoring LLM inference workloads, including latency,
throughput, error rates, token usage, and model-version
comparisons.

## Dataset

RedisPulse uses the Microsoft Azure LLM Inference Trace 2023:

- Conversation workload
- Code-generation workload

Each trace contains:
- `TIMESTAMP`
- `ContextTokens`
- `GeneratedTokens`

The dataset does not contain inference latency, errors,
generated responses, or ground-truth labels.

We therefore simulate latency, failures, and deployment
versions while preserving the trace's request timing
patterns and token counts.

Dataset:
https://github.com/Azure/AzurePublicDataset/blob/master/AzureLLMInferenceDataset2023.md

## Simulated models

| Model | Versions | Azure workload |
|---|---|---|
| ConversationLLM | v1.0, v1.1 | Conversation |
| CodeLLM | v1.0, v1.1 | Code |

These are simulated LLM deployments, not executable
machine-learning models.

## Current functionality

- Load Azure LLM inference traces from CSV
- Validate model, version, and inference event schemas
- Generate simulated inference events
- Store models, versions and inference events in Redis
- Search and filter events with Redis Search
- Aggregate monitoring metrics and compare versions
- Apply event and metrics retention
- Run automated tests against an isolated Redis
- Run Redis and FastAPI with Docker Compose
- Check API and Redis connectivity

The FastAPI query endpoints and the dashboard are not
implemented yet.

## Project structure

```text
redispulse/
├── app/
│   ├── main.py            # FastAPI app (health check)
│   ├── schemas.py
│   ├── redis_registry.py  # models and versions
│   └── redis_events.py    # events, search, metrics, retention
├── config/
│   └── models.json        # simulated models and versions
├── data/
│   ├── raw/               # Azure CSV traces (not in Git)
│   └── sample/
│       └── events.jsonl   # shared baseline of 200 events
├── docs/                  # M1/M2 documentation
├── simulator/
│   ├── generator.py
│   └── trace_loader.py
├── tests/
├── compose.yaml
├── compose.test.yaml      # isolated Redis for tests
├── Dockerfile
└── requirements.txt
```

## Setup

### Requirements

- Python 3.12 or newer
- Docker and Docker Compose

### Start Redis and FastAPI

```bash
docker compose up --build -d
```

Check the API:

http://localhost:8001/health

### Prepare the Azure datasets

Download the conversation and code CSV files from the
official dataset page and place them in `data/raw/`.

Expected filenames:

- `AzureLLMInferenceTrace_conv.csv`
- `AzureLLMInferenceTrace_code.csv`

The original CSV files are excluded from Git.

### Generate inference events

From the project root, with the Python environment active:

```bash
python -m simulator.generator
```

### Run tests

The Redis tests use a separate Redis container on port 6380, so
they never affect the development data in the main Redis (port 6379).

```bash
docker compose -f compose.test.yaml up -d
python -m pytest tests/ -q
docker compose -f compose.test.yaml down
```

## Documentation

See [Shared Foundation](docs/SHARED_FOUNDATION.md) for
the data pipeline, schemas, simulation assumptions,
limitations, and M2 handoff.

## Project status

The shared foundation, the Redis database design (M2)
and the Redis data layer are implemented.

The API query endpoints and the monitoring dashboard
are planned for subsequent development stages.
