"""
プライベート Docker Registry クライアント

責務:
- イメージの push / pull / 一覧取得 / 削除
"""
from __future__ import annotations

import logging

import httpx

from control_plane.config import REGISTRY_URL

logger = logging.getLogger(__name__)


class RegistryClient:
    """Docker Registry HTTP API v2 クライアント"""

    def __init__(self, base_url: str | None = None) -> None:
        self._base = f"http://{base_url or REGISTRY_URL}"

    # ------------------------------------------------------------------
    # カタログ / タグ
    # ------------------------------------------------------------------

    async def list_repositories(self) -> list[str]:
        """Registry に存在するリポジトリ一覧"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._base}/v2/_catalog")
                resp.raise_for_status()
                return resp.json().get("repositories", [])
        except Exception as exc:
            logger.warning("Registry catalog error: %s", exc)
            return []

    async def list_tags(self, repository: str) -> list[str]:
        """指定リポジトリのタグ一覧"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(f"{self._base}/v2/{repository}/tags/list")
                resp.raise_for_status()
                return resp.json().get("tags", []) or []
        except Exception as exc:
            logger.warning("Registry tags error (%s): %s", repository, exc)
            return []

    async def image_exists(self, repository: str, tag: str = "latest") -> bool:
        """イメージが Registry に存在するか"""
        try:
            async with httpx.AsyncClient() as client:
                resp = await client.head(
                    f"{self._base}/v2/{repository}/manifests/{tag}",
                    headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
                )
                return resp.status_code == 200
        except Exception:
            return False

    async def delete_image(self, repository: str, tag: str = "latest") -> bool:
        """イメージを Registry から削除（digest 取得 → DELETE）"""
        try:
            async with httpx.AsyncClient() as client:
                # digest 取得
                resp = await client.head(
                    f"{self._base}/v2/{repository}/manifests/{tag}",
                    headers={"Accept": "application/vnd.docker.distribution.manifest.v2+json"},
                )
                if resp.status_code != 200:
                    return False
                digest = resp.headers.get("Docker-Content-Digest")
                if not digest:
                    return False
                # 削除
                del_resp = await client.delete(
                    f"{self._base}/v2/{repository}/manifests/{digest}"
                )
                return del_resp.status_code == 202
        except Exception as exc:
            logger.warning("Registry delete error (%s:%s): %s", repository, tag, exc)
            return False

    # ------------------------------------------------------------------
    # ヘルスチェック
    # ------------------------------------------------------------------

    async def health(self) -> bool:
        try:
            async with httpx.AsyncClient(timeout=3) as client:
                resp = await client.get(f"{self._base}/v2/")
                return resp.status_code == 200
        except Exception:
            return False
