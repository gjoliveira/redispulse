# RedisPulse — M2 Redis Data Design

## 1. Design Objectives

RedisPulse requires a Redis database capable of supporting the application operations defined in the M2 Query Catalogue (Q1–Q11), including:

- Model and version management.
- Continuous inference-event ingestion.
- Direct request-ID lookup.
- Chronological retrieval of recent events.
- Filtering by version, time, status, and latency.
- Full-text search over error messages.
- Monitoring metrics and model-version comparisons.
- Raw-event and historical-metric retention.

The objective is to select a Redis data model that supports these access patterns while balancing query efficiency, ingestion overhead, memory consumption, and implementation complexity.

Three modeling decisions are analyzed:

| Investigation | Alternatives considered | Selected approach |
|---|---|---|
| E1 — Event storage | Streams; Hashes + Sorted Sets; hybrid storage | Streams + event Hashes |
| E2 — Indexing | Manual indexes; Redis Search | Redis Search |
| E3 — Metrics | Raw-event scans; maintained aggregates; Redis Time Series | Maintained Hash aggregates |

The selections are based on analytical reasoning and the application's requirements. They are **proposed design choices, not experimentally validated performance results**.

## 2. Selected Redis Data Model

The selected architecture uses Redis Hashes, Sets, Streams, Redis Search, and time-bucketed metric Hashes.

### 2.1 Key Organization

| Redis key pattern | Type | Purpose |
|---|---|---|
| `model:<model_id>` | Hash | Model metadata |
| `version:<version_id>` | Hash | Version metadata and parent model ID |
| `versions:<model_id>` | Set | Version IDs belonging to a model |
| `events:<version_id>` | Stream | Ordered inference-event history for one version |
| `event:<request_id>` | Hash | Individual event details and direct lookup |
| `idx:events` | Search index | Filtering and full-text search over event Hashes |
| `metrics:<version_id>:<minute>` | Hash | Monitoring counters for one version and minute |

The event Stream and event Hash intentionally contain overlapping information.

The Stream supports recent-event retrieval, while the Hash supports direct lookup and indexed searches.

This duplication increases storage and write overhead but avoids forcing one data structure to serve incompatible access patterns.

### 2.2 Model and Version Metadata

Model metadata is stored in a Hash:

```redis
HSET model:llm-conversation name ConversationLLM description "Conversation model" created_at 1767225600000 status active
```

Version metadata is stored separately:

```redis
HSET version:conv-v1 model_id llm-conversation version_label v1.0 created_at 1767225600000 status active
```

The relationship between models and versions is represented using a Set:

```redis
SADD versions:llm-conversation conv-v1
```

Relevant operations include:

- Q1: `HSET`, `HGETALL`.
- Q2: `HSET`, `SADD`, `SMEMBERS`, `HGETALL`.
- Q3: `HSET`, `DEL`, `SREM`, and relationship checks.

Models and versions can be archived by updating their status.

Physical deletion is allowed only for unused records whose relationships permit deletion. Because raw events expire, the implementation must preserve enough lifecycle metadata to distinguish records that have never been used from records whose historical events have expired.

## 3. E1 — Event Storage

### 3.1 Selected Approach: Streams + Hashes

RedisPulse stores each accepted inference event in two representations.

**Per-version Stream**

Key:

`events:<version_id>`

Example:

```redis
XADD events:conv-v1 * request_id req-001 model_id llm-conversation version_id conv-v1 timestamp 1767225600000 prediction accepted latency_ms 381.84 status success
```

The Stream provides append-oriented ingestion and recent-event retrieval.

For Q6, the application retrieves the latest entries using:

```redis
XREVRANGE events:conv-v1 + - COUNT 20
```

**Per-request Hash**

Key:

`event:<request_id>`

Example:

```redis
HSET event:req-001 model_id llm-conversation version_id conv-v1 timestamp 1767225600000 prediction accepted latency_ms 381.84 status success
```

The Hash stores the complete event representation, including optional fields when present.

For Q5:

```redis
HGETALL event:req-001
```

The Stream and Hash are written as part of the same ingestion operation.

The initial simulator assigns current simulated ingestion timestamps and produces events in chronological order. Therefore, Stream insertion order is suitable for retrieving recent activity in the initial workload.

If arbitrary out-of-order event timestamps become a requirement, additional ordering logic or an event-time index may be necessary.

### 3.2 Alternatives Considered

**Candidate A — Streams only**

A Stream could store every event without creating individual event Hashes.

Advantages:

- Append-oriented ingestion.
- Natural ordering by Stream ID.
- Fewer event representations.

Limitations:

