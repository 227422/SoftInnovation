"""Follow payloads; starred is the target state, never a toggle."""
from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt


class FollowUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    starred: StrictBool
    expected_version: StrictInt | None = None


class FollowView(BaseModel):
    notice_id: str
    starred: bool
    followed_at: str | None = None
    version: int
