"""
Cisco MCP Scanner スキャン結果モデル
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ScanFinding(BaseModel):
    """個別の検出結果"""

    tool_name: str = Field(description="問題が検出されたMCPツール名")
    pattern: str = Field(description="脅威カテゴリ (threat_category)")
    description: str = Field(description="検出内容の要約")
    severity: str = Field(description="深刻度: HIGH / MEDIUM / LOW")
    analyzer: str = Field(default="mcp-scanner", description="検出したアナライザー名")
    details: Any = Field(default=None, description="追加詳細情報")


class CiscoScanRequest(BaseModel):
    """スキャンリクエスト（オプション）"""

    use_api: bool = Field(default=False, description="Cisco AI Defense API を使用するか")
    use_llm: bool = Field(default=False, description="LLM アナライザーを使用するか")


class CiscoScanResponse(BaseModel):
    """スキャンレスポンス"""

    container_name: str
    is_safe: bool
    severity: str = Field(description="総合判定: SAFE / LOW / MEDIUM / HIGH")
    findings: list[ScanFinding] = Field(default_factory=list)
    summary: str = Field(description="日本語サマリー")
    raw_results: list[dict] | None = Field(
        default=None, description="生のスキャン結果JSON"
    )
