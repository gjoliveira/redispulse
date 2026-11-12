
import json
import random
from datetime import datetime, timezone

from app.schemas import InferenceEvent
from simulator.trace_loader import load_trace


#NOTE : We define latency as L = (100 + input_tokens * 0.02 + output_tokens * 6) * latency_factor * random_factor

TRACE_FILES = {
    "conversation": "data/raw/AzureLLMInferenceTrace_conv.csv",
    "code": "data/raw/AzureLLMInferenceTrace_code.csv",
}


def generate_events(workload, limit=10, seed=42):
    # Load the Azure requests
    requests = load_trace(
        TRACE_FILES[workload],
        workload=workload,
        limit=limit,
    )

    # Load our simulated model registry
    with open("config/models.json") as file:
        config = json.load(file)

    model_id = f"llm-{workload}"

    versions = [
        version
        for version in config["versions"]
        if version["model_id"] == model_id
    ]

    if len(versions) != 2:
        raise ValueError("Expected two versions per model")

    rng = random.Random(seed)
    events = []

    # Shift historical request times to the present.
    # This preserves the time gaps between requests.
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    last_timestamp = requests[-1].timestamp

    for i, request in enumerate(requests):
        version = versions[i % 2]

        # v1.1 is simulated as faster and more reliable
        is_new_version = version["version_label"] == "v1.1"

        latency_factor = 0.8 if is_new_version else 1.0
        error_probability = 0.02 if is_new_version else 0.08

        base_latency = (
            100
            + request.input_tokens * 0.02
            + request.output_tokens * 6
        )

        latency_ms = round(
            base_latency * latency_factor * rng.uniform(0.9, 1.1),
            2,
        )

        failed = rng.random() < error_probability

        time_before_last = (
            last_timestamp - request.timestamp
        ).total_seconds()

        timestamp_ms = now_ms - int(time_before_last * 1000)

        event = InferenceEvent(
            request_id=f"{workload}-{i + 1:05d}",
            model_id=model_id,
            version_id=version["version_id"],
            timestamp_ms=timestamp_ms,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            latency_ms=latency_ms,
            status="error" if failed else "success",
            error_type="inference_error" if failed else None,
        )

        events.append(event)

    return events


if __name__ == "__main__":
    for workload in TRACE_FILES:
        events = generate_events(workload, limit=5)

        print(f"\n{workload.upper()} EVENTS")

        for event in events:
            print(event.model_dump_json(indent=2))
