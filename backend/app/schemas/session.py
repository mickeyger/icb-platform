"""Session / active-branch schemas (WO v4.16, ADR 0010)."""
from typing import List, Optional

from pydantic import BaseModel, ConfigDict


class BranchInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    code: str
    name: str


class UserInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    role: Optional[str] = None


class SessionInfo(BaseModel):
    user: UserInfo
    active_branch: Optional[BranchInfo] = None       # default JHB for display (ADR 0010)
    accessible_branches: List[BranchInfo] = []
    permissions: List[str] = []                      # effective permission keys (WO v4.17; admin = all)


class BranchSwitchRequest(BaseModel):
    model_config = ConfigDict(json_schema_extra={"example": {"branch_id": 2}})
    branch_id: int
