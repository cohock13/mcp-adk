"""
MCP 通信テスター

責務:
- ビルド済みイメージから一時コンテナを起動
- server.py のインポート検証
- MCP ツール一覧の抽出
- コンテナのクリーンアップ
"""
from __future__ import annotations

import logging
import time

import docker
from docker.errors import NotFound

logger = logging.getLogger(__name__)


class MCPTester:
    """MCP サーバーイメージのスモークテスト"""

    def __init__(self) -> None:
        self._client = docker.from_env()

    def test_server(
        self,
        image_name: str,
        timeout: int = 15,
    ) -> tuple[bool, list[str], list[str]]:
        """
        MCP サーバーイメージをテスト実行。

        Parameters
        ----------
        image_name : str
            テスト対象の Docker イメージ名
        timeout : int
            起動待機秒数

        Returns
        -------
        (passed, logs, tool_names)
        """
        container_name = f"mcp-test-{int(time.time())}"
        logs: list[str] = []
        tool_names: list[str] = []
        container = None

        try:
            # テスト用コンテナを起動
            container = self._client.containers.run(
                image_name,
                name=container_name,
                stdin_open=True,
                detach=True,
                user="10001:10001",
                read_only=True,
                tmpfs={"/tmp": "size=64m,mode=1777"},
                mem_limit="256m",
                cpu_quota=50000,
            )
            logs.append(f"✅ テストコンテナ起動: {container_name}")

            # サーバー起動を待機
            time.sleep(min(timeout, 5))

            container.reload()
            if container.status != "running":
                container_log = container.logs().decode("utf-8", errors="replace")
                logs.append("🚫 コンテナがクラッシュしました")
                logs.append(f"ログ: {container_log[-500:]}")
                return False, logs, []

            logs.append("✅ コンテナ正常稼働中")

            # --- import テスト ---
            passed_import = self._test_import(container, logs)
            if not passed_import:
                return False, logs, []

            # --- ツール検出 ---
            tool_names = self._detect_tools(container, logs)

            logs.append("✅ MCP テスト完了")
            return True, logs, tool_names

        except Exception as exc:
            logs.append(f"🚫 テストエラー: {exc}")
            return False, logs, []

        finally:
            self._cleanup(container_name, logs)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _test_import(container, logs: list[str]) -> bool:
        """server.py がインポート可能かを検証"""
        exit_code, output = container.exec_run(
            [
                "python", "-c",
                "import importlib; importlib.import_module('server'); print('IMPORT_OK')",
            ],
            user="10001:10001",
            demux=True,
        )
        stdout = (output[0] or b"").decode("utf-8", errors="replace")
        stderr = (output[1] or b"").decode("utf-8", errors="replace")

        if "IMPORT_OK" in stdout:
            logs.append("✅ server.py のインポート成功")
            return True

        logs.append("🚫 server.py のインポート失敗")
        if stderr:
            logs.append(f"エラー: {stderr[-500:]}")
        return False

    @staticmethod
    def _detect_tools(container, logs: list[str]) -> list[str]:
        """AST 解析でデコレーター @mcp.tool() 付き関数名を抽出"""
        detect_script = """\
import ast, sys
try:
    with open('/app/server.py') as f:
        tree = ast.parse(f.read())
    tools = []
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            for deco in node.decorator_list:
                deco_src = ast.dump(deco)
                if 'tool' in deco_src.lower():
                    tools.append(node.name)
    print('TOOLS:' + ','.join(tools) if tools else 'TOOLS:none')
except Exception as e:
    print(f'TOOLS_ERR:{e}', file=sys.stderr)
    print('TOOLS:none')
"""
        exit_code, output = container.exec_run(
            ["python", "-c", detect_script],
            user="10001:10001",
            demux=True,
        )
        stdout = (output[0] or b"").decode("utf-8", errors="replace")
        tool_names: list[str] = []

        if "TOOLS:" in stdout:
            tools_str = stdout.split("TOOLS:")[1].strip()
            if tools_str and tools_str != "none":
                tool_names = [t.strip() for t in tools_str.split(",") if t.strip()]
                logs.append(f"✅ 検出ツール: {', '.join(tool_names)}")
            else:
                logs.append("⚠️ @mcp.tool() デコレーターが検出されませんでした")

        return tool_names

    def _cleanup(self, container_name: str, logs: list[str]) -> None:
        """テストコンテナを削除"""
        try:
            c = self._client.containers.get(container_name)
            c.remove(force=True)
            logs.append("🧹 テストコンテナを削除しました")
        except NotFound:
            pass
        except Exception as exc:
            logger.warning("Test container cleanup failed (%s): %s", container_name, exc)
