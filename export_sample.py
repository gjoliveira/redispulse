
from pathlib import Path

from simulator.generator import generate_events


def main():
    # Generate events from both Azure workloads
    conversation = generate_events("conversation", limit=100)
    code = generate_events("code", limit=100)

    # Combine and sort by timestamp
    events = conversation + code
    events.sort(key=lambda event: event.timestamp_ms)

    # Create the output directory
    output = Path("data/sample/events.jsonl")
    output.parent.mkdir(parents=True, exist_ok=True)

    # Write one JSON event per line
    with output.open("w") as file:
        for event in events:
            file.write(event.model_dump_json() + "\n")

    print(f"Exported {len(events)} events to {output}")


if __name__ == "__main__":
    main()

