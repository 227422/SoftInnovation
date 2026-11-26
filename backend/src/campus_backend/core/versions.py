"""Wire types for versions backed by signed 64-bit counters."""
from typing import Annotated

from pydantic import Field, StrictInt

_MAX_VERSION = 9_223_372_036_854_775_807
Version = Annotated[int, Field(ge=0, le=_MAX_VERSION, json_schema_extra={"format": "int64"})]
# Leave room to increment the submitted version on an accepted write.
ExpectedVersion = Annotated[StrictInt, Field(ge=0, le=_MAX_VERSION - 1, json_schema_extra={"format": "int64"})]
