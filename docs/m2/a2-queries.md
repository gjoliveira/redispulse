# RedisPulse — M2 Query Catalogue

## 1. Purpose

This document defines the application operations and access patterns required by RedisPulse.

Each query specifies its purpose, inputs, conditions, output, ordering, read/write classification, expected frequency, and result size.

Queries are described independently of Redis structures and commands. The physical database design and operation-cost analysis are Student 2's responsibilities.

All frequencies and result sizes are design assumptions, not measured results.

## 2. Query Catalogue

### Q1 — Create or Retrieve a Model

**Purpose:** Register a new model or retrieve the metadata of an existing model.

**Inputs:**
- Operation: create or retrieve.
- For creation: model ID, name, description, and initial metadata.
- For retrieval: model ID.

**Conditions:**
- Model IDs must be unique.
- Retrieval requires an existing model.

**Output:**
- Model ID, name, description, creation timestamp, and status.
- Creation confirmation or not-found/error result, as applicable.

**Ordering and limits:** Not applicable; one model per operation.

**Type:** Write (create) or read (retrieve).

**Expected frequency:** Low.

**Expected result size:** One model.

### Q2 — Create or List Model Versions

**Purpose:** Register a version belonging to a model or list all versions of a model.

**Inputs:**
- Operation: create or list.
- Model ID.
- For creation: version ID, version label, and initial metadata.

**Conditions:**
- The parent model must exist.
- Version IDs must be unique.
- Every version belongs to exactly one model.

**Output:**
- For creation: the created version or confirmation.
- For listing: version ID, model ID, label, creation timestamp, and status for each version.

**Ordering and limits:**
- Version lists ordered by creation timestamp, newest first.
- No fixed page limit is required for the initial configuration.

**Type:** Write (create) or read (list).

**Expected frequency:** Low.

**Expected result size:** One version for creation; approximately 2–10 versions for listing.

### Q3 — Update, Delete, or Archive Metadata

**Purpose:** Maintain model and version metadata while respecting their lifecycle rules.

**Inputs:**
- Entity type: model or version.
- Model ID or version ID.
- Operation: update, delete, or archive.
- Updated metadata, when applicable.

**Conditions:**
- Only existing entities can be modified.
- Inference events are immutable.
- Models and versions with inference history must be archived instead of physically deleted.
- Physical deletion is permitted only when the record is unused and its relationships allow deletion.

**Output:**
- Updated model/version metadata or operation confirmation.
- Validation or not-found error when applicable.

**Ordering and limits:** Not applicable.

**Type:** Write.

**Expected frequency:** Low.

**Expected result size:** One entity or operation result.

### Q4 — Ingest an Inference Event

**Purpose:** Receive an inference event and update the monitoring metrics associated with its model version.

**Inputs:**
- Unique request ID.
- Model ID and version ID.
- Inference timestamp.
- Simulated prediction and optional confidence.
- Latency.
- Success/error status.
- Optional error type and error message.

**Conditions:**
- The referenced model and version must exist.
- The version must belong to the specified model.
- The event must satisfy the defined schema.
- The initial workload generator produces unique request IDs.
- Accepted inference events are immutable.

**Output:**
- Request ID and ingestion confirmation.
- Validation or ingestion error when applicable.

**Ordering and limits:** One event per operation.

**Type:** Write.

**Expected frequency:** Very high relative to other operations: approximately 1 event/second normally and 10 events/second during bursts.

**Expected result size:** One confirmation.

### Q5 — Retrieve an Inference Event by Request ID

**Purpose:** Inspect the details of one inference request.

**Inputs:**
- Request ID.

**Conditions:**
- Match the exact request ID.
- The event must still be within its retention period.

**Output:**
- Complete stored inference-event details, including model/version identifiers, timestamp, prediction fields, latency, status, and error information.

**Ordering and limits:** Not applicable; at most one event.

**Type:** Read.

**Expected frequency:** Medium.

**Expected result size:** Zero or one event.

### Q6 — Retrieve the Latest K Events for a Version

**Purpose:** Display recent inference activity for a selected model version.

**Inputs:**
- Version ID.
- Result limit K.

**Conditions:**
- Only events belonging to the requested version.
- Only retained events.
- K must be between 1 and 100.

**Output:**
- Event details needed for recent-event inspection.

**Ordering and limits:**
- Newest first by inference timestamp.
- Request ID used as a deterministic tie-breaker.
- Maximum 100 events.

**Type:** Read.

**Expected frequency:** High.

**Expected result size:** Up to 100 events.

### Q7 — Filter Inference Events

**Purpose:** Find inference events matching operational filters, including failures and high-latency requests.

**Inputs:**
- Version ID.
- Start timestamp and end timestamp.
- Optional status filter.
- Optional minimum latency threshold.
- Result limit or page size.

**Conditions:**
- Events must belong to the selected version.
- Event timestamp must fall within the requested interval.
- Apply the status filter when provided.
- Apply the minimum latency threshold when provided.
- Only retained events are eligible.

**Output:**
- Matching inference events, including request ID, timestamp, version, latency, status, and available error information.

