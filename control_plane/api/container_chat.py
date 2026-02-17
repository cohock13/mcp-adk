"""
コンテナ編集チャット API — 個別コンテナの対話編集

- GET  /api/containers/{name}/chat/stream   — 編集チャット (SSE ストリーム)
- POST /api/containers/{name}/chat/reset    — 編集セッションリセット
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from google import genai
from google.genai import types

from control_plane.config import GOOGLE_API_KEY, AGENT_MODEL
from control_plane.services.container_manager import ContainerManager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/containers", tags=["container-chat"])

# 編集プロンプト読み込み
PROMPT_DIR = Path(__file__).parent.parent / "prompts"
EDIT_PROMPT = (PROMPT_DIR / "edit_prompt.txt").read_text(encoding="utf-8")

# コンテナ名ごとの編集セッション
_edit_sessions: dict[str, "_EditSession"] = {}
# コンテナ名ごとの最新 AI レスポンス
_last_edit_responses: dict[str, str] = {}


class _EditSession:
    """コンテナ単位の編集チャットセッション（Function Calling 対応）"""

    def __init__(self, current_code: str) -> None:
        self._history: list[types.Content] = []
        self._current_code = current_code

    @property
    def current_code(self) -> str:
        return self._current_code

    @current_code.setter
    def current_code(self, code: str) -> None:
        self._current_code = code

    def _build_system_prompt(self) -> str:
        return (
            f"{EDIT_PROMPT}\n\n"
            f"## 現在のコード\n\n```python\n{self._current_code}\n```"
        )

    async def generate_stream(
        self,
        user_message: str,
        function_declarations: list[types.FunctionDeclaration] | None = None,
        tool_map: dict[str, dict] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """Function Calling 対応のストリーミング"""
        client = genai.Client(api_key=GOOGLE_API_KEY)

        self._history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        )

        tools_param = None
        if function_declarations:
            tools_param = [types.Tool(function_declarations=function_declarations)]

        config = types.GenerateContentConfig(
            system_instruction=self._build_system_prompt(),
            temperature=0.7,
            max_output_tokens=8192,
            tools=tools_param,
        )

        max_rounds = 5
        for _ in range(max_rounds):
            full_text = ""
            function_call_parts: list[types.Part] = []

            try:
                stream = await client.aio.models.generate_content_stream(
                    model=AGENT_MODEL,
                    contents=self._history,
                    config=config,
                )

                async for chunk in stream:
                    try:
                        if chunk.text:
                            full_text += chunk.text
                            yield {"type": "text", "content": chunk.text}
                    except (ValueError, AttributeError):
                        pass

                    try:
                        if chunk.candidates and chunk.candidates[0].content:
                            for part in chunk.candidates[0].content.parts:
                                if hasattr(part, "function_call") and part.function_call:
                                    function_call_parts.append(part)
                    except (AttributeError, IndexError):
                        pass

            except Exception as exc:
                error_msg = f"\n\n❌ AI エラー: {exc}"
                yield {"type": "text", "content": error_msg}
                self._history.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=error_msg)],
                    )
                )
                return

            if not function_call_parts:
                if full_text:
                    self._history.append(
                        types.Content(
                            role="model",
                            parts=[types.Part.from_text(text=full_text)],
                        )
                    )
                break

            # Function Calling 処理
            self._history.append(
                types.Content(role="model", parts=function_call_parts)
            )

            from control_plane.services.tool_executor import execute_tool

            response_parts: list[types.Part] = []
            for fc_part in function_call_parts:
                fc = fc_part.function_call
                if tool_map and fc.name in tool_map:
                    info = tool_map[fc.name]
                    container_name = info["container"]
                    tool_name = info["tool"]
                else:
                    parts = fc.name.split("__", 1)
                    container_name = parts[0]
                    tool_name = parts[1] if len(parts) > 1 else fc.name

                args = dict(fc.args) if fc.args else {}

                yield {
                    "type": "tool_call",
                    "container": container_name,
                    "tool": tool_name,
                    "args": args,
                }

                result = await execute_tool(container_name, tool_name, args)

                yield {
                    "type": "tool_result",
                    "container": container_name,
                    "tool": tool_name,
                    "result": result,
                }

                response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": result},
                        )
                    )
                )

            self._history.append(
                types.Content(role="user", parts=response_parts)
            )

    def reset(self) -> None:
        self._history.clear()


def _get_session(name: str) -> _EditSession:
    """コンテナの編集セッションを取得（なければ作成）"""
    if name not in _edit_sessions:
        mgr = ContainerManager()
        code = mgr.get_server_code(name)
        _edit_sessions[name] = _EditSession(current_code=code)
    return _edit_sessions[name]


def extract_edit_spec(text: str) -> dict | None:
    """AI レスポンスから編集仕様 JSON を抽出"""
    # ```json ... ``` 内を探す
    json_blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    for block in json_blocks:
        try:
            spec = json.loads(block.strip())
            if _is_valid_edit_spec(spec):
                return spec
        except json.JSONDecodeError:
            continue

    # { で始まるテキストブロックを探す
    brace_blocks = re.findall(
        r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL
    )
    for block in brace_blocks:
        try:
            spec = json.loads(block)
            if _is_valid_edit_spec(spec):
                return spec
        except json.JSONDecodeError:
            continue

    return None


def _is_valid_edit_spec(spec: dict) -> bool:
    return (
        isinstance(spec, dict)
        and spec.get("action") == "update"
        and isinstance(spec.get("code"), str)
        and len(spec["code"]) > 10
    )


# ------------------------------------------------------------------
# GET /api/containers/{name}/chat/stream?message=...
# ------------------------------------------------------------------

@router.get("/{name}/chat/stream")
async def container_chat_stream(
    name: str,
    message: str = Query(..., description="ユーザーメッセージ"),
):
    """コンテナ編集チャットの SSE ストリーム"""
    # コンテナ存在確認
    mgr = ContainerManager()
    info = mgr.get_container(name)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Container not found: {name}")

    return StreamingResponse(
        _edit_sse_generator(name, message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _edit_sse_generator(name: str, message: str):
    """編集チャットの SSE イベントジェネレーター（Function Calling 対応）"""
    session = _get_session(name)
    full_response = ""

    # 稼働中コンテナのツールを取得（全コンテナ対象）
    from control_plane.services.tool_executor import get_available_tools
    try:
        declarations, tool_map = get_available_tools()
    except Exception:
        declarations, tool_map = [], {}

    try:
        async for event in session.generate_stream(
            message,
            function_declarations=declarations or None,
            tool_map=tool_map or None,
        ):
            if event["type"] == "text":
                full_response += event["content"]
                sse = json.dumps(
                    {"type": "text", "content": event["content"]},
                    ensure_ascii=False,
                )
                yield f"data: {sse}\n\n"

            elif event["type"] == "tool_call":
                sse = json.dumps(
                    {
                        "type": "tool_call",
                        "container": event["container"],
                        "tool": event["tool"],
                        "args": event["args"],
                    },
                    ensure_ascii=False,
                )
                yield f"data: {sse}\n\n"

            elif event["type"] == "tool_result":
                sse = json.dumps(
                    {
                        "type": "tool_result",
                        "container": event["container"],
                        "tool": event["tool"],
                        "result": event["result"],
                    },
                    ensure_ascii=False,
                )
                yield f"data: {sse}\n\n"

    except Exception as exc:
        error_event = json.dumps(
            {"type": "error", "content": f"エラー: {exc}"},
            ensure_ascii=False,
        )
        yield f"data: {error_event}\n\n"

    _last_edit_responses[name] = full_response

    # 編集仕様が含まれているか確認
    spec = extract_edit_spec(full_response)
    if spec:
        # AST 解析でツールの引数情報を取得
        from control_plane.api.test import _parse_tools_from_code
        tools_detail = _parse_tools_from_code(spec.get("code", ""))

        update_event = json.dumps(
            {
                "type": "update_ready",
                "spec": {
                    "code": spec.get("code", ""),
                    "dependencies": spec.get("dependencies", []),
                    "whitelist": spec.get("whitelist", []),
                    "description": spec.get("description", ""),
                    "tools": tools_detail,
                },
            },
            ensure_ascii=False,
        )
        yield f"data: {update_event}\n\n"

    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ------------------------------------------------------------------
# POST /api/containers/{name}/chat/apply
# ------------------------------------------------------------------

@router.post("/{name}/chat/apply")
async def apply_edit(name: str):
    """
    最後の AI レスポンスに含まれるコード修正を適用して再ビルドを開始。
    """
    from control_plane.services.build_pipeline import BuildPipeline

    last_response = _last_edit_responses.get(name, "")
    if not last_response:
        raise HTTPException(status_code=400, detail="AI レスポンスがありません")

    spec = extract_edit_spec(last_response)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail="AI レスポンスからコード修正を抽出できませんでした",
        )

    mgr = ContainerManager()
    config = mgr.load_config(name)
    if config is None:
        raise HTTPException(status_code=404, detail=f"Config not found: {name}")

    new_code = spec.get("code", "")
    new_deps = spec.get("dependencies", config.dependencies or [])
    new_whitelist = spec.get("whitelist", config.whitelist or [])
    description = spec.get("description", config.description or "")

    # セッションのコードを更新
    session = _get_session(name)
    session.current_code = new_code

    # ビルドパイプライン実行（バックグラウンド）
    from fastapi import BackgroundTasks
    pipeline = BuildPipeline()

    # 既にビルド中か確認
    current = pipeline.get_state(name)
    if current and current.stage.value not in ("completed", "failed"):
        raise HTTPException(status_code=409, detail=f"'{name}' は現在ビルド中です")

    import asyncio
    asyncio.create_task(
        pipeline.execute(
            name=name,
            code=new_code,
            dependencies=new_deps,
            whitelist=new_whitelist,
            description=description,
        )
    )

    return {
        "message": f"コード更新 & 再ビルドを開始しました: {name}",
        "name": name,
        "description": description,
    }


# ------------------------------------------------------------------
# POST /api/containers/{name}/chat/reset
# ------------------------------------------------------------------

@router.post("/{name}/chat/reset")
async def reset_edit_session(name: str):
    """編集チャットセッションをリセット"""
    if name in _edit_sessions:
        del _edit_sessions[name]
    if name in _last_edit_responses:
        del _last_edit_responses[name]
    return {"message": f"セッションをリセットしました: {name}"}
