"""
Docker SDK を使ったコンテナ管理サービス

責務:
- MCPサーバーコンテナの起動 / 停止 / 削除 / 一覧
- 固定 IP の割り当て・管理
- Squid ホワイトリスト / ACL の動的更新
- サーバー設定 JSON の永続化
"""
from __future__ import annotations

import json
import logging
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import docker
from docker.errors import NotFound, APIError

from control_plane.config import (
    CONTAINER_SECURITY,
    DATA_DIR,
    MCP_BASE_IMAGE,
    MCP_NETWORK_NAME,
    MCP_SUBNET_PREFIX,
    MCP_IP_START_OFFSET,
    REGISTRY_URL,
    SERVER_CONFIGS_DIR,
    SQUID_CONF_PATH,
    SQUID_CONTAINER_NAME,
    SQUID_WHITELIST_DIR,
)
from control_plane.models.server import ServerConfig
from control_plane.models.container import ContainerInfo, ContainerStatus

logger = logging.getLogger(__name__)


class ContainerManager:
    """Docker コンテナのライフサイクル管理"""

    def __init__(self) -> None:
        self._client = docker.from_env()
        # 設定ディレクトリがなければ作成
        SERVER_CONFIGS_DIR.mkdir(parents=True, exist_ok=True)
        SQUID_WHITELIST_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # サーバー設定 JSON の永続化
    # ------------------------------------------------------------------

    def _config_path(self, name: str) -> Path:
        return SERVER_CONFIGS_DIR / f"{name}.json"

    def save_config(self, config: ServerConfig) -> None:
        """サーバー設定を JSON で永続化"""
        self._config_path(config.name).write_text(
            config.model_dump_json(indent=2), encoding="utf-8"
        )

    def load_config(self, name: str) -> ServerConfig | None:
        """保存済みのサーバー設定を読み込む"""
        path = self._config_path(name)
        if not path.exists():
            return None
        return ServerConfig.model_validate_json(path.read_text(encoding="utf-8"))

    def list_configs(self) -> list[ServerConfig]:
        """全サーバー設定を返す"""
        configs: list[ServerConfig] = []
        for p in sorted(SERVER_CONFIGS_DIR.glob("*.json")):
            try:
                configs.append(
                    ServerConfig.model_validate_json(p.read_text(encoding="utf-8"))
                )
            except Exception:
                logger.warning("Invalid config: %s", p)
        return configs

    def delete_config(self, name: str) -> None:
        path = self._config_path(name)
        if path.exists():
            path.unlink()

    # ------------------------------------------------------------------
    # IP 割り当て
    # ------------------------------------------------------------------

    def _used_ips(self) -> set[str]:
        return {c.ip for c in self.list_configs() if c.ip}

    def allocate_ip(self) -> str:
        """未使用の固定 IP を割り当てる"""
        used = self._used_ips()
        for offset in range(MCP_IP_START_OFFSET, 250):
            ip = f"{MCP_SUBNET_PREFIX}.{offset}"
            if ip not in used:
                return ip
        raise RuntimeError("利用可能な IP アドレスがありません")

    # ------------------------------------------------------------------
    # コンテナ一覧 / 詳細
    # ------------------------------------------------------------------

    def _container_name(self, name: str) -> str:
        return f"mcp-{name}"

    def list_containers(self) -> list[ContainerInfo]:
        """登録済みの全 MCP サーバーのコンテナ情報を返す"""
        configs = self.list_configs()
        results: list[ContainerInfo] = []
        for cfg in configs:
            results.append(self._get_container_info(cfg))
        return results

    def get_container(self, name: str) -> ContainerInfo | None:
        """単一コンテナの情報を取得"""
        cfg = self.load_config(name)
        if cfg is None:
            return None
        return self._get_container_info(cfg)

    def _get_container_info(self, cfg: ServerConfig) -> ContainerInfo:
        """Docker API から実際のコンテナ状態を取得し ContainerInfo に詰める"""
        cname = self._container_name(cfg.name)
        info = ContainerInfo(
            name=cfg.name,
            ip=cfg.ip,
            whitelist=cfg.whitelist,
        )
        try:
            container = self._client.containers.get(cname)
            info.status = self._map_status(container.status)
            info.image = str(container.image.tags[0]) if container.image.tags else ""
            # Docker の created 属性は ISO 文字列
            created = container.attrs.get("Created", "")
            if created:
                info.created_at = datetime.fromisoformat(
                    created.replace("Z", "+00:00")
                )
        except NotFound:
            info.status = ContainerStatus.STOPPED
        except Exception as exc:
            logger.warning("Container inspect error (%s): %s", cname, exc)
            info.status = ContainerStatus.ERROR
            info.error = str(exc)
        return info

    @staticmethod
    def _map_status(docker_status: str) -> ContainerStatus:
        mapping = {
            "running": ContainerStatus.RUNNING,
            "exited": ContainerStatus.STOPPED,
            "created": ContainerStatus.STOPPED,
            "paused": ContainerStatus.STOPPED,
            "restarting": ContainerStatus.RUNNING,
            "removing": ContainerStatus.STOPPED,
            "dead": ContainerStatus.ERROR,
        }
        return mapping.get(docker_status, ContainerStatus.ERROR)

    # ------------------------------------------------------------------
    # コンテナ起動 / 停止 / 削除
    # ------------------------------------------------------------------

    def start_container(self, name: str) -> ContainerInfo:
        """既存イメージからコンテナを起動（なければ作成）"""
        cfg = self.load_config(name)
        if cfg is None:
            raise ValueError(f"サーバー設定が見つかりません: {name}")

        cname = self._container_name(name)

        # 既にコンテナが存在する場合は start
        try:
            container = self._client.containers.get(cname)
            if container.status != "running":
                container.start()
            return self._get_container_info(cfg)
        except NotFound:
            pass

        # イメージ名の決定
        image = cfg.image_tag or f"{REGISTRY_URL}/mcp-{name}:latest"

        # セキュリティ設定
        sec = CONTAINER_SECURITY.copy()

        networking_config = self._client.api.create_networking_config({
            MCP_NETWORK_NAME: self._client.api.create_endpoint_config(
                ipv4_address=cfg.ip,
            )
        })

        environment = {
            "HTTP_PROXY": "http://mcp-squid:3128",
            "HTTPS_PROXY": "http://mcp-squid:3128",
            "NO_PROXY": "localhost,127.0.0.1",
        }

        try:
            self._client.api.create_container(
                image=image,
                name=cname,
                user=sec.pop("user"),
                stdin_open=True,
                environment=environment,
                host_config=self._client.api.create_host_config(
                    read_only=sec.pop("read_only", True),
                    cap_drop=sec.get("cap_drop", []),
                    security_opt=sec.get("security_opt", []),
                    mem_limit=sec.get("mem_limit"),
                    cpu_quota=sec.get("cpu_quota"),
                    pids_limit=sec.get("pids_limit"),
                    tmpfs=sec.get("tmpfs"),
                    restart_policy={"Name": "unless-stopped"},
                ),
                networking_config=networking_config,
            )
            self._client.api.start(cname)
        except APIError as exc:
            logger.error("Container start failed (%s): %s", name, exc)
            raise

        return self._get_container_info(cfg)

    def stop_container(self, name: str) -> ContainerInfo:
        cfg = self.load_config(name)
        if cfg is None:
            raise ValueError(f"サーバー設定が見つかりません: {name}")
        cname = self._container_name(name)
        try:
            container = self._client.containers.get(cname)
            container.stop(timeout=10)
        except NotFound:
            pass
        return self._get_container_info(cfg)

    def remove_container(self, name: str) -> None:
        """コンテナ + 設定 + ホワイトリストを完全削除"""
        cname = self._container_name(name)
        try:
            container = self._client.containers.get(cname)
            container.remove(force=True)
        except NotFound:
            pass

        # Squid ホワイトリスト削除
        wl_path = SQUID_WHITELIST_DIR / f"{name}.txt"
        if wl_path.exists():
            wl_path.unlink()

        # 設定 JSON 削除
        self.delete_config(name)

        # squid.conf から ACL を削除して reload
        self._rebuild_squid_conf()

    # ------------------------------------------------------------------
    # コンテナログ
    # ------------------------------------------------------------------

    def get_logs(self, name: str, tail: int = 100) -> str:
        cname = self._container_name(name)
        try:
            container = self._client.containers.get(cname)
            return container.logs(tail=tail).decode("utf-8", errors="replace")
        except NotFound:
            return ""

    # ------------------------------------------------------------------
    # Squid ホワイトリスト管理
    # ------------------------------------------------------------------

    def get_whitelist(self, name: str) -> list[str]:
        cfg = self.load_config(name)
        return cfg.whitelist if cfg else []

    def set_whitelist(self, name: str, domains: list[str]) -> None:
        """ホワイトリストを更新し Squid を reload"""
        cfg = self.load_config(name)
        if cfg is None:
            raise ValueError(f"サーバー設定が見つかりません: {name}")

        cfg.whitelist = domains
        self.save_config(cfg)

        # ホワイトリストファイル書き出し
        wl_path = SQUID_WHITELIST_DIR / f"{name}.txt"
        wl_path.write_text("\n".join(domains) + "\n", encoding="utf-8")

        # squid.conf 再構築 & reload
        self._rebuild_squid_conf()

    def add_whitelist_domain(self, name: str, domain: str) -> list[str]:
        domains = self.get_whitelist(name)
        if domain not in domains:
            domains.append(domain)
            self.set_whitelist(name, domains)
        return domains

    def remove_whitelist_domain(self, name: str, domain: str) -> list[str]:
        domains = self.get_whitelist(name)
        if domain in domains:
            domains.remove(domain)
            self.set_whitelist(name, domains)
        return domains

    # ------------------------------------------------------------------
    # squid.conf 再構築
    # ------------------------------------------------------------------

    def _rebuild_squid_conf(self) -> None:
        """全サーバー設定から squid.conf を再生成し Squid を reload"""
        configs = self.list_configs()

        acl_lines: list[str] = []
        access_lines: list[str] = []

        for cfg in configs:
            if not cfg.whitelist:
                continue
            acl_name = f"mcp_{cfg.name}"
            wl_name = f"whitelist_{cfg.name}"
            acl_lines.append(f"acl {acl_name} src {cfg.ip}")
            acl_lines.append(
                f'acl {wl_name} dstdomain "/etc/squid/whitelist/{cfg.name}.txt"'
            )
            access_lines.append(f"http_access allow {acl_name} {wl_name}")

        conf = textwrap.dedent("""\
            http_port 3128

            # ===== 動的生成 ACL =====
            {acls}

            # ===== アクセス制御 =====
            {access}

            # デフォルト拒否
            http_access deny all

            # ログ設定
            access_log /var/log/squid/access.log
            cache_log /var/log/squid/cache.log
            cache deny all
        """).format(
            acls="\n".join(acl_lines) if acl_lines else "# (なし)",
            access="\n".join(access_lines) if access_lines else "# (なし)",
        )

        SQUID_CONF_PATH.write_text(conf, encoding="utf-8")

        # Squid reload（コンテナ内で squid -k reconfigure）
        self._reload_squid()

    def _reload_squid(self) -> None:
        try:
            squid = self._client.containers.get(SQUID_CONTAINER_NAME)
            squid.exec_run("squid -k reconfigure")
            logger.info("Squid reconfigured")
        except NotFound:
            logger.warning("Squid container not found — skip reload")
        except Exception as exc:
            logger.warning("Squid reload failed: %s", exc)

    # ------------------------------------------------------------------
    # コード / イメージ管理（Phase 3 ビルドパイプラインが使用）
    # ------------------------------------------------------------------

    def get_server_code(self, name: str) -> str:
        """保存済みのサーバーコードを返す"""
        cfg = self.load_config(name)
        return cfg.code if cfg else ""

    def update_server_code(self, name: str, code: str) -> None:
        """サーバーコードを更新（再ビルドは別途トリガー）"""
        cfg = self.load_config(name)
        if cfg is None:
            raise ValueError(f"サーバー設定が見つかりません: {name}")
        cfg.code = code
        self.save_config(cfg)