- Request-ID lookup requires additional mapping or scanning.
- Redis Search cannot directly index Stream entries as event documents.
- Combined filtering becomes more complex.

**Candidate B — Hashes + Sorted Sets**

Each event could be stored in a Hash, with Sorted Sets indexing timestamps.

Advantages:

- Direct request-ID lookup.
- Explicit chronological indexing.
- Compatible with Redis Search over Hashes.

Limitations:

- Additional index writes and maintenance.
- Sorted Set members require cleanup after Hash expiration.
- More application-managed indexing logic.

### 3.3 Comparison

| Property | Streams only | Hashes + Sorted Sets | Selected hybrid |
|---|---|---|---|
| Continuous ingestion | Good | Good | Good |
| Direct request lookup | Requires auxiliary mechanism | Direct Hash lookup | Direct Hash lookup |
| Latest events per version | Stream range | Sorted Set range | Stream range |
| Redis Search compatibility | Requires additional representation | Supported through Hashes | Supported through Hashes |
| Storage duplication | Low | Hash plus indexes | Stream plus Hash |
| Maintenance complexity | Lookup/index challenges | Index maintenance | Multiple representations |

**Decision:** Use per-version Streams together with per-request Hashes.

This supports Q4, Q5, and Q6 directly while providing a suitable representation for Q7 and Q8.

The main trade-off is additional storage and ingestion work.

## 4. E2 — Search and Indexing

Q7 requires combined attribute filtering, while Q8 requires keyword search over error messages.

### 4.1 Selected Approach: Redis Search

RedisPulse uses Redis Search to index event Hashes.

Proposed index:

`idx:events`

| Field | Index type | Purpose |
|---|---|---|
| `model_id` | TAG | Filter by model |
| `version_id` | TAG | Filter by version |
| `timestamp` | NUMERIC | Time-range filtering |
| `latency_ms` | NUMERIC | Latency thresholds |
| `status` | TAG | Success/error filtering |
| `error_message` | TEXT | Keyword search |

An illustrative index definition is:

```redis
FT.CREATE idx:events ON HASH PREFIX 1 event: SCHEMA model_id TAG version_id TAG timestamp NUMERIC SORTABLE latency_ms NUMERIC status TAG error_message TEXT
```

This requires Redis Search to be available in the selected Redis deployment. Availability and command compatibility must be verified with the planned Redis 8.10.3 Docker environment.

### 4.2 Attribute Filtering — Q7

Example: find failed events for version `conv-v1` with latency of at least 1000 ms.

```redis
FT.SEARCH idx:events "@version_id:{conv-v1} @status:{error} @latency_ms:[1000 +inf]" SORTBY timestamp DESC LIMIT 0 100
```

Time-range constraints can be added using the indexed timestamp field.

The application limits results to a maximum of 100 events per request.

### 4.3 Full-Text Search — Q8

Example: search error messages containing the word `timeout`.

```redis
FT.SEARCH idx:events "@status:{error} @error_message:timeout" SORTBY timestamp DESC LIMIT 0 100
```

The search can also include version and time restrictions.

Keyword matching follows Redis Search's configured text-analysis semantics rather than an arbitrary substring search.

### 4.4 Alternative: Manual Indexes

An alternative is to maintain Sets and Sorted Sets for individual attributes.

Possible indexes include:

- `idx:version:<version_id>`
- `idx:status:<status>`
- `idx:latency`
- `idx:error_word:<term>`

This approach offers explicit control but requires additional ingestion updates, index intersections, text tokenization, and expiration cleanup.

### 4.5 Comparison

| Property | Manual indexes | Redis Search |
|---|---|---|
| Attribute filtering | Application-managed | Indexed queries |
| Combined predicates | Multiple index operations | Single search expression |
| Error-message search | Custom implementation | Built-in full-text search |
| Index maintenance | Explicit writes and cleanup | Managed by search index |
| Memory overhead | Depends on maintained indexes | Depends on index schema |
| Application complexity | Higher | Lower |

**Decision:** Use Redis Search.

This reduces application-side query logic and supports Q7 and Q8 without maintaining several custom indexes.

The cost is additional index memory and maintenance overhead during event ingestion.

## 5. E3 — Monitoring Metrics

Q9 and Q10 require operational metrics over 5-, 15-, and 60-minute windows.

Required metrics are:

- Request count.
- Error count.
- Error rate.
- Throughput.
- Average latency.

### 5.1 Selected Approach: Maintained Aggregates

RedisPulse maintains one metrics Hash per model version and minute.

Key pattern:

`metrics:<version_id>:<minute>`

Example:

`metrics:conv-v1:20260101T0000`

Fields:

