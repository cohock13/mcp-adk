"""
ツールテスト API — MCP サーバーのツールを直接実行

- GET   /api/containers/{name}/tools              ツール一覧
- POST  /api/containers/{name}/tools/{tool}/test   ツール実行テスト
"""
from __future__ import annotations

import ast
import json
import logging
import time

import docker
from docker.errors import NotFound
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from control_plane.services.container_manager import ContainerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/containers", tags=["tools"])


# ------------------------------------------------------------------
# ツール情報の抽出
# ------------------------------------------------------------------

def _parse_tools_from_code(code: str) -> list[dict]:
    """
    AST 解析で @mcp.tool() 付き関数の名前・引数・docstring を抽出
    """
    tools: list[dict] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return tools

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue

        is_tool = False
        for deco in node.decorator_list:
            deco_src = ast.dump(deco)
            if "tool" in deco_src.lower():
                is_tool = True
                break

        if not is_tool:
            continue

        # 引数情報
        params: list[dict] = []
        for arg in node.args.args:
            if arg.arg == "self":
                continue
            param_type = "str"
            if arg.annotation:
                param_type = ast.unparse(arg.annotation)
            params.append({
                "name": arg.arg,
                "type": param_type,
            })

        # docstring
        docstring = ast.get_docstring(node) or ""

        tools.append({
            "name": node.name,
            "description": docstring,
            "parameters": params,
        })

    return tools


# ------------------------------------------------------------------
# GET /api/containers/{name}/tools
# ------------------------------------------------------------------

@router.get("/{name}/tools")
async def list_tools(name: str):
    """コンテナの MCP ツール一覧を取得（コードから AST 解析）"""
    mgr = ContainerManager()
    code = mgr.get_server_code(name)
    if not code:
        raise HTTPException(status_code=404, detail=f"Code not found: {name}")

    tools = _parse_tools_from_code(code)
    return {"name": name, "tools": tools}


# ------------------------------------------------------------------
# POST /api/containers/{name}/tools/{tool}/test
# ------------------------------------------------------------------

class ToolTestRequest(BaseModel):
    args: dict = {}


@router.post("/{name}/tools/{tool}/test")
async def test_tool(name: str, tool: str, body: ToolTestRequest):
    """
    稼働中のコンテナ内で指定ツールを実行してテストする。

    コンテナ内で Python を起動し、server.py からツール関数を
    直接インポートして実行する。
    """
    mgr = ContainerManager()
    info = mgr.get_container(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Container not found: {name}")

    if info.status.value != "running":
        raise HTTPException(
            status_code=400,
            detail=f"コンテナが稼働していません（status: {info.status.value}）",
        )

    # コンテナ名
    container_name = f"mcp-{name}"

    # ツールの引数をコードに埋め込む
    args_json = json.dumps(body.args, ensure_ascii=False)

    test_script = f"""\
import json, sys, asyncio, inspect
try:
    import server
    func = getattr(server, '{tool}', None)
    if func is None:
        print(json.dumps({{"error": "ツール '{tool}' が見つかりません"}}))
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
        container = client.containers.get(container_name)
        exit_code, output = container.exec_run(
            ["python", "-c", test_script],
            user="10001:10001",
            demux=True,
        )
        stdout = (output[0] or b"").decode("utf-8", errors="replace").strip()
        stderr = (output[1] or b"").decode("utf-8", errors="replace").strip()

        if stdout:
            try:
                result = json.loads(stdout)
                return result
            except json.JSONDecodeError:
                return {"result": stdout}

        if stderr:
            return {"error": stderr}

        return {"error": "出力がありませんでした"}

    except NotFound:
        raise HTTPException(
            status_code=404, detail=f"Container not found: {container_name}"
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))
