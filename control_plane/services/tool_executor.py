"""
MCP ツール実行サービス — コンテナ内のツールを Gemini Function Calling 経由で利用

- 稼働中コンテナのツール情報を収集し Gemini FunctionDeclaration に変換
- Docker exec でコンテナ内のツール関数を実行
"""
from __future__ import annotations

import json
import logging
from typing import Any

import docker
from docker.errors import NotFound
from google.genai import types

from control_plane.services.container_manager import ContainerManager
from control_plane.api.test import _parse_tools_from_code

logger = logging.getLogger(__name__)

# Python 型 → Gemini Schema Type
_TYPE_MAP = {
    "str": "STRING",
    "int": "INTEGER",
    "float": "NUMBER",
    "bool": "BOOLEAN",
}


def get_available_tools() -> tuple[list[types.FunctionDeclaration], dict[str, dict]]:
    """
    稼働中の全コンテナからツール情報を収集し、
    Gemini FunctionDeclaration リストと実行用マッピングを返す。

    Returns
    -------
    (declarations, tool_map)
        tool_map: { "container__tool": {"container": name, "tool": tool_name} }
    """
    mgr = ContainerManager()
    containers = mgr.list_containers()
    declarations: list[types.FunctionDeclaration] = []
    tool_map: dict[str, dict] = {}

    for c in containers:
        if c.status.value != "running":
            continue
        code = mgr.get_server_code(c.name)
        if not code:
            continue
        tools = _parse_tools_from_code(code)
        _add_tools(c.name, tools, declarations, tool_map)

    return declarations, tool_map


def get_container_tools(
    name: str,
) -> tuple[list[types.FunctionDeclaration], dict[str, dict]]:
    """特定コンテナのツール情報のみ取得"""
    mgr = ContainerManager()
    info = mgr.get_container(name)
    if info is None or info.status.value != "running":
        return [], {}

    code = mgr.get_server_code(name)
    if not code:
        return [], {}

    tools = _parse_tools_from_code(code)
    declarations: list[types.FunctionDeclaration] = []
    tool_map: dict[str, dict] = {}
    _add_tools(name, tools, declarations, tool_map)
    return declarations, tool_map


def _add_tools(
    container_name: str,
    tools: list[dict],
    declarations: list[types.FunctionDeclaration],
    tool_map: dict[str, dict],
) -> None:
    """ツール情報を FunctionDeclaration リストとマッピングに追加"""
    # Gemini の関数名は [a-zA-Z_][a-zA-Z0-9_]* のみ許可
    safe_name = container_name.replace("-", "_")

    for t in tools:
        full_name = f"{safe_name}__{t['name']}"

        properties = {}
        required = []
        for p in t.get("parameters", []):
            schema_type = _TYPE_MAP.get(p["type"], "STRING")
            properties[p["name"]] = types.Schema(type=schema_type)
            required.append(p["name"])

        params_schema = None
        if properties:
            params_schema = types.Schema(
                type="OBJECT",
                properties=properties,
                required=required,
            )

        decl = types.FunctionDeclaration(
            name=full_name,
            description=f"[{container_name}] {t.get('description', '')}",
            parameters=params_schema,
        )
        declarations.append(decl)
        tool_map[full_name] = {
            "container": container_name,
            "tool": t["name"],
        }


async def execute_tool(
    container_name: str, tool_name: str, args: dict[str, Any]
) -> str:
    """コンテナ内でツール関数を実行して結果文字列を返す"""
    docker_name = f"mcp-{container_name}"
    args_json = json.dumps(args, ensure_ascii=False)

    test_script = f"""\
import json, sys, asyncio, inspect
try:
    import server
    func = getattr(server, '{tool_name}', None)
    if func is None:
        print(json.dumps({{"error": "ツール '{tool_name}' が見つかりません"}}))
        sys.exit(0)
    args = json.loads('''{args_json}''')
    result = func(**args)
    if inspect.iscoroutine(result):
        result = asyncio.run(result)
    print(json.dumps({{"result": result}}, ensure_ascii=False))
except Exception as e:
    print(json.dumps({{"error": str(e)}}, ensure_ascii=False))
"""

    client = docker.from_env()
    try:
        container = client.containers.get(docker_name)
        _, output = container.exec_run(
            ["python", "-c", test_script],
            user="10001:10001",
            demux=True,
        )
        stdout = (output[0] or b"").decode("utf-8", errors="replace").strip()
        stderr = (output[1] or b"").decode("utf-8", errors="replace").strip()

        if stdout:
            try:
                data = json.loads(stdout)
                if "result" in data:
                    return str(data["result"])
                if "error" in data:
                    return f"エラー: {data['error']}"
                return stdout
            except json.JSONDecodeError:
                return stdout

        if stderr:
            return f"エラー: {stderr}"

        return "出力がありませんでした"

    except NotFound:
        return f"エラー: コンテナ {docker_name} が見つかりません"
    except Exception as exc:
        return f"エラー: {str(exc)}"
