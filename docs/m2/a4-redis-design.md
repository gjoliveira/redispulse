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

The selections are based on analytical reasoning and the application's requirements. They are **design choices supported by functional implementation and testing, not experimentally validated performance results**.

## 2. Selected Redis Data Model

The selected architecture uses Redis Hashes, Sets, Streams, Redis Search, time-bucketed metric Hashes, and persistent String markers for lifecycle and duplicate protection.

### 2.1 Key Organization

| Redis key pattern | Type | Purpose |
|---|---|---|
| `model:<model_id>` | Hash | Model metadata |
| `version:<version_id>` | Hash | Version metadata and parent model ID |
| `versions:<model_id>` | Set | Version IDs belonging to a model |
| `events:<version_id>` | Stream | Ordered inference-event history for one version |
| `event:<request_id>` | Hash | Individual event details and direct lookup |
| `idx:events` | Search index | Filtering and full-text search over event Hashes |
| `metrics:<version_id>:<minute_ms>` | Hash | Monitoring counters for one version and minute |
| `request-used:<request_id>` | String | Permanent duplicate-request protection |
| `model-used:<model_id>` | String | Prevent deletion of models with inference history |
| `version-used:<version_id>` | String | Prevent deletion of versions with inference history |

The event Stream and event Hash intentionally contain overlapping information.

The Stream supports recent-event retrieval, while the Hash supports direct lookup and indexed searches.

This duplication increases storage and write overhead but avoids forcing one data structure to serve incompatible access patterns.

Persistent usage markers provide additional consistency guarantees. In particular, they allow the application to preserve information about previously used request IDs, models, and versions after raw inference events expire.

### 2.2 Model and Version Metadata

Model metadata is stored in a Hash:

```redis
HSET model:llm-conversation name ConversationLLM description "Conversation model" created_at_ms 1767225600000 status active
```

Version metadata is stored separately:

