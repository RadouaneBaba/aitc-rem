"""Base class for every generated model.

`validate_assignment` is on deliberately. Pydantic does not validate mutation by
default, so `event.diff.urlChanged = {"from": ..., "to": ...}` quietly stores a
dict where a model belongs, and the failure surfaces much later as an
AttributeError in unrelated code. These models are the contract between four
components and two languages; letting a bad assignment through is the one thing
they must not do.

The per-model `extra="forbid"` that codegen emits merges with this rather than
replacing it.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class StrictModel(BaseModel):
    model_config = ConfigDict(validate_assignment=True)
