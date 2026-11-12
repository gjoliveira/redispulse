
import csv
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field


class TraceRequest(BaseModel):
    timestamp: datetime
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    workload: str


def load_trace(file_path: str, workload: str, limit: int = 10):
    requests = []

    with Path(file_path).open(newline="") as file:
        reader = csv.DictReader(file)

        for row in reader:
            request = TraceRequest(
                timestamp=datetime.fromisoformat(row["TIMESTAMP"]),
                input_tokens=int(row["ContextTokens"]),
                output_tokens=int(row["GeneratedTokens"]),
                workload=workload,
            )

            requests.append(request)

            if len(requests) >= limit:
                break

    return requests
