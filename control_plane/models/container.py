"""
コンテナ状態モデル
"""
from __future__ import annotations

from enum import Enum
from datetime import datetime
from pydantic import BaseModel, Field


class ContainerStatus(str, Enum):
    """コンテナのステータス"""
    RUNNING = "running"
    STOPPED = "stopped"
    BUILDING = "building"
    ERROR = "error"
    NOT_FOUND = "not_found"


class ContainerInfo(BaseModel):
    """コンテナの現在の状態（Docker API から動的に取得）"""

    name: str
    status: ContainerStatus = ContainerStatus.NOT_FOUND
    ip: str = ""
    image: str = ""
    created_at: datetime | None = None
    tools: list[str] = Field(default_factory=list, description="公開しているMCPツール名")
    whitelist: list[str] = Field(default_factory=list, description="許可ドメイン")
    error: str = ""
