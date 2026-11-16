
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

| Model ID | Version ID | Label | Azure workload |
|---|---|---|---|
| `llm-conversation` | `conv-v1` | v1.0 | Conversation |
| `llm-conversation` | `conv-v2` | v1.1 | Conversation |
| `llm-code` | `code-v1` | v1.0 | Code |
| `llm-code` | `code-v2` | v1.1 | Code |

These are simulated LLM deployments, not executable
machine-learning models. They are defined in
`config/models.json`.

## Simulation

The generator (`simulator/generator.py`) reads Azure requests
and assigns them alternately to the two versions of the model.

Latency is simulated as:

```text
latency_ms = (100 + 0.02 * input_tokens + 6 * output_tokens)
             * version_factor
             * random_variation
```

| Parameter | v1.0 | v1.1 |
|---|---|---|
| Version factor | 1.0 | 0.8 |
| Failure probability | 8% | 2% |

The random variation is uniform between 0.9 and 1.1.

Timestamps are shifted so that the last request of a
generated batch is close to the current time, while the
gaps between requests from the trace are preserved.

These parameters are illustrative assumptions, not
measured Azure service characteristics.

### Data provenance

| Attribute | Source |
|---|---|
| Request timing pattern | Azure trace |
| Input and output tokens | Azure trace |
| Model/version assignment | Simulator |
| Latency | Simulator |
| Success/failure and error type | Simulator |
| Request ID | Simulator |

Metrics computed from these events must not be presented
as measured Azure latency or reliability results. Accuracy
and other ML-quality metrics are out of scope, because the
trace has no predictions or labels.

### Sample data

`data/sample/events.jsonl` holds a fixed baseline of 200
generated events (100 conversation, 100 code-generation),
shared by both project members for design examples and
early testing.

### Known limitations

- Request IDs (`conversation-00001`, ...) repeat across
  generator runs. Redis permanently remembers ingested
  request IDs, so a second run cannot be ingested into the
  same Redis instance.
- Redis only accepts events whose timestamps fall within the
  last 24 hours. The fixed sample file therefore serves as
  a reference, not as live ingestion input.
- Generated failures have an `error_type` but no
  `error_message`, so error keyword search has nothing to
  match on in simulated data.
- Both workloads use the same default random seed, so their
  random patterns are correlated.
- Versions receive alternating requests rather than identical
  workloads, so token-count differences can influence
  version comparisons.
- Failed requests keep the original output token counts.

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

- [Project plan](docs/PLAN.md)
- [Requirements coverage](docs/requirements-coverage.md)
- M2: [requirements](docs/m2/a1-requirements.md),
  [queries](docs/m2/a2-queries.md),
  [conceptual model](docs/m2/a3-conceptual-model.md),
  [Redis design](docs/m2/a4-redis-design.md)

## Project status

The data simulator, the Redis database design (M2)
and the Redis data layer are implemented.

The API query endpoints and the monitoring dashboard
are planned for subsequent development stages.
