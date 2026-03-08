"""
Cisco MCP Scanner API — コンテナごとのセキュリティスキャン

- POST  /api/containers/{name}/scan   Cisco mcp-scanner でスキャン実行
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from control_plane.models.scan import CiscoScanRequest, CiscoScanResponse
from control_plane.services.cisco_scanner import get_cisco_scanner
from control_plane.services.container_manager import ContainerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/containers", tags=["scan"])


@router.post(
    "/{name}/scan",
    response_model=CiscoScanResponse,
    summary="Cisco mcp-scanner でコンテナの MCP ツールをスキャン",
)
async def scan_container(name: str, body: CiscoScanRequest | None = None):
    """
    稼働中のコンテナの server.py コードを取得し、
    Cisco mcp-scanner (YARA アナライザー) でツールを動的にスキャンする。
    """
    mgr = ContainerManager()

    # コンテナの存在確認
    info = mgr.get_container(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"コンテナが見つかりません: {name}")

    # コード取得
    code = mgr.get_server_code(name)
    if not code:
        raise HTTPException(
            status_code=404,
            detail=f"サーバーコードが見つかりません: {name}",
        )

    # スキャナー取得
    use_api = body.use_api if body else False
    use_llm = body.use_llm if body else False
    scanner = get_cisco_scanner(use_api=use_api, use_llm=use_llm)

    # スキャン実行
    result = await scanner.scan_code(container_name=name, code=code)
    return result