| Field | Meaning |
|---|---|
| `total` | Number of requests |
| `errors` | Number of failed requests |
| `latency_sum_ms` | Sum of inference latencies |

During ingestion, the relevant counters are updated:

```redis
HINCRBY metrics:conv-v1:20260101T0000 total 1
HINCRBYFLOAT metrics:conv-v1:20260101T0000 latency_sum_ms 381.84
```

For failed requests, the application also increments:

```redis
HINCRBY metrics:conv-v1:20260101T0000 errors 1
```

These commands are illustrative; the actual minute key is calculated from the event timestamp.

### 5.2 Derived Metrics

For a selected window:

**Request count**

`request_count = sum(total)`

**Error count**

`error_count = sum(errors)`

**Error rate**

`error_rate = error_count / request_count`

**Average latency**

`average_latency = sum(latency_sum_ms) / request_count`

**Throughput**

`throughput = request_count / window_duration_seconds`

For windows without requests, counts and rates are reported as zero, while average latency is unavailable.

Q10 calculates the same metrics for two versions using identical time boundaries.

The initial design uses minute-aligned monitoring windows. Exact arbitrary-second windows would require additional handling of partial-minute buckets.

### 5.3 Alternative A — Raw-Event Scans

Metrics could be calculated by retrieving all events within the requested window.

Advantages:

- No additional aggregate storage.
- No counter updates during ingestion.

Limitations:

- Repeated dashboard queries must process raw events.
- Query work increases with event volume.
- Seven-day metrics cannot be reconstructed after raw events expire at 24 hours.

Raw scans are therefore useful as a conceptual baseline but do not independently satisfy the retention requirement.

### 5.4 Alternative B — Redis Time Series

Redis Time Series could represent request counts, error counts, and latency sums as time-oriented series.

Advantages:

- Specialized time-series operations.
- Time-range aggregation capabilities.

Limitations:

- Additional series configuration.
- Multiple series may be required.
- Compatibility and deployment requirements must be considered.

For the initial workload, RedisPulse does not require this additional specialization.

### 5.5 Comparison

| Property | Raw scans | Maintained Hash aggregates | Redis Time Series |
|---|---|---|---|
| Ingestion overhead | Low | Counter updates | Series updates |
| Dashboard query work | Depends on matching events | Depends on minute buckets | Depends on series query |
| Seven-day metrics after raw expiration | No | Yes | Yes, with retention |
| Additional storage | None for metrics | Small metric Hashes | Metric series |
| Main trade-off | Read cost | Write cost and bucket precision | Configuration complexity |

**Decision:** Use maintained per-minute Hash aggregates.

This supports Q9 and Q10 while preserving historical metrics independently of raw events.

## 6. Ingestion, Consistency, and Retention

### 6.1 Ingestion Workflow — Q4

For each accepted event, the application:

1. Validates the event and its model-version relationship.
2. Determines the relevant version Stream and minute bucket.
3. Writes the event to the Stream.
4. Writes the corresponding event Hash.
5. Sets the raw-event expiration.
6. Updates the metrics counters.
7. Ensures the metrics bucket has the required retention policy.

The related Redis writes are grouped using `MULTI/EXEC`.

This prevents other clients from observing a partially executed sequence of successful transactional writes.

However, `MULTI/EXEC` does not automatically prevent duplicate request IDs or roll back commands that fail at execution time. The simulator is expected to generate unique request IDs; stronger idempotency guarantees would require additional validation or conditional-write logic.

No consumer group is required because the initial application reads recent history directly and does not use asynchronous Stream consumers.

### 6.2 Raw-Event Retention — Q11

Raw events are retained for 24 hours.

Event Hashes receive a TTL:

```redis
EXPIRE event:req-001 86400
```

Per-version Streams are maintained through time-based trimming.

For Streams using automatically generated IDs based on ingestion time, old entries can be removed using an appropriate `XTRIM MINID` threshold.

The threshold must correspond to the configured 24-hour retention boundary.

Redis Search indexes event Hashes; expired Hashes must no longer appear as valid event results.

### 6.3 Metrics Retention — Q11

Metrics buckets are retained for seven days.

Each bucket receives an expiration policy corresponding to its retention period.

This allows historical summaries to remain available after raw inference events expire.

Because metrics are grouped by minute, retention boundaries have minute-level granularity.

### 6.4 Consistency Considerations

The design must account for:

- Coordinating Stream, Hash, and metrics updates.
- Avoiding duplicate ingestion.
- Preventing metrics from being counted twice.
- Ensuring expired events are not returned by queries.
- Preserving model/version lifecycle information after event expiration.
- Maintaining consistent window definitions for version comparisons.

These requirements will guide the implementation.

