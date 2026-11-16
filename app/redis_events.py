
import re
from datetime import datetime, timezone

import redis
from redis.commands.search.query import Query

from app.schemas import InferenceEvent

MINUTE_MS = 60_000

# Raw events (event Hashes and Stream entries) are kept for 24 hours.
RAW_RETENTION_S = 86_400
RAW_RETENTION_MS = RAW_RETENTION_S * 1000

# Per-minute metrics buckets are kept for seven days after their minute.
METRICS_RETENTION_S = 7 * 86_400

# Accepted event timestamps, relative to the application clock:
#   now - MAX_EVENT_AGE_MS  <=  timestamp_ms  <=  now + MAX_CLOCK_SKEW_MS
#
# * Older events are already outside the raw-event retention window, and
#   (since buckets are keyed by event time) could otherwise recreate a
#   metrics bucket that Redis has already expired.
# * A small future tolerance absorbs producer/consumer clock skew while
#   preventing far-future buckets that no monitoring window would read.
MAX_EVENT_AGE_MS = RAW_RETENTION_MS
MAX_CLOCK_SKEW_MS = 60_000


def _now_ms() -> int:
    """Application (UTC wall-clock) time in milliseconds."""
    return int(datetime.now(timezone.utc).timestamp() * 1000)


class RedisEventStore:
    def __init__(self, client: redis.Redis):
        self.client = client

    @staticmethod
    def _server_time_ms(conn) -> int:
        """Redis server time in milliseconds.

        Auto-generated Stream IDs come from the Redis server clock, so the
        XTRIM MINID cutoff must be computed from the same clock; using the
        application clock would trim too much or too little under skew.
        """
        seconds, micros = conn.time()
        return int(seconds) * 1000 + int(micros) // 1000

    def ingest_event(self, event: InferenceEvent) -> bool:
        event_key = f"event:{event.request_id}"
        request_used_key = f"request-used:{event.request_id}"
        stream_key = f"events:{event.version_id}"
        version_key = f"version:{event.version_id}"
        model_key = f"model:{event.model_id}"

        # Redis Hashes and Streams cannot store None values.
        data = event.model_dump(exclude_none=True)

        # Validate the event time before touching Redis (see the
        # MAX_EVENT_AGE_MS / MAX_CLOCK_SKEW_MS policy above).
        now_ms = _now_ms()

        if not (
            now_ms - MAX_EVENT_AGE_MS
            <= event.timestamp_ms
            <= now_ms + MAX_CLOCK_SKEW_MS
        ):
            raise ValueError(
                "Event timestamp outside the accepted ingestion window"
            )

        # Group metrics by the event's own minute (UTC), per the design.
        minute_ms = (event.timestamp_ms // MINUTE_MS) * MINUTE_MS
        metrics_key = f"metrics:{event.version_id}:{minute_ms}"

        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(event_key, request_used_key, version_key, model_key)

                    # Reject duplicate request IDs.
                    if pipe.exists(event_key) or pipe.exists(request_used_key):
                        pipe.unwatch()
                        return False

                    # Validate the model and version relationship.
                    model = pipe.hgetall(model_key)
                    version = pipe.hgetall(version_key)

                    if (
                        not model
                        or not version
                        or version.get("model_id") != event.model_id
                    ):
                        pipe.unwatch()
                        raise ValueError("Invalid model or version")

                    if (
                        model.get("status") != "active"
                        or version.get("status") != "active"
                    ):
                        pipe.unwatch()
                        raise ValueError("Model or version is archived")

                    # Stream IDs use the server clock; so must the cutoff.
                    cutoff_ms = (
                        self._server_time_ms(pipe) - RAW_RETENTION_MS
                    )

                    pipe.multi()

                    # Store in the version's Stream.
                    pipe.xadd(stream_key, data)

                    pipe.xtrim(
                        stream_key,
                        minid=str(cutoff_ms),
                        approximate=False,
                    )

                    # Store the individually addressable Hash.
                    pipe.hset(event_key, mapping=data)

                    pipe.expire(event_key, RAW_RETENTION_S)
                    pipe.set(request_used_key, 1)

                    # Remember that these records have been used.
                    pipe.set(f"model-used:{event.model_id}", 1)
                    pipe.set(f"version-used:{event.version_id}", 1)


                    # Update monitoring counters.
                    pipe.hincrby(metrics_key, "total", 1)

                    pipe.hincrbyfloat(
                        metrics_key,
                        "latency_sum_ms",
                        event.latency_ms,
                    )

                    if event.status == "error":
                        pipe.hincrby(metrics_key, "errors", 1)

                    # Retain the minute bucket for seven days after its
                    # minute. The timestamp policy keeps this in the future.
                    pipe.expireat(
                        metrics_key,
                        minute_ms // 1000 + METRICS_RETENTION_S + 60,
                    )


                    pipe.execute()
                    return True

                except redis.WatchError:
                    continue

    def get_event(self, request_id: str) -> InferenceEvent | None:
        data = self.client.hgetall(f"event:{request_id}")

        if not data:
            return None

        return InferenceEvent.model_validate(data)

    
    def get_latest_events(
        self,
        version_id: str,
        limit: int = 10,
    ) -> list[InferenceEvent]:
        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")

        entries = self.client.xrevrange(
            f"events:{version_id}",
            count=limit,
        )

        return [
            InferenceEvent.model_validate(data)
            for _, data in entries
        ]

    
    def ensure_search_index(self) -> None:
        # Avoid creating the same index twice.
        existing_indexes = self.client.execute_command("FT._LIST")

        if "idx:events" in existing_indexes:
            return

        self.client.execute_command(
            "FT.CREATE", "idx:events",
            "ON", "HASH",
            "PREFIX", 1, "event:",
            "SCHEMA",
            "model_id", "TAG",
            "version_id", "TAG",
            "timestamp_ms", "NUMERIC", "SORTABLE",
            "latency_ms", "NUMERIC",
            "status", "TAG",
            "error_message", "TEXT",
        )


     
    def filter_events(
        self,
        version_id: str,
        start_ms: int,
        end_ms: int,
        status: str | None = None,
        min_latency_ms: float | None = None,
        limit: int = 100,
    ) -> list[InferenceEvent]:
  

        if start_ms > end_ms:
            raise ValueError("Invalid time interval")

        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")

        if status not in (None, "success", "error"):
            raise ValueError("Invalid status")

        if min_latency_ms is not None and min_latency_ms < 0:
            raise ValueError("Invalid latency")

        safe_version = re.sub(
            r"([^A-Za-z0-9_])", r"\\\1", version_id
        )

        filters = [
            f"@version_id:{{{safe_version}}}",
            f"@timestamp_ms:[{start_ms} {end_ms}]",
        ]

        if status is not None:
            filters.append(f"@status:{{{status}}}")

        if min_latency_ms is not None:
            filters.append(
                f"@latency_ms:[{min_latency_ms} +inf]"
            )

        query = (
            Query(" ".join(filters))
            .no_content()
            .sort_by("timestamp_ms", asc=False)
            .paging(0, limit)
            .dialect(2)
        )

        results = self.client.ft("idx:events").search(query)

        # Each result contains the matching Redis key.
        event_keys = [doc.id for doc in results.docs]

        with self.client.pipeline() as pipe:
            for key in event_keys:
                pipe.hgetall(key)
            records = pipe.execute()

        return [
            InferenceEvent.model_validate(data)
            for data in records
            if data
        ]

    
    def search_errors(
        self,
        keyword: str,
        version_id: str | None = None,
        limit: int = 100,
        start_ms: int | None = None,
        end_ms: int | None = None,
    ) -> list[InferenceEvent]:
        if not re.fullmatch(r"[A-Za-z0-9_]+", keyword):
            raise ValueError("Keyword must be a single word")

        if not 1 <= limit <= 100:
            raise ValueError("Limit must be between 1 and 100")

        filters = [
            "@status:{error}",
            f"@error_message:{keyword}",
        ]

        if version_id is not None:
            safe_version = re.sub(
                r"([^A-Za-z0-9_])", r"\\\1", version_id
            )
            filters.append(f"@version_id:{{{safe_version}}}")


        # Optional time interval.
        if start_ms is not None or end_ms is not None:
            if (
                start_ms is not None
                and end_ms is not None
                and start_ms > end_ms
            ):
                raise ValueError("Invalid time interval")

            start = start_ms if start_ms is not None else "-inf"
            end = end_ms if end_ms is not None else "+inf"

            filters.append(f"@timestamp_ms:[{start} {end}]")
        
        query = (
            Query(" ".join(filters))
            .no_content()
            .sort_by("timestamp_ms", asc=False)
            .paging(0, limit)
            .dialect(2)
        )

        results = self.client.ft("idx:events").search(query)

        with self.client.pipeline() as pipe:
            for doc in results.docs:
                pipe.hgetall(doc.id)
            records = pipe.execute()

        return [
            InferenceEvent.model_validate(data)
            for data in records
            if data
        ]

    
    def get_metrics(
        self,
        version_id: str,
        window_minutes: int = 5,
        end_ms: int | None = None,
    ) -> dict:
    

        if window_minutes not in (5, 15, 60):
            raise ValueError("Invalid monitoring window")

        if end_ms is None:
            end_ms = _now_ms()

        current_minute = (end_ms // 60_000) * 60_000

        # Get the keys for the current and previous minutes.
        keys = [
            f"metrics:{version_id}:{current_minute - i * 60_000}"
            for i in range(window_minutes)
        ]

        # Read all metric buckets.
        with self.client.pipeline() as pipe:
            for key in keys:
                pipe.hgetall(key)
            buckets = pipe.execute()

        total = sum(int(b.get("total", 0)) for b in buckets)
        errors = sum(int(b.get("errors", 0)) for b in buckets)
        latency_sum = sum(
            float(b.get("latency_sum_ms", 0))
            for b in buckets
        )

        return {
            "request_count": total,
            "error_count": errors,
            "error_rate": errors / total if total else 0.0,
            "average_latency_ms": latency_sum / total if total else None,
            "throughput_rps": total / (window_minutes * 60),
        }

    
    
    def compare_versions(
        self,
        version_a: str,
        version_b: str,
        window_minutes: int = 5,
    ) -> dict:
        # One shared time boundary for both versions.
        end_ms = _now_ms()

        return {
            "version_a": {
                "id": version_a,
                "metrics": self.get_metrics(
                    version_a, window_minutes, end_ms
                ),
            },
            "version_b": {
                "id": version_b,
                "metrics": self.get_metrics(
                    version_b, window_minutes, end_ms
                ),
            },
        }

    
    def trim_version_stream(self, version_id: str) -> int:
        """Remove Stream entries older than 24 hours (Redis server time)."""

        cutoff_ms = self._server_time_ms(self.client) - RAW_RETENTION_MS

        removed = self.client.xtrim(
            f"events:{version_id}",
            minid=str(cutoff_ms),
            approximate=False,
        )

        return removed

