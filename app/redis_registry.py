
import redis
from app.schemas import Model, ModelVersion


class RedisRegistry:
    def __init__(self, client: redis.Redis):
        self.client = client

    
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


    def get_model(self, model_id: str) -> Model | None:
        key = f"model:{model_id}"

        data = self.client.hgetall(key)

        if not data:
            return None

        return Model.model_validate(data)


    
    def create_version(self, version: ModelVersion) -> bool:
        # Check that the parent model exists.
        if self.get_model(version.model_id) is None:
            raise ValueError("Parent model does not exist")

        version_key = f"version:{version.version_id}"
        versions_key = f"versions:{version.model_id}"

        # Prevent duplicate version IDs.
        with self.client.pipeline() as pipe:
            while True:
                try:
                    pipe.watch(version_key)

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
                    # Another client changed the version
                    # between our check and transaction.
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

    
    def update_model(
        self,
        model_id: str,
        name: str | None = None,
        description: str | None = None,
    ) -> Model | None:
        key = f"model:{model_id}"

        if not self.client.exists(key):
            return None

        updates = {}

        if name is not None:
            updates["name"] = name

        if description is not None:
            updates["description"] = description

        if updates:
            self.client.hset(key, mapping=updates)

        return self.get_model(model_id)

    def archive_model(self, model_id: str) -> Model | None:
        key = f"model:{model_id}"

        if not self.client.exists(key):
            return None

        self.client.hset(key, "status", "archived")

        return self.get_model(model_id)

    
    def update_version(
        self,
        version_id: str,
        version_label: str,
    ) -> ModelVersion | None:
        key = f"version:{version_id}"

        if not self.client.exists(key):
            return None

        self.client.hset(key, "version_label", version_label)

        data = self.client.hgetall(key)
        return ModelVersion.model_validate(data)

    def archive_version(
        self,
        version_id: str,
    ) -> ModelVersion | None:
        key = f"version:{version_id}"

        if not self.client.exists(key):
            return None

        self.client.hset(key, "status", "archived")

        data = self.client.hgetall(key)
        return ModelVersion.model_validate(data)

    
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





