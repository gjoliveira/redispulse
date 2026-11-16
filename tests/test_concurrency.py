"""Redis transactions under concurrency (WATCH + MULTI/EXEC).

Threads start together on a barrier; tests assert the final state and
invariants, never which thread wins.
"""

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
import redis

from app.schemas import Model, ModelVersion

ROUNDS = 5


def run_together(*functions):
    """Run functions in parallel; return each result or raised exception."""
    barrier = threading.Barrier(len(functions))

    def call(fn):
        barrier.wait()
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001 - asserted by the tests
            return exc

    with ThreadPoolExecutor(len(functions)) as pool:
        return list(pool.map(call, functions))


def test_concurrent_duplicate_ingestion_is_accepted_once(
    r, store, version, make_event
):
    event = make_event()

    results = run_together(*[lambda: store.ingest_event(event)] * 10)

    assert sorted(results) == [False] * 9 + [True]
    assert r.xlen(f"events:{version.version_id}") == 1
    minute = event.timestamp_ms // 60_000 * 60_000
    assert r.hget(f"metrics:{version.version_id}:{minute}", "total") == "1"


def test_concurrent_model_creation_with_same_id_succeeds_once(registry, uid):
    models = [Model(model_id=f"{uid}-same", name=f"m{i}", description="",
                    created_at_ms=0) for i in range(10)]

    results = run_together(*[(lambda m=m: registry.create_model(m)) for m in models])

    assert results.count(True) == 1
    winner = models[results.index(True)]
    assert registry.get_model(winner.model_id) == winner


def test_model_deletion_vs_version_creation_leaves_no_orphans(r, registry, uid):
    for i in range(ROUNDS):
        model = Model(model_id=f"{uid}-m{i}", name="m", description="",
                      created_at_ms=0)
        registry.create_model(model)
        version = ModelVersion(version_id=f"{uid}-v{i}", model_id=model.model_id,
                               version_label="v", created_at_ms=0)

        deleted, created = run_together(
            lambda: registry.delete_model(model.model_id),
            lambda: registry.create_version(version),
        )

        # Exactly one wins; the loser is rejected with ValueError.
        if created is True:
            assert isinstance(deleted, ValueError)
            assert r.exists(f"model:{model.model_id}")
        else:
            assert deleted is True and isinstance(created, ValueError)
            assert not r.exists(f"version:{version.version_id}")


def test_version_deletion_vs_ingestion_leaves_no_orphan_events(
    r, registry, store, model, add_version, make_event
):
    for i in range(ROUNDS):
        version = add_version(model.model_id, f"race{i}")
        event = make_event(v=version)

        deleted, ingested = run_together(
            lambda: registry.delete_version(version.version_id),
            lambda: store.ingest_event(event),
        )

        if ingested is True:
            assert isinstance(deleted, ValueError)
            assert r.exists(f"version:{version.version_id}")
        else:
            assert deleted is True and isinstance(ingested, ValueError)
            assert not r.exists(f"event:{event.request_id}")
            assert not r.exists(f"events:{version.version_id}")


@pytest.mark.parametrize("operation", ["archive_model", "update_version"])
def test_update_cannot_recreate_a_concurrently_deleted_record(
    r, registry, model, version, monkeypatch, operation
):
    """Deterministic race: the record is deleted just before EXEC.

    The method must notice (Redis aborts the watched transaction), retry,
    see the record is gone and return None - not recreate a partial Hash.
    """
    if operation == "archive_model":
        registry.delete_version(version.version_id)  # make model deletable
        key, args = f"model:{model.model_id}", (model.model_id,)
        delete = lambda: registry.delete_model(model.model_id)  # noqa: E731
    else:
        key, args = f"version:{version.version_id}", (version.version_id, "v2")
        delete = lambda: registry.delete_version(version.version_id)  # noqa: E731

    # Run the delete once, right before the first transaction commits.
    original_execute = redis.client.Pipeline.execute
    pending = [delete]

    def execute_with_race(pipe, *a, **kw):
        if pending:
            pending.pop()()
        return original_execute(pipe, *a, **kw)

    monkeypatch.setattr(redis.client.Pipeline, "execute", execute_with_race)

    result = getattr(registry, operation)(*args)

    assert not pending, "the concurrent delete never ran"
    assert result is None
    assert not r.exists(key)
