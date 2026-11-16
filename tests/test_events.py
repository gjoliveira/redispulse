"""Event ingestion, retrieval, search, metrics and retention (RedisEventStore)."""

import pytest

from app import redis_events
from app.schemas import Model

MINUTE_MS = 60_000
DAY_MS = 86_400_000


def server_now_ms(r):
    seconds, micros = r.time()
    return seconds * 1000 + micros // 1000


def bucket(event_or_ts):
    ts = getattr(event_or_ts, "timestamp_ms", event_or_ts)
    return ts // MINUTE_MS * MINUTE_MS


# --- ingestion and retrieval ----------------------------------------------

def test_ingest_stores_hash_stream_entry_and_permanent_markers(
    r, store, model, version, make_event
):
    event = make_event("error")

    assert store.ingest_event(event) is True

    assert r.hgetall(f"event:{event.request_id}")["error_type"] == "timeout"
    assert r.xlen(f"events:{version.version_id}") == 1
    for marker in (f"request-used:{event.request_id}",
                   f"model-used:{model.model_id}",
                   f"version-used:{version.version_id}"):
        assert r.ttl(marker) == -1  # exists and never expires


def test_get_event_and_latest_events(store, version, make_event):
    events = [make_event() for _ in range(5)]
    for e in events:
        store.ingest_event(e)

    assert store.get_event(events[0].request_id) == events[0]
    assert store.get_event("no-such-request") is None
    latest = store.get_latest_events(version.version_id, limit=3)
    assert latest == events[::-1][:3]  # newest first
    assert store.get_latest_events("no-such-version") == []


def test_duplicate_request_is_rejected_without_side_effects(
    r, store, version, make_event
):
    first = make_event(request_id=f"{version.version_id}-dup")
    store.ingest_event(first)
    metrics_key = f"metrics:{version.version_id}:{bucket(first)}"

    retry = make_event(request_id=first.request_id, latency_ms=999)
    assert store.ingest_event(retry) is False

    assert r.xlen(f"events:{version.version_id}") == 1
    assert r.hget(metrics_key, "total") == "1"
    assert store.get_event(first.request_id) == first


@pytest.mark.parametrize("problem", ["missing-version", "foreign-version",
                                     "archived-version"])
def test_invalid_event_is_rejected_without_partial_state(
    r, registry, store, uid, model, add_version, make_event, problem
):
    if problem == "missing-version":
        event = make_event(version_id=f"{uid}-ghost")
    elif problem == "foreign-version":
        other = Model(model_id=f"{uid}-other", name="o", description="",
                      created_at_ms=0)
        registry.create_model(other)
        foreign = add_version(other.model_id, "foreign")
        event = make_event(version_id=foreign.version_id)
    else:
        v = add_version(model.model_id, "old")
        registry.archive_version(v.version_id)
        event = make_event(v=v)

    with pytest.raises(ValueError):
        store.ingest_event(event)

    assert not r.exists(f"event:{event.request_id}")
    assert not r.exists(f"request-used:{event.request_id}")
    assert not r.exists(f"events:{event.version_id}")
    assert not list(r.scan_iter(match=f"metrics:{event.version_id}:*"))


@pytest.mark.parametrize("offset_ms", [-DAY_MS - 1, 2 * MINUTE_MS],
                         ids=["older-than-24h", "too-far-in-future"])
def test_event_outside_timestamp_window_is_rejected(
    r, store, version, make_event, now, offset_ms
):
    event = make_event(timestamp_ms=now + offset_ms)

    with pytest.raises(ValueError, match="timestamp"):
        store.ingest_event(event)

    # In particular, no (possibly already expired) metrics bucket is created.
    assert not r.exists(f"event:{event.request_id}")
    assert not list(r.scan_iter(match=f"metrics:{version.version_id}:*"))


# --- Redis Search -----------------------------------------------------------

@pytest.mark.usefixtures("search_index")
def test_filter_events_by_time_status_and_latency(
    store, version, make_event, now
):
    t = now - 10 * MINUTE_MS
    match_old = make_event("error", timestamp_ms=t, latency_ms=1500)
    match_new = make_event("error", timestamp_ms=t + 2000, latency_ms=1000)
    for e in (
        match_old, match_new,
        make_event("success", timestamp_ms=t + 1000, latency_ms=1500),
        make_event("error", timestamp_ms=t + 1000, latency_ms=999),
        make_event("error", timestamp_ms=t - 1, latency_ms=1500),
    ):
        store.ingest_event(e)

    found = store.filter_events(version.version_id, t, t + 5000,
                                status="error", min_latency_ms=1000)

    assert found == [match_new, match_old]  # newest first
    assert store.filter_events(version.version_id, t, t + 5000, status="error",
                               min_latency_ms=1000, limit=1) == [match_new]


@pytest.mark.usefixtures("search_index")
def test_filter_events_escapes_hyphenated_version_ids(
    store, model, add_version, make_event
):
    # "<uid>-x-v1" must not match "<uid>-x-v1-canary" (or vice versa).
    short = add_version(model.model_id, "x-v1.0")
    longer = add_version(model.model_id, "x-v1.0-canary")
    mine = make_event(v=short)
    store.ingest_event(mine)
    store.ingest_event(make_event(v=longer))

    assert store.filter_events(short.version_id, 0, 2**53) == [mine]


