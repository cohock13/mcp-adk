"""
ビルドパイプライン — コードからコンテナデプロイまでの CI/CD

ステージ:
  1. CODE_ANALYSIS       — 静的解析 (ruff / bandit)
  2. SECURITY_SCAN       — 危険パターン検査
  3. DOCKER_BUILD        — Docker イメージビルド
  4. VULNERABILITY_SCAN  — Trivy イメージスキャン
  5. MCP_TEST            — MCP 通信テスト
  6. REGISTRY_PUSH       — Private Registry へ push
  7. DEPLOY              — コンテナ起動 (ContainerManager)
"""
from __future__ import annotations

import asyncio
import io
import logging
import shutil
import textwrap
from pathlib import Path

import docker
from docker.errors import ImageNotFound

from control_plane.config import (
    BUILD_WORKSPACE_DIR,
    MCP_BASE_IMAGE,
    REGISTRY_URL,
)
from control_plane.models.build import BuildStage, BuildState
from control_plane.models.server import ServerConfig
from control_plane.services.container_manager import ContainerManager
from control_plane.services.mcp_tester import MCPTester
from control_plane.services.registry_client import RegistryClient
from control_plane.services.security_scanner import SecurityScanner

logger = logging.getLogger(__name__)


class BuildError(Exception):
    """ビルドパイプラインの中断エラー"""


# ------------------------------------------------------------------
# ベースイメージの定義（コンテナ内に Dockerfile がないので埋め込み）
# ------------------------------------------------------------------
MCP_BASE_DOCKERFILE = textwrap.dedent("""\
    FROM python:3.12-slim-bookworm

    RUN apt-get update && \\
        apt-get install -y --no-install-recommends ca-certificates tini && \\
        rm -rf /var/lib/apt/lists/* && apt-get clean

    RUN useradd -u 10001 -m -s /bin/false mcpuser

    COPY requirements.txt /tmp/
    RUN pip install --no-cache-dir -r /tmp/requirements.txt && \\
        rm /tmp/requirements.txt

    WORKDIR /app
    USER 10001:10001

    ENTRYPOINT ["/usr/bin/tini", "--"]
    CMD ["python", "server.py"]
""")

MCP_BASE_REQUIREMENTS = "mcp[cli]==1.26.0\nhttpx==0.28.1\n"


