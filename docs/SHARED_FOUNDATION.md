
# RedisPulse — Shared Foundation

## 1. Purpose

This document describes the shared infrastructure
developed before the M2 database-design milestone.

The foundation provides a common data contract and
sample inference events for both project members.

It deliberately does not implement Redis persistence,
indexing, or metric aggregation. Those decisions belong
to the M2 design phase.

## 2. Data pipeline

```text
Azure LLM Inference Traces (CSV)
              |
              v
       Trace Loader
              |
              v
        TraceRequest
              |
              v
     Inference Simulator
              |
              v
        InferenceEvent
              |
              v
     Sample JSONL Export

Future:
InferenceEvent -> Redis -> API -> Dashboard
```

## 3. Source dataset

The project uses the Azure LLM Inference Trace 2023.

Two workloads are supported:

- Conversation
- Code generation

Each CSV row provides:

| Field | Meaning |
|---|---|
| TIMESTAMP | Request arrival timestamp |
| ContextTokens | Input token count |
| GeneratedTokens | Output token count |

The trace does not include actual model latency,
failure status, generated responses, or ground truth.

The original timestamps have no explicit timezone
information in the CSV.

## 4. Conceptual entities

### Model

Represents a monitored LLM.

Fields:
- model_id
- name
- description
- created_at_ms
- status

### ModelVersion

Represents a deployment version of an LLM.

Fields:
- version_id
- model_id
- version_label
- created_at_ms
- status

Each version belongs to one model.

### InferenceEvent

Represents one monitored inference request.

Fields:
- request_id
- model_id
- version_id
- timestamp_ms
- input_tokens
- output_tokens
- latency_ms
- status
- error_type
- error_message

The Pydantic schemas validate individual records.
They do not automatically enforce database-level
uniqueness or relationships between stored records.

## 5. Simulated deployments

| Model ID | Version ID | Label |
|---|---|---|
| llm-conversation | conv-v1 | v1.0 |
| llm-conversation | conv-v2 | v1.1 |
| llm-code | code-v1 | v1.0 |
| llm-code | code-v2 | v1.1 |

The configuration is stored in `config/models.json`.

## 6. Simulation assumptions

The generator reads Azure requests and assigns
alternating deployment versions.

Latency is simulated using:

latency_ms =
    (100 + 0.02 * input_tokens + 6 * output_tokens)
    * version_factor
    * random_variation

Version factors:
- v1.0: 1.0
- v1.1: 0.8

Random variation:
- Uniformly distributed between 0.9 and 1.1

Failure probabilities:
- v1.0: 8%
- v1.1: 2%

These parameters are illustrative assumptions,
not measured Azure service characteristics.

The generator shifts historical timestamps so that
the final request in a generated batch is near the
current time, preserving relative request gaps.

## 7. Data provenance

| Attribute | Source |
|---|---|
| Request timing pattern | Azure trace |
| Input tokens | Azure trace |
| Output tokens | Azure trace |
| Model/version assignment | Simulator |
| Latency | Simulator |
| Success/failure | Simulator |
| Error type | Simulator |
| Request ID | Generator |

Operational metrics will be calculated from the
resulting inference events.

They must not be presented as measured Azure
latency or reliability results.

## 8. Planned monitoring metrics

- Request count
- Throughput (requests per second)
- Average inference latency
- P95 inference latency
- Error count and error rate
- Input and output token consumption
- Token throughput
- Operational comparisons between model versions

Planned monitoring windows:
- 5 minutes
- 15 minutes
- 60 minutes

Accuracy, precision, recall, and other ML-quality
metrics are outside the initial scope because the
Azure trace does not provide predictions or labels.

## 9. Current implementation

Implemented:
- Docker Compose infrastructure
- Redis connectivity health check
- FastAPI skeleton
- Pydantic schemas
- Azure trace loader
- Simulated model registry
- Inference event generator
- JSONL sample export
- Automated generator tests

Not implemented:
- Redis event ingestion
- Redis storage structures and indexes
- Event search and filtering
- Aggregated monitoring metrics
- Model-version comparison API
- Continuous real-time replay
- Dashboard

## 10. Known limitations

1. Request IDs are unique within a generated batch,
   but are reused across generator runs.

2. Both workloads currently use the same default
   random seed, causing correlated random patterns.

3. Versions receive alternating requests, not
   identical workloads. Aggregate comparisons may
   therefore be influenced by token-count differences.

4. Generated timestamps depend on the execution time,
   so complete exports are not byte-for-byte
   reproducible across runs.

5. Failed requests retain the original Azure output
   token counts as a simplifying assumption.

6. The generator runs locally and is not yet part
   of the Dockerized API.

7. Redis is running but does not yet store events.

These limitations should be addressed or documented
during later implementation and evaluation.

## 11. M2 responsibilities

### Student A — Application and conceptual design

- Define functional requirements
- Define application access patterns
- Produce the conceptual UML model
- Build the query catalogue
- Ensure requirements are covered by the model
- Specify expected query inputs and outputs

### Student B — Redis database design

- Propose Redis data structures
- Define key organization and indexes
- Design aggregate metric storage
- Explain ingestion and query operations
- Estimate read/write costs
- Justify design choices and tradeoffs

Both students use the same schemas, simulated
deployments, and sample events.

## 12. Shared baseline

The sample file `data/sample/events.jsonl` contains:

- 100 conversation events
- 100 code-generation events
- 200 total inference events

It is intended for design examples, testing,
and early implementation.

The shared foundation should remain stable during
M2 unless both students agree on a schema change.
