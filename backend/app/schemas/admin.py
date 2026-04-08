from typing import Any, List

from pydantic import BaseModel


class AdminTestCaseOut(BaseModel):
    id: str
    title: str
    area: str
    health: str
    status: str
    summary: str
    source_file: str
    source_test: str
    commands: List[str]
    covered_paths: List[str]


class AdminSuiteDashStatusOut(BaseModel):
    enabled: bool
    configured: bool
    base_url: str
    public_id_present: bool
    secret_key_present: bool
    contact_meta_path: str
    contact_sync_path: str
    contact_sync_method: str


class AdminSuiteDashMetaOut(BaseModel):
    data: Any
