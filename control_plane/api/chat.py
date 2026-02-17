"""
メイン画面チャット API — AI との対話で MCP サーバーコンテナを生成

- GET  /api/chat/stream   — AI チャット (SSE ストリーム)
- POST /api/chat/reset    — セッションリセット
- POST /api/chat/build    — 最後の AI レスポンスからビルド実行
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query
from fastapi.responses import StreamingResponse

from control_plane.services.code_generator import (
    CodeGeneratorSession,
    extract_server_spec,
)
from control_plane.services.build_pipeline import BuildPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# セッション管理（簡易版: 単一セッション）
_session = CodeGeneratorSession()

# 最後の AI レスポンス全文を保持（JSON 抽出用）
_last_ai_response: str = ""

# ビルドパイプライン
_pipeline = BuildPipeline()


# ------------------------------------------------------------------
# GET /api/chat/stream?message=...
# ------------------------------------------------------------------

@router.get("/stream")
async def chat_stream(message: str = Query(..., description="ユーザーメッセージ")):
    """
    AI チャットの SSE ストリーム。

    AI がサーバー仕様 JSON を含むレスポンスを返した場合、
    最後に `[BUILD_READY]` イベントを送信する。
    """
    return StreamingResponse(
        _chat_sse_generator(message),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _chat_sse_generator(message: str):
    """AI 応答を SSE イベントとしてストリーミング（Function Calling 対応）"""
    global _last_ai_response
    _last_ai_response = ""
    full_response = ""

    # 稼働中コンテナのツールを取得
    from control_plane.services.tool_executor import get_available_tools
    try:
        declarations, tool_map = get_available_tools()
    except Exception:
        declarations, tool_map = [], {}

    try:
        async for event in _session.generate_stream(
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

    _last_ai_response = full_response

    # JSON 仕様が含まれているか確認
    spec = extract_server_spec(full_response)
    if spec:
        # AST 解析でツールの引数情報を取得
        from control_plane.api.test import _parse_tools_from_code
        tools_detail = _parse_tools_from_code(spec.get("code", ""))

        build_event = json.dumps(
            {
                "type": "build_ready",
                "spec": {
                    "name": spec.get("name", ""),
                    "description": spec.get("description", ""),
                    "tools": tools_detail if tools_detail else spec.get("tools", []),
                    "dependencies": spec.get("dependencies", []),
                    "whitelist": spec.get("whitelist", []),
                },
            },
            ensure_ascii=False,
        )
        yield f"data: {build_event}\n\n"

    # 完了イベント
    yield f"data: {json.dumps({'type': 'done'})}\n\n"


# ------------------------------------------------------------------
# POST /api/chat/build
# ------------------------------------------------------------------

@router.post("/build")
async def build_from_chat(background_tasks: BackgroundTasks):
    """
    最後の AI レスポンスに含まれるサーバー仕様でビルドパイプラインを開始。
    """
    if not _last_ai_response:
        raise HTTPException(status_code=400, detail="AI レスポンスがありません")

    spec = extract_server_spec(_last_ai_response)
    if spec is None:
        raise HTTPException(
            status_code=400,
            detail="AI レスポンスからサーバー仕様を抽出できませんでした",
        )

    name = spec.get("name", "")
    if not name or not name.replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail=f"無効なサーバー名: {name}")

    # 既にビルド中か確認
    current = _pipeline.get_state(name)
    if current and current.stage.value not in ("completed", "failed"):
        raise HTTPException(
            status_code=409,
            detail=f"'{name}' は現在ビルド中です",
        )

    background_tasks.add_task(
        _pipeline.execute,
        name=name,
        code=spec.get("code", ""),
        dependencies=spec.get("dependencies", []),
        whitelist=spec.get("whitelist", []),
        description=spec.get("description", ""),
    )

    return {
        "message": f"ビルドを開始しました: {name}",
        "name": name,
        "description": spec.get("description", ""),
    }


# ------------------------------------------------------------------
# POST /api/chat/reset
# ------------------------------------------------------------------

@router.post("/reset")
async def reset_session():
    """チャットセッションをリセット"""
    global _last_ai_response
    _session.reset()
    _last_ai_response = ""
    return {"message": "セッションをリセットしました"}