@pytest.mark.usefixtures("search_index")
def test_search_errors_by_keyword(store, uid, model, version, add_version,
                                  make_event):
    keyword = uid.replace("-", "")  # unique word, isolates this test
    other = add_version(model.model_id, "v2")
    hit = make_event("error", error_message=f"gateway {keyword} failure")
    elsewhere = make_event("error", v=other, error_message=f"{keyword} too")
    for e in (
        hit, elsewhere,
        make_event("error", error_message="rate limit exceeded"),
        make_event("success", error_message=f"{keyword} warning only"),
    ):
        store.ingest_event(e)

    assert store.search_errors(keyword, version_id=version.version_id) == [hit]
    assert len(store.search_errors(keyword)) == 2  # success event excluded


# --- metrics ------------------------------------------------------------------

def test_get_metrics(store, version, make_event, now):
    for status, latency in [("success", 100), ("success", 200),
                            ("success", 300), ("error", 1400)]:
        store.ingest_event(make_event(status, latency_ms=latency))

    assert store.get_metrics(version.version_id, 5, end_ms=now) == {
        "request_count": 4,
        "error_count": 1,
        "error_rate": 0.25,
        "average_latency_ms": 500.0,
        "throughput_rps": 4 / 300,
    }
    assert store.get_metrics("no-such-version", 5, end_ms=now) == {
        "request_count": 0, "error_count": 0, "error_rate": 0.0,
        "average_latency_ms": None, "throughput_rps": 0.0,
    }
    with pytest.raises(ValueError):
        store.get_metrics(version.version_id, 10)


def test_metrics_use_event_timestamp_not_ingestion_time(
    r, store, version, make_event, now
):
    late = make_event(timestamp_ms=now - 10 * MINUTE_MS)
    store.ingest_event(late)

    assert r.hget(f"metrics:{version.version_id}:{bucket(late)}", "total") == "1"
    assert not r.exists(f"metrics:{version.version_id}:{bucket(now)}")
    assert store.get_metrics(version.version_id, 5)["request_count"] == 0
    assert store.get_metrics(version.version_id, 15)["request_count"] == 1


def test_metrics_windows_cover_the_last_n_minutes(r, store, uid, now):
    end = bucket(now)
    # One request in buckets 0, 4, 5, 14, 15, 59 and 60 minutes ago.
    for minutes_ago in (0, 4, 5, 14, 15, 59, 60):
        r.hset(f"metrics:{uid}-v:{end - minutes_ago * MINUTE_MS}",
               mapping={"total": 1, "latency_sum_ms": 10})

    counts = {w: store.get_metrics(f"{uid}-v", w)["request_count"]
              for w in (5, 15, 60)}

    assert counts == {5: 2, 15: 4, 60: 6}


def test_compare_versions(store, model, version, add_version, make_event):
    v2 = add_version(model.model_id, "v2")
    store.ingest_event(make_event(latency_ms=100))
    store.ingest_event(make_event(v=v2, latency_ms=300))
    store.ingest_event(make_event("error", v=v2, latency_ms=500))

    result = store.compare_versions(version.version_id, v2.version_id)

    a, b = result["version_a"], result["version_b"]
    assert (a["id"], b["id"]) == (version.version_id, v2.version_id)
    assert a["metrics"]["request_count"] == 1
    assert b["metrics"]["request_count"] == 2
    assert b["metrics"]["error_rate"] == 0.5
    assert b["metrics"]["average_latency_ms"] == 400.0


# --- retention ------------------------------------------------------------

def test_event_hash_and_metrics_expiry(r, store, version, make_event):
    event = make_event()
    store.ingest_event(event)

    assert 86_390 <= r.ttl(f"event:{event.request_id}") <= 86_400
    metrics_key = f"metrics:{version.version_id}:{bucket(event)}"
    assert r.expiretime(metrics_key) == bucket(event) // 1000 + 7 * 86_400 + 60
    assert r.ttl(f"version:{version.version_id}") == -1  # metadata is kept


def test_stream_trimming_uses_redis_server_time(r, store, version, monkeypatch):
    server_now = server_now_ms(r)
    key = f"events:{version.version_id}"
    r.xadd(key, {"age": "old"}, id=f"{server_now - DAY_MS - MINUTE_MS}-0")
    r.xadd(key, {"age": "recent"}, id=f"{server_now - DAY_MS + 10 * MINUTE_MS}-0")

    # Even with the application clock two days ahead of Redis...
    monkeypatch.setattr(redis_events, "_now_ms", lambda: server_now + 2 * DAY_MS)

    # ...only entries older than 24 h by the *server* clock are removed.
    assert store.trim_version_stream(version.version_id) == 1
    assert [fields["age"] for _, fields in r.xrange(key)] == ["recent"]


def test_ingestion_trims_old_stream_entries(r, store, version, make_event):
    key = f"events:{version.version_id}"
    r.xadd(key, {"age": "old"}, id=f"{server_now_ms(r) - DAY_MS - MINUTE_MS}-0")

    store.ingest_event(make_event())

    assert r.xlen(key) == 1
    assert "age" not in r.xrange(key)[0][1]


def test_expired_event_keeps_markers_and_cannot_be_replayed(
    r, store, registry, version, make_event
):
    event = make_event()
    store.ingest_event(event)
    r.delete(f"event:{event.request_id}")  # as if the 24 h TTL had passed

    assert store.ingest_event(event) is False
    assert r.exists(f"request-used:{event.request_id}")
    assert r.xlen(f"events:{version.version_id}") == 1
    with pytest.raises(ValueError, match="inference history"):
        registry.delete_version(version.version_id)
