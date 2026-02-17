"""
コンテナ操作 API エンドポイント

GET    /api/containers                          コンテナ一覧
GET    /api/containers/{name}                   コンテナ詳細
POST   /api/containers/{name}/start             コンテナ起動
POST   /api/containers/{name}/stop              コンテナ停止
DELETE /api/containers/{name}                   コンテナ削除
GET    /api/containers/{name}/logs              ログ取得
GET    /api/containers/{name}/code              コード取得
PUT    /api/containers/{name}/code              コード更新
GET    /api/containers/{name}/whitelist         ホワイトリスト取得
POST   /api/containers/{name}/whitelist         ドメイン追加
DELETE /api/containers/{name}/whitelist/{domain} ドメイン削除
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.services.container_manager import ContainerManager

router = APIRouter(prefix="/containers", tags=["containers"])

# シングルトン（main.py の lifespan で差し替え可能）
_manager: ContainerManager | None = None


def get_manager() -> ContainerManager:
    global _manager
    if _manager is None:
        _manager = ContainerManager()
    return _manager


# ------------------------------------------------------------------
# Request / Response スキーマ
# ------------------------------------------------------------------

class WhitelistAddRequest(BaseModel):
    domain: str


class CodeUpdateRequest(BaseModel):
    code: str


# ------------------------------------------------------------------
# コンテナ一覧 / 詳細
# ------------------------------------------------------------------

@router.get("")
async def list_containers():
    """登録済みMCPサーバーコンテナの一覧"""
    mgr = get_manager()
    return [c.model_dump() for c in mgr.list_containers()]


@router.get("/{name}")
async def get_container(name: str):
    """単一コンテナの詳細"""
    mgr = get_manager()
    info = mgr.get_container(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Container not found: {name}")
    return info.model_dump()


# ------------------------------------------------------------------
# 起動 / 停止 / 削除
# ------------------------------------------------------------------

@router.post("/{name}/start")
async def start_container(name: str):
    """コンテナを起動"""
    mgr = get_manager()
    try:
        info = mgr.start_container(name)
        return info.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.post("/{name}/stop")
async def stop_container(name: str):
    """コンテナを停止"""
    mgr = get_manager()
    try:
        info = mgr.stop_container(name)
        return info.model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{name}")
async def remove_container(name: str):
    """コンテナと設定を完全削除"""
    mgr = get_manager()
    mgr.remove_container(name)
    return {"detail": f"Removed: {name}"}


# ------------------------------------------------------------------
# ログ
# ------------------------------------------------------------------

@router.get("/{name}/logs")
async def get_logs(name: str, tail: int = 100):
    """コンテナログを取得"""
    mgr = get_manager()
    logs = mgr.get_logs(name, tail=tail)
    return {"name": name, "logs": logs}


# ------------------------------------------------------------------
# コード
# ------------------------------------------------------------------

@router.get("/{name}/code")
async def get_code(name: str):
    """サーバーコードを取得"""
    mgr = get_manager()
    code = mgr.get_server_code(name)
    return {"name": name, "code": code}


@router.put("/{name}/code")
async def update_code(name: str, body: CodeUpdateRequest):
    """サーバーコードを更新（再ビルドは Phase 3 で実装）"""
    mgr = get_manager()
    try:
        mgr.update_server_code(name, body.code)
        return {"name": name, "detail": "Code updated"}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ------------------------------------------------------------------
# ホワイトリスト
# ------------------------------------------------------------------

@router.get("/{name}/whitelist")
async def get_whitelist(name: str):
    """ホワイトリストを取得"""
    mgr = get_manager()
    domains = mgr.get_whitelist(name)
    return {"name": name, "whitelist": domains}


@router.post("/{name}/whitelist")
async def add_whitelist(name: str, body: WhitelistAddRequest):
    """ドメインを追加"""
    mgr = get_manager()
    try:
        domains = mgr.add_whitelist_domain(name, body.domain)
        return {"name": name, "whitelist": domains}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.delete("/{name}/whitelist/{domain}")
async def remove_whitelist(name: str, domain: str):
    """ドメインを削除"""
    mgr = get_manager()
    try:
        domains = mgr.remove_whitelist_domain(name, domain)
        return {"name": name, "whitelist": domains}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