**Ordering and limits:**
- Newest first by inference timestamp.
- Request ID used to break timestamp ties.
- Maximum 100 events per page/request.

**Type:** Read.

**Expected frequency:** Medium.

**Expected result size:** Up to 100 events per page.

### Q8 — Search Error Messages

**Purpose:** Find inference failures whose error messages contain a specified keyword.

**Inputs:**
- Search keyword.
- Optional version ID.
- Optional start and end timestamps.
- Result limit or page size.

**Conditions:**
- Only failed events with an error message.
- Error message must match the supplied keyword according to the application's search semantics.
- Apply version and time filters when provided.
- Only retained events are eligible.

**Output:**
- Request ID, model/version identifiers, timestamp, status, error type, error message, and latency.

**Ordering and limits:**
- Newest first by inference timestamp.
- Maximum 100 events per page/request.

**Type:** Read.

**Expected frequency:** Low to medium.

**Expected result size:** Up to 100 events per page.

### Q9 — Retrieve Monitoring Metrics

**Purpose:** Display operational performance for one model version over a selected recent window.

**Inputs:**
- Version ID.
- Time window: 5, 15, or 60 minutes.

**Conditions:**
- Include only activity associated with the requested version and window.
- Calculate metrics consistently across all supported windows.

**Output:**
- Request count.
- Error count.
- Error rate.
- Throughput (requests/second).
- Average latency (milliseconds).

**Metric definitions:**
- Error rate = error count / request count.
- Average latency = total latency / request count.
- Throughput = request count / window duration in seconds.
- For a window with zero requests, counts and rates are zero; average latency is unavailable.

**Ordering and limits:** Not applicable.

**Type:** Read.

**Expected frequency:** High.

**Expected result size:** One metrics summary.

### Q10 — Compare Two Model Versions

**Purpose:** Compare the operational performance of two model versions over the same time window.

**Inputs:**
- Version ID A.
- Version ID B.
- Time window: 5, 15, or 60 minutes.

**Conditions:**
- Both versions use the same time boundaries.
- Metrics are calculated using the definitions from Q9.

**Output:**
- Metrics summary for version A.
- Metrics summary for version B.
- Differences in request count, error rate, throughput, and average latency.

**Ordering and limits:** Two versions in the requested comparison order.

**Type:** Read.

**Expected frequency:** Medium.

**Expected result size:** Two summaries and their differences.

### Q11 — Expire Old Events and Metrics

**Purpose:** Enforce data-retention policies and prevent indefinite growth of monitoring data.

**Inputs:**
- Configured retention policies.

**Conditions:**
- Raw inference events are retained for 24 hours.
- Monitoring metrics are retained for 7 days.
- Retention must apply consistently to all representations of the affected data.
- Expired events must no longer appear in application queries.

**Output:**
- Retention operation result or maintenance information, where applicable.

**Ordering and limits:** Not applicable.

**Type:** Write / maintenance.

**Expected frequency:** Automatic or periodic, depending on the data representation.

**Expected result size:** Variable; depends on the amount of expired data.

## 3. Workload Assumptions

| Parameter | Initial assumption |
|---|---|
| Models | 2 |
| Versions | 2 per model |
| Normal ingestion | Approximately 1 event/second |
| Burst ingestion | Approximately 10 events/second |
| Future evaluation volumes | 10,000 and 50,000 events |
| Raw-event retention | 24 hours |
| Metrics retention | 7 days |
| Dashboard windows | 5, 15, and 60 minutes |
| Event result limit | 100 per page/request |

The Microsoft Azure LLM Inference Trace 2023 dataset provides request-arrival patterns. Additional operational metadata is simulated.

These assumptions describe the intended workload, not benchmark results.

## 4. Query Summary

| Query | Operation | Type | Frequency |
|---|---|---|---|
| Q1 | Create/retrieve model | Read/Write | Low |
| Q2 | Create/list versions | Read/Write | Low |
| Q3 | Update/delete/archive metadata | Write | Low |
| Q4 | Ingest event and update metrics | Write | Very high |
| Q5 | Retrieve event by ID | Read | Medium |
| Q6 | Latest K events for a version | Read | High |
| Q7 | Filter events | Read | Medium |
| Q8 | Search error messages | Read | Low–medium |
| Q9 | Monitoring metrics | Read | High |
| Q10 | Version comparison | Read | Medium |
| Q11 | Retention maintenance | Write | Automatic/periodic |

## 5. Design Implications

The query catalogue establishes the following database requirements:

- Q1–Q3 require metadata management and entity relationships.
- Q4 requires continuous ingestion and associated metric updates.
- Q5 requires direct request-ID lookup.
- Q6 requires chronological event retrieval for a version.
- Q7 requires combined time, status, and latency filtering.
- Q8 requires keyword search over error messages.
- Q9–Q10 require efficient time-window aggregation and version comparison.
- Q11 requires bounded retention of events and historical metrics.

Student 2 will map these operations to Redis structures, commands, read/write costs, and consistency requirements.

The query definitions in this document form the shared application contract for M2.
