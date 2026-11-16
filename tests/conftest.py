"""Shared fixtures for the RedisPulse tests.

The Redis tests run against a separate, throwaway Redis container on port
6380 (compose.test.yaml), never against the development Redis on 6379.
A second logical DB on the dev server would not be enough, because Redis
Search only allows indexes on DB 0.

Every test builds its IDs from a unique ``uid`` and all keys containing it
are deleted afterwards, so tests are independent of each other.
"""

import time
import uuid

import pytest
import redis

from app import redis_events
from app.redis_events import RedisEventStore
from app.redis_registry import RedisRegistry
from app.schemas import InferenceEvent, Model, ModelVersion

TEST_REDIS_URL = "redis://localhost:6380/0"
MINUTE_MS = 60_000
DAY_MS = 86_400_000


@pytest.fixture(scope="session")
def redis_client():
    client = redis.Redis.from_url(TEST_REDIS_URL, decode_responses=True)
    try:
        client.ping()
    except redis.ConnectionError:
        pytest.fail(
            f"Test Redis is not running at {TEST_REDIS_URL}. Start it with:\n"
            "    docker compose -f compose.test.yaml up -d",
            pytrace=False,
        )
    yield client
    client.close()


@pytest.fixture
def uid(redis_client):
    """Unique ID prefix for one test; its keys are removed afterwards."""
    token = f"test-{uuid.uuid4().hex[:8]}"
    yield token
    keys = list(redis_client.scan_iter(match=f"*{token}*"))
    if keys:
        redis_client.delete(*keys)


@pytest.fixture
def r(redis_client, uid):
    return redis_client


@pytest.fixture
def registry(r):
    return RedisRegistry(r)


@pytest.fixture
def store(r):
    return RedisEventStore(r)


@pytest.fixture(scope="session")
def search_index(redis_client):
    RedisEventStore(redis_client).ensure_search_index()
    yield
    redis_client.execute_command("FT.DROPINDEX", "idx:events")


@pytest.fixture
def now(monkeypatch):
    """Freeze the application clock (not Redis' own clock).

    30 s into the minute that started an hour ago: a fixed, recent instant,
    so minute buckets are deterministic and their 7-day expiry is valid.
    """
    real_now = int(time.time() * 1000)
    fixed = real_now // MINUTE_MS * MINUTE_MS - 60 * MINUTE_MS + 30_000
    monkeypatch.setattr(redis_events, "_now_ms", lambda: fixed)
    return fixed


# --- domain objects -------------------------------------------------------

@pytest.fixture
def model(registry, uid):
    m = Model(model_id=f"{uid}-model", name="Test model",
              description="test", created_at_ms=0)
    assert registry.create_model(m)
    return m


@pytest.fixture
def add_version(registry, uid):
    def _add(model_id, suffix="v1"):
        v = ModelVersion(version_id=f"{uid}-{suffix}", model_id=model_id,
                         version_label=suffix, created_at_ms=0)
        assert registry.create_version(v)
        return v
    return _add


@pytest.fixture
def version(model, add_version):
    return add_version(model.model_id)


@pytest.fixture
def make_event(uid, version, now):
    """Build an event; by default a few seconds before ``now``."""
    counter = iter(range(10_000))

    def _make(status="success", v=None, request_id=None, **fields):
        n = next(counter)
        v = v or version
        data = dict(
            request_id=request_id or f"{uid}-req-{n}",
            model_id=v.model_id,
            version_id=v.version_id,
            timestamp_ms=now - 5_000 + n,
            input_tokens=100,
            output_tokens=50,
            latency_ms=250.0,
            status=status,
        )
        if status == "error":
            data.update(error_type="timeout",
                        error_message="Upstream timeout after 30 seconds")
        data.update(fields)
        return InferenceEvent(**data)

    return _make
