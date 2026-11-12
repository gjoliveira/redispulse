
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
- Export sample events to JSONL
- Run automated generator tests
- Run Redis and FastAPI with Docker Compose
- Check API and Redis connectivity

Redis event storage, monitoring queries, metric aggregation,
and the dashboard are not implemented yet.

## Project structure

```text
redispulse/
├── app/
│   ├── main.py
│   └── schemas.py
├── config/
│   └── models.json
├── data/
│   ├── raw/
│   └── sample/
│       └── events.jsonl
├── docs/
│   └── SHARED_FOUNDATION.md
├── simulator/
│   ├── generator.py
│   └── trace_loader.py
├── tests/
│   └── test_generator.py
├── compose.yaml
├── Dockerfile
├── export_sample.py
├── inspect_dataset.py
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

Export 200 sample events:

```bash
python export_sample.py
```

Output:

```text
data/sample/events.jsonl
```

### Run tests

```bash
python -m unittest discover -s tests -v
```

## Documentation

See [Shared Foundation](docs/SHARED_FOUNDATION.md) for
the data pipeline, schemas, simulation assumptions,
limitations, and M2 handoff.

## Project status

The shared foundation is implemented.

The Redis database design, application queries,
aggregations, and monitoring dashboard are planned
for subsequent development stages.
