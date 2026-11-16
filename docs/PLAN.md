# RedisPulse — M2 Work Plan 

**BDNR | FEUP | Two students**  
**Project:** RedisPulse — real-time monitoring of simulated LLM inference requests  
**Status:** Design-first M2, with optional early implementation work already started

## 0. Shared Project Specification (Both Students)

### Purpose and scope

RedisPulse is a lightweight Redis-backed monitoring application for **simulated** LLM inference workloads. It records inference events, supports model/version management and event investigation, and computes operational metrics for a dashboard and version comparisons.

The goal of M2 is to explain and justify the Redis data model, its access patterns, and expected trade-offs—not to develop an ML model or prove performance experimentally.

**Required functionality:** model/version CRUD (delete unused records, archive records with history), event ingestion, lookup by request ID, recent events, filtering by version/time/status/latency, keyword search over error messages, request count/error count/error rate/throughput/average latency, version comparisons, and retention.

**Excluded:** alerts, training pipelines, drift detection, authentication, distributed Redis, and production infrastructure.

### Conceptual entities

| Entity | Attributes |
|---|---|
| `Model` | `model_id`, `name`, `description`, `created_at`, `status` |
| `ModelVersion` | `version_id`, `model_id`, `version_label`, `created_at`, `status` |
| `InferenceEvent` | `request_id`, `model_id`, `version_id`, `timestamp`, `prediction`, `confidence` (optional), `latency_ms`, `status`, `error_type` (optional), `error_message` (optional) |

Relationships:

- **Model 1:N ModelVersion**
- **ModelVersion 1:N InferenceEvent**

Metrics are derived data, not separate conceptual entities.

Inference events are immutable. Model/version metadata can be updated. Records with inference history are archived rather than physically deleted.

**Implementation note:** Existing code uses `created_at_ms`, `timestamp_ms`, `input_tokens`, and `output_tokens` from the Azure-based simulator. Align the implemented event schema to the conceptual specification deliberately. Retain token data as optional simulator metadata if useful, but do not silently make token metrics an M2 requirement. Use consistent millisecond timestamps in Redis.

### Workload and deployment assumptions

- Microsoft Azure LLM Inference Trace 2023 supplies request-arrival patterns; predictions, errors, latency, and version assignments are simulated.
- Two models, two versions each.
- Normal load approximately **1 event/s**, short bursts of **10 events/s**.
- Potential later test volumes: **10,000** and **50,000** events.
- Event retention: **24 hours**.
- Metric retention: **7 days**.
- Dashboard windows: **5, 15, 60 minutes**.
- Event response limit: **100**.
- Initial generator supplies unique IDs per batch, but IDs may recur across runs. This must be addressed before relying on replay as idempotent ingestion.
- Single Redis 8 instance in Docker; target image `redis:8.10.3` (verify version and Redis Search support in the actual environment).

These are **design assumptions**, not measured performance results.

### Agreed Redis architecture

| Purpose | Structure/key pattern |
|---|---|
| Model metadata | Hash `model:<model_id>` |
| Version metadata | Hash `version:<version_id>` |
| Model → versions | Set `versions:<model_id>` |
| Recent events | Per-version Stream `events:<version_id>` |
| Lookup/indexed event | Hash `event:<request_id>` |
| Combined filtering/error search | Redis Search over event Hashes, index `idx:events` |
| Monitoring counters | Per-minute Hash `metrics:<version_id>:<minute>` (`total`, `errors`, `latency_sum_ms`) |
| Raw retention | 24-hour Hash TTL + time-based Stream trimming |
| Metrics retention | Seven-day minute-bucket TTL |
| Related event writes | Synchronous `MULTI/EXEC`, with duplicate-ID and failure limitations documented |

Stream entries and event Hashes intentionally duplicate information: Streams serve recent history, while Hashes serve request lookup and Redis Search.

Manual Sorted Set indexes and Redis Time Series are **alternatives to analyze**, not components of the chosen initial architecture.

No consumer group is required for synchronous ingestion.

### Shared query catalogue (fixed IDs)