```redis
HSET version:conv-v1 model_id llm-conversation version_label v1.0 created_at_ms 1767225600000 status active
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

Physical deletion is allowed only for unused records whose relationships permit deletion. A model cannot be deleted while it has registered versions or inference history. Similarly, a version cannot be deleted after it has been used for inference.

Because raw events expire, permanent `model-used` and `version-used` markers preserve this lifecycle information independently of event retention.

Model and version creation, updating, archiving, and deletion use Redis optimistic transactions where necessary to prevent inconsistent state under concurrent operations.

## 3. E1 — Event Storage

### 3.1 Selected Approach: Streams + Hashes

RedisPulse stores each accepted inference event in two representations.

**Per-version Stream**

Key:

`events:<version_id>`

Example:

```redis
XADD events:conv-v1 * request_id req-001 model_id llm-conversation version_id conv-v1 timestamp_ms 1767225600000 input_tokens 100 output_tokens 50 latency_ms 381.84 status success
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
HSET event:req-001 request_id req-001 model_id llm-conversation version_id conv-v1 timestamp_ms 1767225600000 input_tokens 100 output_tokens 50 latency_ms 381.84 status success
```

The Hash stores the complete event representation, including optional fields when present.

The current implementation records token usage, latency, status, and optional error information. The `prediction` and `confidence` fields considered in the initial conceptual model are not part of the implemented event schema.

For Q5:

```redis
HGETALL event:req-001
```

The Stream and Hash are written as part of the same transactional ingestion operation.

The initial simulator generates inference events with timestamps close to the current time and produces events in chronological order. Therefore, Stream insertion order is suitable for retrieving recent activity in the initial workload.

However, Stream IDs reflect insertion order rather than the event's original `timestamp_ms`. Consequently, a late-arriving event appears among the most recently ingested events even if its event timestamp is older.

If retrieval ordered strictly by event time becomes a requirement, additional ordering logic or an event-time index may be necessary.

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

Index name:

`idx:events`

| Field | Index type | Purpose |
|---|---|---|
| `model_id` | TAG | Filter by model |
| `version_id` | TAG | Filter by version |
| `timestamp_ms` | NUMERIC | Time-range filtering and sorting |
| `latency_ms` | NUMERIC | Latency thresholds |
| `status` | TAG | Success/error filtering |
| `error_message` | TEXT | Keyword search |

The index definition is:

```redis
FT.CREATE idx:events ON HASH PREFIX 1 event: SCHEMA model_id TAG version_id TAG timestamp_ms NUMERIC SORTABLE latency_ms NUMERIC status TAG error_message TEXT
```

The application checks whether the index already exists before attempting to create it.

This requires Redis Search to be available in the selected Redis deployment. The project uses Redis 8 with Redis Search support through its Docker environment.

### 4.2 Attribute Filtering — Q7

Example: find failed events for version `conv-v1` with latency of at least 1000 ms.

```redis
FT.SEARCH idx:events "@version_id:{conv\-v1} @status:{error} @latency_ms:[1000 +inf]" SORTBY timestamp_ms DESC LIMIT 0 100 DIALECT 2
```

Time-range constraints can be added using the indexed `timestamp_ms` field.

The application escapes special characters in TAG values, including hyphens in version identifiers, when constructing search queries.

The application limits results to a maximum of 100 events per request.

Search results identify matching event Hashes, which are then retrieved and validated as inference-event records.

### 4.3 Full-Text Search — Q8

Example: search error messages containing the word `timeout`.

```redis
FT.SEARCH idx:events "@status:{error} @error_message:timeout" SORTBY timestamp_ms DESC LIMIT 0 100 DIALECT 2
```

The search can also include version and time restrictions.

Keyword matching follows Redis Search's configured text-analysis semantics rather than arbitrary substring search.

The implemented application validates search terms before constructing the query.

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

`metrics:<version_id>:<minute_ms>`

The minute identifier is a Unix timestamp in milliseconds, rounded down to the beginning of the minute.

For example, the minute beginning at `2026-01-01 00:00:00 UTC` is represented by `1767225600000`.

Example key:

`metrics:conv-v1:1767225600000`

Fields:

| Field | Meaning |
|---|---|
| `total` | Number of requests |
| `errors` | Number of failed requests |
| `latency_sum_ms` | Sum of inference latencies |

During ingestion, the relevant counters are updated:

```redis
HINCRBY metrics:conv-v1:1767225600000 total 1
HINCRBYFLOAT metrics:conv-v1:1767225600000 latency_sum_ms 381.84
```

For failed requests, the application also increments:

```redis
HINCRBY metrics:conv-v1:1767225600000 errors 1
```

These commands are illustrative. The actual minute key is calculated from each event's `timestamp_ms`:

```python
minute_ms = (event.timestamp_ms // 60_000) * 60_000
```

This means that metrics are grouped according to **event time**, not the time at which the event is received by RedisPulse.

Late-arriving events that satisfy the ingestion timestamp policy therefore contribute to their corresponding historical minute bucket.

All metric updates are performed within the event ingestion transaction.

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

The application reads the relevant minute Hashes and combines their stored counters rather than scanning individual inference events.

Q10 calculates the same metrics for two versions using identical time boundaries.

The initial implementation uses minute-aligned monitoring windows. For example, a five-minute query includes the current minute bucket and the preceding four minute buckets.

Consequently, these windows are approximate relative to the exact current second. Exact arbitrary-second windows would require additional handling of partial-minute buckets.

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

For each inference event, RedisPulse:

1. Validates the event timestamp and its model-version relationship.
2. Verifies that the model and version exist and are active.
3. Checks whether the request ID has already been used.
4. Determines the relevant version Stream and metrics minute bucket.
5. Appends the event to the Stream and trims outdated Stream entries.
6. Stores the corresponding event Hash with a 24-hour TTL.
7. Creates permanent usage markers for the request, model, and version.
8. Updates the metrics counters and applies the seven-day metrics retention policy.

Related Redis writes are grouped using `MULTI/EXEC`. The implementation also uses `WATCH` to detect concurrent modifications of relevant records and retry transactions when necessary.

This prevents conflicting operations from silently producing inconsistent database state, such as an event referencing a version deleted during ingestion.

The transaction coordinates the Redis writes, although Redis `MULTI/EXEC` does not provide rollback of commands that fail during execution. Input validation and the selected Redis commands therefore remain important.

**Duplicate protection**

Duplicate ingestion is prevented using a permanent marker:

`request-used:<request_id>`

When an event is accepted, the marker is created in the same transaction as the event records and metrics updates.

Subsequent attempts to ingest the same request ID are rejected.

Unlike the event Hash, this marker does not expire. Therefore, duplicate protection continues to work after the original event has been removed by the retention policy.

Permanent markers introduce a small but continuously growing storage overhead. This trade-off is accepted for the initial proof of concept.

The simulator generates unique request IDs, but the database layer does not rely solely on this assumption.

No consumer group is required because the application reads recent Stream history directly and does not use asynchronous Stream consumers.

### 6.2 Raw-Event Retention — Q11

Raw event data is retained for 24 hours after ingestion, subject to the Stream cleanup behavior described below.

**Event Hashes**

Individual event Hashes receive a TTL of 86,400 seconds:

```redis
EXPIRE event:req-001 86400
```

This allows Redis to remove the Hash automatically after 24 hours.

**Per-version Streams**

Streams are maintained through `XTRIM MINID`, which removes entries whose Stream IDs are older than the retention threshold.

Since automatically generated Stream IDs are based on Redis server time, the implementation uses Redis `TIME` to calculate the cutoff.

This avoids inconsistencies caused by differences between the application's clock and the Redis server's clock.

Stream trimming occurs during event ingestion and can also be executed explicitly.

Consequently, a Stream that receives no further events is not automatically trimmed merely because 24 hours have elapsed. Its outdated entries remain until another ingestion or an explicit cleanup operation triggers trimming.

This is a limitation of the ingestion-triggered retention strategy.

**Relationship with event timestamps**

Raw-event retention is based on ingestion time, whereas monitoring metrics are grouped by the event's own timestamp.

An event arriving late may therefore remain stored for more than 24 hours after its original event timestamp.

For example, an event generated 23 hours before ingestion may remain in Redis for approximately another 24 hours.

This distinction follows from the different purposes of the two timestamps:

- Event time determines the monitoring minute bucket.
- Ingestion time determines raw-data expiration and Stream ordering.

Redis Search indexes the event Hashes, so expired Hashes are no longer available as valid indexed event records.

### 6.3 Metrics Retention and Event-Time Validation — Q11

Metrics buckets are retained for approximately seven days after their corresponding minute.

Each metrics Hash receives an expiration timestamp based on the beginning of its minute bucket, with an additional 60-second allowance.

The retention timestamp is calculated as:

```python
expiration_s = minute_ms // 1000 + 7 * 86400 + 60
```

This allows historical summaries to remain available after raw inference events expire.

**Event-time validation**

To prevent outdated or excessively future-dated events from creating inappropriate monitoring buckets, RedisPulse accepts only events satisfying:

```text
now - 24 hours <= timestamp_ms <= now + 60 seconds
```

Events outside this interval are rejected before Redis records are created.

The 24-hour backward limit restricts how late an event can arrive. It also prevents very old events from recreating metrics buckets that have already expired.

The 60-second future allowance accommodates small clock differences between event producers and the application.

An accepted event with a slightly future timestamp is assigned to its corresponding future minute bucket. It becomes visible in monitoring windows when that minute is included.

**Metric aggregation**

Accepted events contribute to the bucket corresponding to their own `timestamp_ms`, regardless of their actual ingestion minute.

This preserves event-time semantics while retaining the performance advantages of maintained aggregates.

Because metrics are grouped by minute, retention boundaries and monitoring calculations have minute-level granularity.

### 6.4 Consistency Considerations

RedisPulse uses optimistic transactions (`WATCH` with `MULTI/EXEC`) for operations that require consistency across multiple Redis records.

The implementation addresses the following requirements:

- **Atomic ingestion:** Related event writes, duplicate markers, and metrics updates are executed within a Redis transaction.
- **Duplicate prevention:** Permanent request markers prevent repeated ingestion, including after event expiration.
- **Referential integrity:** Model and version relationships are validated before event ingestion.
- **Lifecycle protection:** Models and versions with inference history cannot be physically deleted, even after raw events expire.
- **Concurrent modifications:** Transactions detect conflicting changes and retry when necessary.
- **Safe metadata updates:** Model and version updates or archiving cannot recreate partial records after concurrent deletion.
- **Consistent monitoring:** Metrics use event-time minute buckets, and version comparisons share the same time boundary.

**Validation**

The implemented Redis layer has been tested using an automated pytest suite.

The tests cover model and version management, event ingestion, Redis Search, monitoring metrics, retention policies, and selected concurrency scenarios.

The simplified suite contains 38 passing tests, including simulator tests, executed against an isolated Redis instance.

These results provide functional validation of the implementation but do not constitute a comprehensive performance evaluation or formal proof of concurrent correctness.

## 7. Preliminary Operation Costs

The following estimates describe the selected design analytically. They are not benchmark results.

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
| Q4 — Ingest event | `WATCH`, `MULTI/EXEC`, `XADD`, `XTRIM`, `HSET`, `EXPIRE`, `SET`, counter updates | Fixed number of writes per event, plus indexing and trimming |
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

Event ingestion performs a bounded number of counter and record writes, although Redis Search indexing, transaction retries, and Stream trimming introduce additional costs that depend on database state and workload.

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

**Benefit:** A consistent ingestion workflow without asynchronous consumers, with protection against selected concurrent modifications and duplicate requests.

**Cost:** Additional commands, transaction retries, and persistent usage markers.

The use of `WATCH` and `MULTI/EXEC` increases implementation complexity compared with independent Redis writes, but provides stronger correctness guarantees for concurrent operations.

Given the initial workload of approximately one event per second with bursts of ten events per second, this is a reasonable design choice to evaluate during later performance testing.

### 8.5 Retention and Event-Time Semantics

Raw-event retention and monitoring aggregation use different time references.

**Benefit:** Raw data expires relative to ingestion, while monitoring metrics reflect when inference events actually occurred.

**Cost:** Late-arriving events may remain stored longer than 24 hours after their original timestamp, and Stream insertion order does not necessarily match event-time order.

The timestamp acceptance window limits excessively late or future-dated events, while Redis-server-based Stream trimming avoids relying on synchronized application and Redis clocks.

### 8.6 Persistent Usage Markers

Permanent usage markers preserve lifecycle and duplicate information after raw-event expiration.

**Benefit:** Prevents repeated request IDs and protects previously used models and versions against deletion.

**Cost:** Marker storage grows over time because these keys do not expire.

For the initial proof of concept, this approach favors straightforward consistency guarantees over implementing a more complex marker-retention policy.

## 9. Final Design Decisions

| Decision | Selected approach | Justification |
|---|---|---|
| Model metadata | Redis Hashes | Direct access and simple updates |
| Model-version associations | Redis Sets | Efficient membership and listing |
| Event history | Per-version Streams | Append-oriented ingestion and recent-event retrieval |
| Event lookup | Per-request Hashes | Direct request-ID lookup |
| Filtering and text search | Redis Search | Combined predicates and keyword search |
| Monitoring metrics | Per-minute Hash aggregates | Efficient summaries and independent retention |
| Metric time reference | Event `timestamp_ms` | Aggregate events according to occurrence time |
| Ingestion consistency | `WATCH` + synchronous `MULTI/EXEC` | Coordinate related Redis writes and detect conflicts |
| Duplicate protection | Permanent request usage markers | Prevent re-ingestion after raw-event expiration |
| Lifecycle protection | Permanent model/version usage markers | Preserve inference history information |
| Raw-event retention | Hash TTL and Stream trimming | Maintain approximately 24-hour ingestion history |
| Stream retention clock | Redis server time | Align trimming cutoff with Stream IDs |
| Metrics retention | Seven-day bucket expiration | Preserve historical summaries |
| Event-time validation | 24-hour backward and 60-second forward window | Reject outdated or excessively future-dated events |
| Redis Time Series | Not selected initially | Additional complexity is unnecessary for the initial requirements |

The selected architecture is a **hybrid Redis data model** designed around RedisPulse's required access patterns.

It is not claimed to be universally optimal. Its advantages and limitations are justified analytically, and its functional behavior has been evaluated through automated testing.

Performance benchmarking remains necessary to assess actual latency, throughput, and memory consumption.

## 10. Conclusion

RedisPulse adopts a hybrid architecture combining:

- Hashes and Sets for model management.
- Per-version Streams for recent event history.
- Per-request Hashes for direct event access.
- Redis Search for attribute filtering and error investigation.
- Per-minute Hash aggregates for monitoring metrics.
- Permanent usage markers for duplicate prevention and lifecycle protection.
- Optimistic Redis transactions for consistency under concurrent operations.

The design supports the Q1–Q11 Query Catalogue while explicitly accounting for storage duplication, indexing overhead, ingestion consistency, event-time semantics, and data retention.

The implementation uses event-time aggregation, Redis-server-based Stream trimming, and transactional validation to address additional consistency requirements identified during development.

M2 establishes the architecture and its rationale. The implemented Redis layer has subsequently undergone functional testing, while its performance characteristics can be evaluated in a later milestone.