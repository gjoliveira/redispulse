# RedisPulse — M2 Functional Requirements

## 1. Application Overview

RedisPulse is a lightweight, real-time LLM inference monitoring application.

It uses request-arrival patterns from the Microsoft Azure LLM Inference Trace 2023 dataset to simulate inference activity for two models:

- ConversationLLM
- CodeLLM

Each model has two deployment versions.

The application focuses on operational monitoring, including request latency, throughput, errors, and comparisons between model versions.

The main objective is to study Redis data modeling, access patterns, and design trade-offs rather than ML model sophistication.

## 2. Functional Requirements

### FR01 — Model Registry

The application shall allow users to register, retrieve, update, delete, and archive model metadata.

Each model has a unique identifier, name, description, creation timestamp, and status.

Models may be physically deleted only when unused. Models with inference history must be archived.

### FR02 — Model Version Management

The application shall allow users to register, retrieve, list, update, delete, and archive model versions.

Each version belongs to exactly one model and has a unique identifier, version label, creation timestamp, and status.

Versions with inference history must be archived rather than physically deleted.

### FR03 — Inference Event Ingestion

The application shall continuously receive and validate inference events produced by the simulator.

Each event contains:

- Unique request ID
- Model ID and version ID
- Timestamp
- Prediction
- Optional confidence
- Latency in milliseconds
- Success or error status
- Optional error type and error message

Inference events are immutable after ingestion.

The ingestion process shall also update the associated monitoring metrics.

### FR04 — Inference Event Inspection

The application shall allow users to retrieve an individual inference event by request ID.

Users shall also be able to inspect the latest K events for a selected model version, ordered newest first.

### FR05 — Event Filtering

The application shall support filtering inference events by:

- Model version
- Time interval
- Success or failure status
- Optional minimum latency threshold

Results shall be ordered chronologically, newest first, with a maximum of 100 events per request.

### FR06 — Error Investigation

The application shall allow users to inspect failed inference requests and search error messages using keywords.

Searches may optionally be restricted to a model version and time interval.

### FR07 — Operational Monitoring Metrics

The application shall calculate and display:

- Request count
- Error count
- Error rate
- Request throughput
- Average inference latency

Metrics shall be available for recent monitoring windows of 5, 15, and 60 minutes.

### FR08 — Model Version Comparison

The application shall allow users to compare the operational metrics of two model versions over the same time window.

Both versions shall use consistent metric definitions and time boundaries.

## 3. Data Retention

The application shall enforce bounded retention periods for monitoring data.

Initial design assumptions:

- Raw inference events: 24 hours
- Historical monitoring metrics: 7 days

Historical metrics shall remain available after the corresponding raw events expire.

Retention maintenance is represented by Q11 in the query catalogue.

## 4. Scope Exclusions

The initial application does not include:

- Training or executing real LLMs
- Model accuracy or quality evaluation
- Drift detection
- Automated retraining
- Alert management
- Authentication or authorization
- Distributed Redis infrastructure
- Production-grade infrastructure
- Unlimited historical event storage

## 5. Workload Assumptions

RedisPulse simulates continuous inference-event arrival using the Microsoft Azure LLM Inference Trace 2023 dataset.

Initial workload assumptions:

| Parameter | Assumption |
|---|---|
| Number of models | 2 |
| Versions per model | 2 |
| Normal ingestion rate | Approximately 1 event/second |
| Burst ingestion rate | Approximately 10 events/second |
| Future evaluation volumes | 10,000 and 50,000 events |
| Dashboard windows | 5, 15, and 60 minutes |
| Maximum event query result | 100 records |
| Raw-event retention | 24 hours |
| Metrics retention | 7 days |

The original trace provides request-arrival patterns. The simulator assigns current simulated event timestamps and generates additional metadata, including predictions, confidence values, latency, errors, and model-version assignments.

These values are design assumptions, not measured performance results.

## 6. M2 Scope

M2 focuses on application specification, conceptual modeling, query definitions, Redis data design, and analytical justification of modeling choices.

Implementation, benchmarking, and experimental validation are not required for this milestone.