| ID | Operation |
|---|---|
| Q1 | Create a model or retrieve metadata by model ID |
| Q2 | Create a version or list versions of a model |
| Q3 | Update model/version metadata; delete unused or archive records with history |
| Q4 | Ingest an inference event and update associated metrics |
| Q5 | Retrieve an inference event by request ID |
| Q6 | Retrieve the latest K events for a version, newest first |
| Q7 | Filter events by version, time interval, status, and optional latency threshold |
| Q8 | Search error messages by keyword, optionally filtered by version/time |
| Q9 | Compute request count, error rate, throughput, and average latency for a version/window |
| Q10 | Compare the same metrics for two versions in the same window |
| Q11 | Expire old events and metrics, including Stream retention |

Do not change these IDs, entities, requirements, or architecture independently. Agree on any changes together.

---

## 1. Student 1 — Application Design and Initial Redis Foundation

**Primary responsibility:** Specify what the application represents and how it is queried.

**Additional agreed responsibility:** Lead the initial Redis design documentation and implement the registry foundation, handing it off to Student 2 for integration and deeper analysis.

| Task | Work | Deliverable / location | Progress |
|---|---|---|---|
| A1 — Application specification | Workflows, scope, entities, retention, workload | `docs/m2/a1-requirements.md` | Revised draft prepared; verify saved version |
| A2 — Conceptual UML | Three entities, attributes, 1:N relationships, lifecycle | `docs/m2/a3-conceptual-model.md` + exported PNG/PDF | Revised draft; export/check diagram |
| A3 — Query catalogue | Q1–Q11: purpose, inputs, outputs, filters, ordering, frequency, limits; no Redis commands | `docs/m2/a2-queries.md` | Revised draft prepared; verify saved version |
| A4 — Requirements coverage | Matrix relating BDNR criteria to entities, queries, and design | `docs/m2/requirements-coverage.md` | Draft prepared; verify saved version |
| **B1 (taken over)** — Initial Redis data model | Select/document key families, Hashes, Sets, Streams, Search, metrics; analyze alternatives at design level | `docs/m2/a4-redis-design.md` | Draft prepared; review for implementation alignment |
| **B1 implementation foundation** | Implement/test model and version persistence: creation, retrieval, listing, update, archive, safe delete | `app/redis_registry.py` | Basic Q1–Q3 verified manually; concurrency/integration tests remain |
| **Next implementation step** | Experiment with and then implement per-version Streams and per-request event Hashes | Event storage module, integrated later | Not yet implemented |
| Slides | Application scope, conceptual UML, Q1–Q11, requirements coverage; briefly introduce Redis structures if useful | Student 1 slides | Pending |

### Student 1 handoff

Provide Student 2 with:

- Redis key naming conventions.
- Initial `a4-redis-design.md`.
- Registry implementation.
- Schema and retention caveats.
- Agreed event-store interfaces.

Manually verified registry CRUD does not yet constitute a complete or concurrency-tested backend.

---

## 2. Student 2 — Redis Architecture, Costs, and Integration

**Primary responsibility:** Own the remaining detailed Redis design work, refine the Student 1 foundation, and ensure all Q1–Q11 operations have correct access paths and realistic costs.

| Task | Work | Deliverable / location |
|---|---|---|
| B1 review/handoff | Review key patterns, Search schema, metadata relationships, and Student 1 registry decisions; identify missing constraints | Feedback/edits to `docs/m2/a4-redis-design.md` |
| **B2 — Ingestion, consistency, retention** | Define Stream + Hash ingestion, uniqueness/idempotency, `MULTI/EXEC`, usage-history markers, TTL, Stream trimming, Redis Search lifecycle, and read/ingestion diagram | Detailed architecture section in `docs/m2/a4-redis-design.md` or linked `docs/m2/redis-architecture.md` |
| **B3 — Query-to-Redis cost analysis** | For each Q1–Q11: key families, commands, logical reads/writes, records returned, asymptotic costs where defensible, index/memory impact, consistency caveats | `docs/m2/query-cost-matrix.md` or a dedicated section in A4 design |
| **B4 — Alternatives and justification** | Streams vs Hashes + Sorted Sets; manual indexes vs Redis Search; raw scans vs maintained buckets vs Redis Time Series | Analytical comparison in `docs/m2/a4-redis-design.md` (no benchmarks required) |
| Implementation integration (optional before final delivery) | Support event ingestion, Search, metrics, retention, API integration, and automated tests after registry handoff | Code/tests coordinated with Student 1 |
| Slides | Redis architecture, query mappings, costs, consistency/retention, alternatives | Student 2 slides |

