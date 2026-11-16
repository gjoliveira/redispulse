# RedisPulse — M2 Requirements Coverage

## 1. Purpose

This document maps the BDNR project requirements to the RedisPulse conceptual data model and query catalogue.

It serves as a traceability matrix, showing where each requirement is addressed in the proposed design.

## 2. Requirements Traceability Matrix

| BDNR Requirement | RedisPulse Coverage | Evidence |
|---|---|---|
| Multiple entities | Three entities: Model, ModelVersion, InferenceEvent | `a3-conceptual-model.md` |
| Entity associations | Model 1:N ModelVersion; ModelVersion 1:N InferenceEvent | UML diagram |
| CRUD operations | Create, retrieve, update, delete, and archive model/version metadata | Q1, Q2, Q3 |
| Key-based lookup | Retrieve models and inference events by unique ID | Q1, Q5 |
| Attribute-based lookup | Filter events by version, time, status, and latency | Q7 |
| Multiple aggregates | Calculate several metrics and compare two versions | Q9, Q10 |
| Aggregation | Request count, error count, error rate, throughput, average latency | Q9, Q10 |
| Projection | Return selected event fields and metric summaries | Q6–Q10 |
| Full-text search | Search error messages by keyword | Q8 |
| Redis-specific functionality | Streams, Hashes, Sets, Redis Search, transactions, and expiration | Q4, Q6–Q11; Redis design |

## 3. Supporting Documents

| Document | Role |
|---|---|
| `a1-requirements.md` | Defines application scope and functional requirements |
| `a2-queries.md` | Defines Q1–Q11 and their access patterns |
| `a3-conceptual-model.md` | Defines entities, attributes, and relationships |
| Redis data design | Explains the Redis structures supporting these operations |

## 4. Conclusion

The proposed RedisPulse design addresses the identified BDNR requirements through three conceptual entities and eleven application operations.

This matrix documents **design coverage**, not implementation or benchmark results. Redis commands, operation costs, and modeling trade-offs are addressed separately in the Redis data design.