## 7. Preliminary Operation Costs

The following estimates describe the proposed design analytically. They are not benchmark results.

Let:

- **K** = number of events returned.
- **B** = number of minute buckets in a metrics query.
- **R** = number of matching search results.
- **V** = number of versions belonging to a model.

| Query | Main Redis operations | Expected work |
|---|---|---|
| Q1 — Model create/retrieve | `HSET`, `HGETALL` | Direct key access |
| Q2 — Version create/list | `HSET`, `SADD`, `SMEMBERS`, `HGETALL` | Depends on V |
| Q3 — Metadata maintenance | `HSET`, `DEL`, `SREM`, relationship checks | Depends on affected relationships |
| Q4 — Ingest event | `XADD`, `HSET`, `EXPIRE`, counter updates | Fixed number of writes per event, plus indexing |
| Q5 — Event lookup | `HGETALL` | Direct key access |
| Q6 — Latest K events | `XREVRANGE` | Depends on K |
| Q7 — Event filtering | `FT.SEARCH` | Depends on index selectivity and R |
| Q8 — Error search | `FT.SEARCH` | Depends on text matches and R |
| Q9 — Metrics | Read relevant metric Hashes | Depends on B |
| Q10 — Version comparison | Read buckets for two versions | Approximately twice Q9's bucket work |
| Q11 — Retention | Expiration and Stream trimming | Depends on expired data |

A direct Hash lookup is expected to have approximately O(1) average key-access complexity.

Retrieving K Stream entries requires work proportional to the returned entries, with additional navigation costs.

Search performance depends on index structure, predicate selectivity, sorting, and result size.

Metrics queries examine a bounded number of minute buckets rather than scanning all raw events in the monitoring window.

These are qualitative expectations; actual latency, throughput, and memory consumption require experimental measurement.

## 8. Design Trade-offs

### 8.1 Storage Duplication

Using both Streams and Hashes duplicates event information.

**Benefit:** Efficient support for recent history, direct lookup, and indexed filtering.

**Cost:** Additional memory and writes.

This trade-off is accepted because RedisPulse has several distinct event-access patterns.

### 8.2 Redis Search Overhead

Redis Search simplifies filtering and keyword search.

**Benefit:** Less custom indexing and query logic.

**Cost:** Additional index memory and maintenance.

The selected workload prioritizes expressive monitoring queries over minimizing every ingestion write.

### 8.3 Maintained Metrics

Per-minute aggregates reduce repeated raw-event processing.

**Benefit:** Efficient monitoring queries and seven-day metric retention.

**Cost:** Additional counter updates and minute-level precision.

This trade-off is appropriate for dashboard windows of 5, 15, and 60 minutes.

### 8.4 Consistency Versus Simplicity

Synchronous transactional writes keep related event updates together.

**Benefit:** Simpler consistency model without asynchronous consumers.

**Cost:** More work on the ingestion path.

Given the initial workload of approximately one event per second with bursts of ten events per second, this is a reasonable design choice to evaluate during later implementation.

## 9. Final Design Decisions

| Decision | Selected approach | Justification |
|---|---|---|
| Model metadata | Redis Hashes | Direct access and simple updates |
| Model-version associations | Redis Sets | Efficient membership and listing |
| Event history | Per-version Streams | Append-oriented ingestion and recent-event retrieval |
| Event lookup | Per-request Hashes | Direct request-ID lookup |
| Filtering and text search | Redis Search | Combined predicates and keyword search |
| Monitoring metrics | Per-minute Hash aggregates | Efficient summaries and independent retention |
| Ingestion consistency | Synchronous `MULTI/EXEC` | Coordinate related Redis writes |
| Raw-event retention | Hash TTL and Stream trimming | Bounded 24-hour history |
| Metrics retention | Seven-day TTL | Preserve historical summaries |
| Redis Time Series | Not selected initially | Additional complexity is unnecessary for the initial requirements |

The selected architecture is a **hybrid Redis data model** designed around RedisPulse's required access patterns.

It is not claimed to be universally optimal. Its advantages and limitations are justified analytically, and its actual performance can be evaluated in a later milestone.

## 10. Conclusion

RedisPulse adopts a hybrid architecture combining:

- Hashes and Sets for model management.
- Per-version Streams for recent event history.
- Per-request Hashes for direct event access.
- Redis Search for attribute filtering and error investigation.
- Per-minute Hash aggregates for monitoring metrics.

The design supports the Q1–Q11 query catalogue while explicitly accounting for storage duplication, indexing overhead, ingestion consistency, and data retention.

M2 establishes the architecture and its rationale. Implementation and benchmarking can subsequently test the assumptions made in this design.