### Analysis expectations

Use symbolic variables:

- **N** — Stored events.
- **K** — Returned events.
- **V** — Versions per model.
- **B** — Minute buckets per window.

Distinguish **Redis command count**, **records processed**, and **network round trips**.

For Redis Search, discuss selectivity and index overhead rather than claiming one universal complexity formula.

Include counter updates and index maintenance as ingestion costs.

Explain that `MULTI/EXEC` serializes queued mutations but does not roll back successful commands when another queued command fails at runtime.

A persistent *ever used* indication is necessary if deletion rules must survive event expiration.

Verify coordination between event ingestion, deletion, and archive transitions.

---

## 3. Independent Working and Handoff Rules

| Area | Lead |
|---|---|
| Application scope and conceptual UML | Student 1 |
| Query semantics and requirements coverage | Student 1 |
| Initial Redis data model proposal (`a4-redis-design.md`) | Student 1 |
| Initial registry code (Q1–Q3) | Student 1 |
| Detailed Redis ingestion/retention architecture | Student 2 |
| Q1–Q11 physical mapping and cost matrix | Student 2 |
| Analytical modeling comparisons | Student 2, using shared initial A4 |
| Event storage and subsequent backend integration | Coordinated; Student 1 begins event-store foundation, Student 2 reviews/integrates |
| Final cross-document review and presentation | Both |

### Integration checks

Check consistency between:

- UML attributes, Python schemas, and Redis fields.
- Q1–Q11 definitions and actual access paths.
- Timestamp naming, particularly `timestamp_ms`.
- Raw Hash TTL and Stream trimming.
- Metric bucket boundaries and seven-day retention.
- Archive/deletion rules and permanent event-usage markers.

Coordinate before changing the shared specification.

---

## 4. Revised Five-Day M2 Schedule

This is a **sequence of work**, not a requirement to restart from Day 1.

| Phase | Student 1 | Student 2 |
|---|---|---|
| Day 1 | Finalize A1 and UML; draft initial Redis key design | Review shared requirements and Redis feasibility |
| Day 2 | Finalize Q1–Q11; implement/test registry basics (Q1–Q3) | Specify ingestion transactions, Search indexing, and retention |
| Day 3 | Finish coverage matrix; begin Stream + Hash event foundation | Build Q1–Q11 command/cost matrix; joint query coverage review |
| Day 4 | Export UML and prepare application/query slides | Refine analytical alternatives; prepare Redis/cost slides |
| Day 5 | Review documentation and handoff assumptions | Review implementation/design consistency; combine/rehearse slides |

**Already accomplished:** Manual Redis Hash/Set experiments and basic Python registry operations for Q1–Q3.

These should be backed by automated tests when implementation work resumes.

---

## 5. M2 Submission vs. Early Implementation

### Required for M2

1. **Conceptual data model:** UML and lifecycle explanation — Student 1.
2. **Application queries:** Complete Q1–Q11 catalogue — Student 1.
3. **Proposed Redis design:** Chosen structures, indexing, aggregates, ingestion/retention architecture — Student 1 initial draft, Student 2 review/details.
4. **Modeling and costs:** Query mapping, read/write estimates, alternatives, trade-offs — Student 2.
5. **Cross-document coherence and slides:** Both.

### Optional early implementation (already underway)

- Redis model/version Hashes and Sets, registry CRUD methods, and manual verification.
- Next: Streams + event Hashes, followed by Redis Search, metrics, retention, API integration, and tests.

**Do not confuse implemented code with M2 completion.**

M2 is documentation/design-focused. Backend, frontend, replay, systematic performance benchmarking, and experimental comparison implementations can be completed in later milestones.

Existing Docker Compose and simulator components are reusable.

### Completion criteria

M2 is ready when the conceptual entities, Q1–Q11 semantics, Redis structures, and expected costs are mutually consistent and technically justified.

The team must distinguish between:

- **Designed**
- **Implemented**
- **Manually tested**
- **Experimentally measured**

These distinctions should remain clear throughout the final report and presentation.
