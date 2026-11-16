
import redis
from app.schemas import Model, ModelVersion


class RedisRegistry:
    def __init__(self, client: redis.Redis):
        self.client = client

    

    def get_model(self, model_id: str) -> Model | None:
        key = f"model:{model_id}"

        data = self.client.hgetall(key)

        if not data:
            return None

        return Model.model_validate(data)

    def create_model(self, model: Model) -> bool:
        key = f"model:{model.model_id}"

        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)

                    # Reject duplicate model IDs.
                    if pipe.exists(key):
                        pipe.unwatch()
                        return False

                    pipe.multi()

                    # Create all model fields together.
                    pipe.hset(
                        key,
                        mapping=model.model_dump(),
                    )

                    pipe.execute()
                    return True

                except redis.WatchError:
                    # Another client modified the key.
                    # Retry the operation.
                    continue



    
    def create_version(self, version: ModelVersion) -> bool:
        model_key = f"model:{version.model_id}"
        version_key = f"version:{version.version_id}"
        versions_key = f"versions:{version.model_id}"

        with self.client.pipeline() as pipe:
            while True:
                try:
                    # Monitor all keys relevant to this operation.
                    pipe.watch(model_key, version_key, versions_key)

                    # Verify the parent model still exists.
                    if not pipe.exists(model_key):
                        pipe.unwatch()
                        raise ValueError("Parent model does not exist")

                    # Prevent duplicate version IDs.
                    if pipe.exists(version_key):
                        pipe.unwatch()
                        return False

                    pipe.multi()

                    pipe.hset(
                        version_key,
                        mapping=version.model_dump(),
                    )

                    pipe.sadd(versions_key, version.version_id)

                    pipe.execute()
                    return True

                except redis.WatchError:
                    # Retry if another transaction changed a watched key.
                    continue
              

    def list_versions(self, model_id: str) -> list[ModelVersion]:
        if self.get_model(model_id) is None:
            raise ValueError("Model does not exist")

        version_ids = self.client.smembers(
            f"versions:{model_id}"
        )

        versions = []

        for version_id in version_ids:
            data = self.client.hgetall(f"version:{version_id}")

            if data:
                versions.append(ModelVersion.model_validate(data))

        return sorted(versions, key=lambda v: v.version_id)

    
    def _update_hash(self, key: str, updates: dict, schema):
        """Atomically apply ``updates`` to an existing Hash.

        WATCH + MULTI/EXEC guarantees the HSET only commits if the Hash
        still exists unchanged since it was read, so a concurrent delete
        can never be undone by recreating a partial record. The returned
        object is built from the watched snapshot plus our updates, i.e.
        exactly the state this transaction committed (re-reading after
        EXEC could observe a later delete or update instead).
        """
        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(key)

                    data = pipe.hgetall(key)

                    if not data:
                        pipe.unwatch()
                        return None

                    if updates:
                        pipe.multi()
                        pipe.hset(key, mapping=updates)
                        pipe.execute()
                    else:
                        pipe.unwatch()

                    return schema.model_validate({**data, **updates})

                except redis.WatchError:
                    # The Hash changed (or was deleted); re-check and retry.
                    continue

    def update_model(
        self,
        model_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> Model | None:
        updates = {}

        if name is not None:
            updates["name"] = name

        if description is not None:
            updates["description"] = description

        return self._update_hash(f"model:{model_id}", updates, Model)

    def archive_model(self, model_id: str) -> Model | None:
        return self._update_hash(
            f"model:{model_id}", {"status": "archived"}, Model
        )

    def update_version(
        self,
        version_id: str,
        version_label: str,
    ) -> ModelVersion | None:
        return self._update_hash(
            f"version:{version_id}",
            {"version_label": version_label},
            ModelVersion,
        )

    def archive_version(
        self,
        version_id: str,
    ) -> ModelVersion | None:
        return self._update_hash(
            f"version:{version_id}", {"status": "archived"}, ModelVersion
        )

    def delete_version(self, version_id: str) -> bool:
        version_key = f"version:{version_id}"
        used_key = f"version-used:{version_id}"
        stream_key = f"events:{version_id}"

        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(version_key, used_key, stream_key)

                    data = pipe.hgetall(version_key)

                    if not data:
                        pipe.unwatch()
                        return False

                    # Never delete a version with event history.
                    if pipe.exists(used_key) or pipe.exists(stream_key):
                        pipe.unwatch()
                        raise ValueError(
                            "Cannot delete a version with inference history"
                        )

                    versions_key = f"versions:{data['model_id']}"

                    pipe.multi()
                    pipe.delete(version_key)
                    pipe.srem(versions_key, version_id)
                    pipe.execute()

                    return True

                except redis.WatchError:
                    continue

    
    def delete_model(self, model_id: str) -> bool:
        model_key = f"model:{model_id}"
        versions_key = f"versions:{model_id}"
        used_key = f"model-used:{model_id}"

        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(model_key, versions_key, used_key)

                    if not pipe.exists(model_key):
                        pipe.unwatch()
                        return False

                    # Cannot delete models with versions.
                    if pipe.scard(versions_key) > 0:
                        pipe.unwatch()
                        raise ValueError(
                            "Cannot delete a model with versions"
                        )

                    # Preserve models that have inference history.
                    if pipe.exists(used_key):
                        pipe.unwatch()
                        raise ValueError(
                            "Cannot delete a model with inference history"
                        )

                    pipe.multi()
                    pipe.delete(model_key)
                    pipe.delete(versions_key)
                    pipe.execute()

                    return True

                except redis.WatchError:
                    continue