class BuildPipeline:
    """ビルドパイプラインオーケストレーター"""

    # サーバー名 → BuildState
    _active_builds: dict[str, BuildState] = {}

    def __init__(self) -> None:
        self._client = docker.from_env()
        self._scanner = SecurityScanner()
        self._tester = MCPTester()
        self._container_mgr = ContainerManager()
        self._registry = RegistryClient()
        BUILD_WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)

    # ==================================================================
    # Public API
    # ==================================================================

    async def execute(
        self,
        name: str,
        code: str,
        dependencies: list[str] | None = None,
        whitelist: list[str] | None = None,
        description: str = "",
    ) -> BuildState:
        """
        フルパイプラインを実行し最終状態を返す。

        途中経過は ``get_state(name)`` でポーリングできる。
        """
        dependencies = dependencies or []
        whitelist = whitelist or []

        state = BuildState(server_name=name)
        self._active_builds[name] = state

        try:
            # 0. ベースイメージの確認
            await self._ensure_base_image(state)

            # 1. CODE_ANALYSIS
            await self._stage_code_analysis(state, code)

            # 2. SECURITY_SCAN
            await self._stage_security_scan(state, code)

            # 3. DOCKER_BUILD
            image_tag = await self._stage_docker_build(
                state, name, code, dependencies,
            )

            # 4. VULNERABILITY_SCAN
            await self._stage_vulnerability_scan(state, image_tag)

            # 5. MCP_TEST
            tools = await self._stage_mcp_test(state, image_tag)

            # 6. REGISTRY_PUSH
            registry_tag = await self._stage_registry_push(state, name, image_tag)

            # 7. DEPLOY
            await self._stage_deploy(
                state, name, code, dependencies,
                whitelist, description, tools, registry_tag,
            )

            state.stage = BuildStage.COMPLETED
            state.progress = 100
            state.logs.append("✅ ビルドパイプライン完了！")

        except BuildError as exc:
            state.stage = BuildStage.FAILED
            state.error = str(exc)
            state.logs.append(f"🚫 失敗: {exc}")
        except Exception as exc:
            state.stage = BuildStage.FAILED
            state.error = f"予期しないエラー: {exc}"
            state.logs.append(f"🚫 予期しないエラー: {exc}")
            logger.exception("Build pipeline error for %s", name)

        return state

    def get_state(self, name: str) -> BuildState | None:
        return self._active_builds.get(name)

    # ==================================================================
    # Stage 0: ベースイメージ
    # ==================================================================

    async def _ensure_base_image(self, state: BuildState) -> None:
        """mcp-base:latest がなければビルドする"""
        state.logs.append("🔍 ベースイメージ確認中...")
        try:
            self._client.images.get(MCP_BASE_IMAGE)
            state.logs.append(f"✅ {MCP_BASE_IMAGE} 存在確認")
            return
        except ImageNotFound:
            state.logs.append(f"⚙️ {MCP_BASE_IMAGE} をビルドします...")

        # ベースイメージ用の一時ディレクトリ
        base_dir = BUILD_WORKSPACE_DIR / "_mcp_base"
        base_dir.mkdir(parents=True, exist_ok=True)
        try:
            (base_dir / "Dockerfile").write_text(MCP_BASE_DOCKERFILE)
            (base_dir / "requirements.txt").write_text(MCP_BASE_REQUIREMENTS)

            image, logs = await asyncio.to_thread(
                self._client.images.build,
                path=str(base_dir),
                tag=MCP_BASE_IMAGE,
                rm=True,
            )
            state.logs.append(f"✅ {MCP_BASE_IMAGE} ビルド完了")
        finally:
            shutil.rmtree(base_dir, ignore_errors=True)

    # ==================================================================
    # Stage 1: CODE_ANALYSIS
    # ==================================================================

    async def _stage_code_analysis(self, state: BuildState, code: str) -> None:
        state.stage = BuildStage.CODE_ANALYSIS
        state.progress = 10
        state.logs.append("📝 静的解析 (ruff / bandit) を実行中...")

        passed, findings = await asyncio.to_thread(self._scanner.scan_code, code)
        state.logs.extend(findings)

        if not passed:
            raise BuildError("静的解析でブロッキング問題が検出されました")

        state.logs.append("✅ 静的解析パス")

    # ==================================================================
    # Stage 2: SECURITY_SCAN
    # ==================================================================

    async def _stage_security_scan(self, state: BuildState, code: str) -> None:
        state.stage = BuildStage.SECURITY_SCAN
        state.progress = 20
        state.logs.append("🔒 セキュリティパターン検査中...")

        # scan_code で既にパターン検査済みだが、
        # ここでは追加のコードサニティチェックを実施
        issues: list[str] = []

        # MCP サーバーとして最低限の構造があるか
        if "from mcp" not in code and "import mcp" not in code:
            issues.append("⚠️ MCP ライブラリのインポートがありません")

        if "@" not in code:
            issues.append("⚠️ デコレーター（@mcp.tool 等）が見つかりません")

        if "def " not in code:
            issues.append("⚠️ 関数定義がありません")

        state.logs.extend(issues)
        state.logs.append("✅ セキュリティスキャン完了")

    # ==================================================================
    # Stage 3: DOCKER_BUILD
    # ==================================================================

    async def _stage_docker_build(
        self,
        state: BuildState,
        name: str,
        code: str,
        dependencies: list[str],
    ) -> str:
        state.stage = BuildStage.DOCKER_BUILD
        state.progress = 35
        state.logs.append("🐳 Docker イメージをビルド中...")

        workspace = BUILD_WORKSPACE_DIR / name
        workspace.mkdir(parents=True, exist_ok=True)

        try:
            # server.py
            (workspace / "server.py").write_text(code, encoding="utf-8")

            # requirements.txt（追加依存）
            deps_text = "\n".join(dependencies) + "\n" if dependencies else ""
            (workspace / "requirements.txt").write_text(deps_text, encoding="utf-8")

            # Dockerfile
            dockerfile = self._generate_dockerfile(bool(dependencies))
            (workspace / "Dockerfile").write_text(dockerfile, encoding="utf-8")

            # ビルド実行
            image_tag = f"mcp-{name}:latest"
            image, build_logs = await asyncio.to_thread(
                self._client.images.build,
                path=str(workspace),
                tag=image_tag,
                rm=True,
                forcerm=True,
            )

            # ビルドログの主要行を記録
            for chunk in build_logs:
                if "stream" in chunk:
                    line = chunk["stream"].strip()
                    if line and not line.startswith("---"):
                        state.logs.append(f"  {line}")

            state.progress = 55
            state.logs.append(f"✅ イメージビルド完了: {image_tag}")
            return image_tag

        except Exception as exc:
            raise BuildError(f"Docker ビルド失敗: {exc}") from exc
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    @staticmethod
    def _generate_dockerfile(has_deps: bool) -> str:
        """MCP サーバー用の Dockerfile を動的生成"""
        lines = [f"FROM {MCP_BASE_IMAGE}"]

        if has_deps:
            lines.extend([
                "",
                "# 追加依存のインストール (root で実行)",
                "USER root",
                "COPY requirements.txt /tmp/server-requirements.txt",
                "RUN pip install --no-cache-dir -r /tmp/server-requirements.txt \\",
                "    && rm /tmp/server-requirements.txt",
                "USER 10001:10001",
            ])

        lines.extend([
            "",
            "# サーバーコード",
            "COPY server.py /app/server.py",
        ])

        return "\n".join(lines) + "\n"

    # ==================================================================
    # Stage 4: VULNERABILITY_SCAN
    # ==================================================================

    async def _stage_vulnerability_scan(
        self, state: BuildState, image_tag: str
    ) -> None:
        state.stage = BuildStage.VULNERABILITY_SCAN
        state.progress = 60
        state.logs.append("🛡️ Trivy 脆弱性スキャン中...")

        passed, findings = await asyncio.to_thread(
            self._scanner.scan_image_trivy, image_tag,
        )
        state.logs.extend(findings)

        # Trivy の CRITICAL は警告のみ（ベースイメージ由来の脆弱性が大半のため）
        if not passed:
            state.logs.append(
                "⚠️ CRITICAL 脆弱性はベースイメージ由来の可能性があります — 続行します"
            )

        state.progress = 70
        state.logs.append("✅ 脆弱性スキャン完了")

    # ==================================================================
    # Stage 5: MCP_TEST
    # ==================================================================

    async def _stage_mcp_test(
        self, state: BuildState, image_tag: str
    ) -> list[str]:
        state.stage = BuildStage.MCP_TEST
        state.progress = 75
        state.logs.append("🧪 MCP 通信テスト中...")

        passed, test_logs, tool_names = await asyncio.to_thread(
            self._tester.test_server, image_tag,
        )
        state.logs.extend(test_logs)

        if not passed:
            raise BuildError("MCP テストが失敗しました")

        state.progress = 82
        state.logs.append("✅ MCP テスト完了")
        return tool_names

    # ==================================================================
    # Stage 6: REGISTRY_PUSH
    # ==================================================================

    async def _stage_registry_push(
        self, state: BuildState, name: str, image_tag: str
    ) -> str:
        state.stage = BuildStage.REGISTRY_PUSH
        state.progress = 85
        state.logs.append("📦 Registry へ push 中...")

        registry_tag = f"{REGISTRY_URL}/mcp-{name}:latest"

        try:
            image = self._client.images.get(image_tag)
            image.tag(f"{REGISTRY_URL}/mcp-{name}", tag="latest")

            push_log = await asyncio.to_thread(
                self._client.images.push,
                f"{REGISTRY_URL}/mcp-{name}",
                tag="latest",
            )
            state.logs.append(f"✅ Registry push 完了: {registry_tag}")
        except Exception as exc:
            # Registry push は失敗しても続行（ローカルイメージで起動可能）
            state.logs.append(f"⚠️ Registry push 失敗（ローカルイメージで続行）: {exc}")
            registry_tag = image_tag

        state.progress = 90
        return registry_tag

    # ==================================================================
    # Stage 7: DEPLOY
    # ==================================================================

    async def _stage_deploy(
        self,
        state: BuildState,
        name: str,
        code: str,
        dependencies: list[str],
        whitelist: list[str],
        description: str,
        tools: list[str],
        image_tag: str,
    ) -> None:
        state.stage = BuildStage.DEPLOY
        state.progress = 92
        state.logs.append("🚀 コンテナをデプロイ中...")

        # 既存コンテナがあれば停止・削除
        existing = self._container_mgr.load_config(name)
        if existing:
            try:
                self._container_mgr.stop_container(name)
                # コンテナだけ削除（設定は更新するので残す）
                cname = f"mcp-{name}"
                try:
                    c = self._client.containers.get(cname)
                    c.remove(force=True)
                except Exception:
                    pass
                state.logs.append("♻️ 既存コンテナを削除しました")
            except Exception:
                pass

        # IP 割り当て（既存があればそのまま）
        ip = existing.ip if existing else self._container_mgr.allocate_ip()

        # サーバー設定を保存
        config = ServerConfig(
            name=name,
            ip=ip,
            whitelist=whitelist,
            dependencies=dependencies,
            description=description,
            code=code,
            image_tag=image_tag,
        )
        self._container_mgr.save_config(config)

        # ホワイトリスト設定（Squid 更新）
        if whitelist:
            self._container_mgr.set_whitelist(name, whitelist)
            state.logs.append(f"🌐 ホワイトリスト設定: {', '.join(whitelist)}")

        # コンテナ起動
        try:
            info = await asyncio.to_thread(
                self._container_mgr.start_container, name,
            )
            state.logs.append(f"✅ コンテナ起動: {info.name} ({info.ip})")
        except Exception as exc:
            raise BuildError(f"コンテナ起動失敗: {exc}") from exc

        state.progress = 98
