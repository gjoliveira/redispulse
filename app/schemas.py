
from typing import Literal
from pydantic import BaseModel, Field, model_validator


class Model(BaseModel):
    model_id: str
    name: str
    description: str
    created_at_ms: int
    status: Literal["active", "archived"] = "active"


class ModelVersion(BaseModel):
    version_id: str
    model_id: str
    version_label: str
    created_at_ms: int
    status: Literal["active", "archived"] = "active"



class InferenceEvent(BaseModel):
    request_id: str
    model_id: str
    version_id: str

    timestamp_ms: int

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)

    latency_ms: float = Field(ge=0)

    status: Literal["success", "error"]
    error_type: str | None = None
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_result(self):
        if self.status == "success":
            if self.error_type is not None:
                raise ValueError(
                    "Successful events cannot have an error type"
                )

        if self.status == "error":
            if self.error_type is None:
                raise ValueError(
                    "Failed events need an error type"
                )

        return self
