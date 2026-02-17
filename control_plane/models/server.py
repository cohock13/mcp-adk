"""
MCPサーバー定義 - メタデータ・設定の永続化モデル
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ServerConfig(BaseModel):
    """MCPサーバーの設定情報（data/server_configs/{name}.json に永続化）"""

    name: str = Field(..., description="サーバー名（コンテナ名の一部にもなる）")
    ip: str = Field(..., description="mcp-internal ネットワーク上の固定IP")
    whitelist: list[str] = Field(
        default_factory=list,
        description="外部アクセスを許可するドメインのリスト",
    )
    dependencies: list[str] = Field(
        default_factory=list,
        description="追加 pip パッケージ（例: numpy==2.0.0）",
    )
    description: str = Field(default="", description="サーバーの説明")
    code: str = Field(default="", description="server.py のソースコード")
    image_tag: str = Field(default="", description="Registry 上のイメージタグ")
