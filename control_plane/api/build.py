"""
ビルドパイプライン API エンドポイント

- POST /api/build/{name}      — ビルド開始
- GET  /api/build/{name}/status — ビルド状態（SSE ストリーム）
"""
from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from control_plane.models.build import BuildStage, BuildState
from control_plane.services.build_pipeline import BuildPipeline

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/build", tags=["build"])

# シングルトン（アプリ内共有）
_pipeline = BuildPipeline()


# ------------------------------------------------------------------
# Request / Response models
# ------------------------------------------------------------------

class BuildRequest(BaseModel):
    """ビルド開始リクエスト"""
    code: str = Field(..., description="server.py のソースコード")
    dependencies: list[str] = Field(
        default_factory=list,
        description="追加 pip パッケージ (例: ['numpy==2.0.0'])",
    )
    whitelist: list[str] = Field(
        default_factory=list,
        description="外部アクセス許可ドメイン",
    )
    description: str = Field(default="", description="サーバーの説明")


class BuildResponse(BaseModel):
    """ビルド開始レスポンス"""
    server_name: str
    stage: BuildStage
    message: str


# ------------------------------------------------------------------
# POST /api/build/{name}
# ------------------------------------------------------------------

@router.post("/{name}", response_model=BuildResponse)
async def start_build(
    name: str,
    req: BuildRequest,
    background_tasks: BackgroundTasks,
):
    """
    ビルドパイプラインを開始する。

    ビルドはバックグラウンドで実行され、
    ``GET /api/build/{name}/status`` で進捗を SSE ストリームとして取得できる。
    """
    # バリデーション
    if not name.isidentifier():
        raise HTTPException(
            status_code=400,
            detail="サーバー名は英数字とアンダースコアのみ使用できます",
        )

    # 既にビルド中なら拒否
    current = _pipeline.get_state(name)
    if current and current.stage not in (
        BuildStage.COMPLETED, BuildStage.FAILED,
    ):
        raise HTTPException(
            status_code=409,
            detail=f"サーバー '{name}' は現在ビルド中です (stage={current.stage.value})",
        )

    # バックグラウンドでパイプライン実行
    background_tasks.add_task(
        _pipeline.execute,
        name=name,
        code=req.code,
        dependencies=req.dependencies,
        whitelist=req.whitelist,
        description=req.description,
    )

    return BuildResponse(
        server_name=name,
        stage=BuildStage.PENDING,
        message="ビルドを開始しました",
    )


# ------------------------------------------------------------------
# GET /api/build/{name}/status (SSE)
# ------------------------------------------------------------------

@router.get("/{name}/status")
async def build_status_stream(name: str):
    """
    ビルド進捗を SSE (Server-Sent Events) でストリーミング。

    クライアントは ``EventSource`` で接続し、
    各イベントで ``BuildState`` JSON を受信する。
    """
    return StreamingResponse(
        _sse_generator(name),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


async def _sse_generator(name: str):
    """BuildState をポーリングして SSE イベントを生成"""
    last_log_count = 0

    while True:
        state = _pipeline.get_state(name)

        if state is None:
            # まだビルドが開始されていない
            yield _sse_event({"stage": "pending", "progress": 0, "logs": [], "error": ""})
            await asyncio.sleep(1)
            continue

        # 新しいログだけ送信
        new_logs = state.logs[last_log_count:]
        last_log_count = len(state.logs)

        event_data = {
            "stage": state.stage.value,
            "progress": state.progress,
            "logs": new_logs,
            "error": state.error,
        }
        yield _sse_event(event_data)

        # 完了 or 失敗なら終了
        if state.stage in (BuildStage.COMPLETED, BuildStage.FAILED):
            # 最終イベント（全ログ含む）
            final = {
                "stage": state.stage.value,
                "progress": state.progress,
                "logs": state.logs,
                "error": state.error,
                "done": True,
            }
            yield _sse_event(final)
            break

        await asyncio.sleep(1)


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
