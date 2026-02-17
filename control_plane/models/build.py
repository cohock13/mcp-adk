"""
ビルド状態モデル
"""
from __future__ import annotations

from enum import Enum
from pydantic import BaseModel, Field


class BuildStage(str, Enum):
    """ビルドパイプラインのステージ"""
    PENDING = "pending"
    CODE_ANALYSIS = "code_analysis"       # 静的解析
    SECURITY_SCAN = "security_scan"       # セキュリティスキャン
    DOCKER_BUILD = "docker_build"         # イメージビルド
    VULNERABILITY_SCAN = "vulnerability_scan"  # Trivy
    MCP_TEST = "mcp_test"                 # MCP通信テスト
    REGISTRY_PUSH = "registry_push"       # Registry push
    DEPLOY = "deploy"                     # コンテナ起動
    COMPLETED = "completed"
    FAILED = "failed"


class BuildState(BaseModel):
    """ビルドの進捗状態"""

    server_name: str
    stage: BuildStage = BuildStage.PENDING
    progress: int = Field(default=0, ge=0, le=100)
    logs: list[str] = Field(default_factory=list)
    error: str = ""
