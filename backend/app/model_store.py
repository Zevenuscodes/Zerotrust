"""Storage abstraction for per-user trained risk models.

Two backends share one interface so the risk engine code never changes
between local development and an AWS deployment:
  - LocalDiskModelStore: pickles to a local directory (dev / no AWS access needed)
  - S3ModelStore: pickles to an S3 bucket (prod, selected via MODEL_STORE=s3)
"""

import io
import os
import pickle
from abc import ABC, abstractmethod
from typing import Optional, Any

from app.config import settings


class ModelStore(ABC):
    @abstractmethod
    def load(self, user_id: str) -> Optional[Any]:
        ...

    @abstractmethod
    def save(self, user_id: str, model: Any) -> None:
        ...


class LocalDiskModelStore(ModelStore):
    def __init__(self, directory: str):
        self.directory = directory
        os.makedirs(directory, exist_ok=True)

    def _path(self, user_id: str) -> str:
        return os.path.join(self.directory, f"{user_id}.pkl")

    def load(self, user_id: str) -> Optional[Any]:
        path = self._path(user_id)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            return pickle.load(f)

    def save(self, user_id: str, model: Any) -> None:
        with open(self._path(user_id), "wb") as f:
            pickle.dump(model, f)


class S3ModelStore(ModelStore):
    def __init__(self, bucket: str, region: str):
        import boto3

        self.bucket = bucket
        self.client = boto3.client("s3", region_name=region)

    def _key(self, user_id: str) -> str:
        return f"risk-models/{user_id}.pkl"

    def load(self, user_id: str) -> Optional[Any]:
        try:
            obj = self.client.get_object(Bucket=self.bucket, Key=self._key(user_id))
            return pickle.load(io.BytesIO(obj["Body"].read()))
        except self.client.exceptions.NoSuchKey:
            return None
        except Exception:
            return None

    def save(self, user_id: str, model: Any) -> None:
        buf = io.BytesIO()
        pickle.dump(model, buf)
        buf.seek(0)
        self.client.put_object(Bucket=self.bucket, Key=self._key(user_id), Body=buf.read())


def get_model_store() -> ModelStore:
    if settings.model_store == "s3":
        return S3ModelStore(settings.model_store_s3_bucket, settings.model_store_s3_region)
    return LocalDiskModelStore(settings.model_store_local_dir)


model_store = get_model_store()
