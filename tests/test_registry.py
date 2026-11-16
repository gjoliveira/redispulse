"""Model and version management (RedisRegistry)."""

import pytest

from app.schemas import Model


def test_create_and_get_model(r, registry, model):
    assert r.hgetall(f"model:{model.model_id}")["name"] == "Test model"
    assert registry.get_model(model.model_id) == model
    assert registry.get_model("no-such-model") is None


def test_duplicate_model_id_is_rejected(registry, model):
    impostor = model.model_copy(update={"name": "Impostor"})

    assert registry.create_model(impostor) is False
    assert registry.get_model(model.model_id).name == "Test model"


def test_update_and_archive_model(registry, model):
    updated = registry.update_model(model.model_id, name="Renamed")
    archived = registry.archive_model(model.model_id)

    assert updated.name == "Renamed"
    assert archived.status == "archived"
    assert registry.get_model(model.model_id) == archived
    assert registry.update_model("no-such-model", name="x") is None


def test_delete_unused_model(r, registry, model):
    assert registry.delete_model(model.model_id) is True
    assert not r.exists(f"model:{model.model_id}")


def test_delete_model_in_use_is_rejected(r, registry, uid, model, version):
    with pytest.raises(ValueError, match="versions"):
        registry.delete_model(model.model_id)

    # A model without versions but with inference history is also kept.
    other = Model(model_id=f"{uid}-used", name="u", description="",
                  created_at_ms=0)
    registry.create_model(other)
    r.set(f"model-used:{other.model_id}", 1)
    with pytest.raises(ValueError, match="inference history"):
        registry.delete_model(other.model_id)


def test_create_and_list_versions(r, registry, model, add_version):
    b = add_version(model.model_id, "v2")
    a = add_version(model.model_id, "v1")

    assert registry.list_versions(model.model_id) == [a, b]
    assert r.smembers(f"versions:{model.model_id}") == {a.version_id, b.version_id}


def test_create_version_rejects_duplicates_and_missing_parent(
    r, registry, uid, model, version
):
    duplicate = version.model_copy(update={"version_label": "other"})
    assert registry.create_version(duplicate) is False

    orphan = version.model_copy(
        update={"version_id": f"{uid}-orphan", "model_id": f"{uid}-none"}
    )
    with pytest.raises(ValueError, match="Parent model"):
        registry.create_version(orphan)
    assert not r.exists(f"version:{uid}-orphan")


def test_update_and_archive_version(registry, model, version):
    assert registry.update_version(version.version_id, "v9").version_label == "v9"
    archived = registry.archive_version(version.version_id)

    assert archived.status == "archived"
    assert registry.list_versions(model.model_id) == [archived]
    assert registry.archive_version("no-such-version") is None


def test_delete_version(r, registry, store, model, version, add_version, make_event):
    # Unused version: deleted and removed from its model's set.
    unused = add_version(model.model_id, "unused")
    assert registry.delete_version(unused.version_id) is True
    assert unused.version_id not in r.smembers(f"versions:{model.model_id}")

    # Version with inference history: kept.
    store.ingest_event(make_event())
    with pytest.raises(ValueError, match="inference history"):
        registry.delete_version(version.version_id)
    assert r.exists(f"version:{version.version_id}")
