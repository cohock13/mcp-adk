"""FastAPI メインアプリケーション"""
import asyncio
import uuid
from pathlib import Path
from typing import Dict, List, Optional, Any
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.requests import Request
from pydantic import BaseModel

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from .agent import create_mcp_creator_agent
from .mcp_manager import mcp_manager
from .config import AGENT_MODEL


# セッション管理
session_service = InMemorySessionService()
sessions: Dict[str, Runner] = {}


@asynccontextmanager
async def lifespan(app: FastAPI):
    """アプリケーションのライフサイクル管理"""
    print("🚀 MCP Web UI を起動しています...")
    yield
    print("👋 MCP Web UI をシャットダウンしています...")


app = FastAPI(
    title="MCP Creator Web UI",
    description="MCPサーバーを作成・管理するWebアプリケーション",
    lifespan=lifespan
)

# 静的ファイルとテンプレートの設定
BASE_DIR = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")
templates = Jinja2Templates(directory=BASE_DIR / "templates")


# Pydanticモデル
class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None


class ToolCall(BaseModel):
    name: str
    arguments: Dict[str, Any]
    result: Optional[str] = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: List[ToolCall] = []


class MCPServerCreate(BaseModel):
    name: str
    code: str


class MCPServerInfo(BaseModel):
    name: str
    path: str
    active: bool


# ルート
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    """メインページ"""
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/servers", response_model=List[MCPServerInfo])
async def list_servers():
    """利用可能なMCPサーバーの一覧を取得"""
    return mcp_manager.list_available_servers()


@app.get("/api/servers/{server_name}/code")
async def get_server_code(server_name: str):
    """MCPサーバーのコードを取得"""
    code = mcp_manager.get_server_code(server_name)
    if code is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"name": server_name, "code": code}


@app.post("/api/servers")
async def create_server(server: MCPServerCreate):
    """MCPサーバーを作成"""
    path = mcp_manager.save_server_code(server.name, server.code)
    return {"message": f"Server '{server.name}' created", "path": path}


@app.delete("/api/servers/{server_name}")
async def delete_server(server_name: str):
    """MCPサーバーを削除"""
    if mcp_manager.delete_server(server_name):
        return {"message": f"Server '{server_name}' deleted"}
    raise HTTPException(status_code=404, detail="Server not found")


@app.post("/api/servers/{server_name}/activate")
async def activate_server(server_name: str):
    """MCPサーバーをアクティブ化"""
    toolset = mcp_manager.load_server(server_name)
    if toolset is None:
        raise HTTPException(status_code=404, detail="Server not found")
    return {"message": f"Server '{server_name}' activated"}


@app.post("/api/servers/{server_name}/deactivate")
async def deactivate_server(server_name: str):
    """MCPサーバーを非アクティブ化"""
    if mcp_manager.stop_server(server_name):
        return {"message": f"Server '{server_name}' deactivated"}
    raise HTTPException(status_code=404, detail="Server not active")


async def run_agent_turn(runner: Runner, session_id: str, user_id: str, message: str) -> tuple[str, List[ToolCall]]:
    """エージェントのターンを実行"""
    content = types.Content(
        role="user",
        parts=[types.Part.from_text(text=message)]
    )
    
    response_text = ""
    tool_calls = []
    pending_tool_calls = {}  # name -> arguments
    
    async for event in runner.run_async(
        user_id=user_id,
        session_id=session_id,
        new_message=content
    ):
        # ツール呼び出しの検出
        if hasattr(event, 'content') and event.content and event.content.parts:
            for part in event.content.parts:
                # function_callの検出
                if hasattr(part, 'function_call') and part.function_call:
                    fc = part.function_call
                    tool_name = fc.name if hasattr(fc, 'name') else str(fc)
                    tool_args = dict(fc.args) if hasattr(fc, 'args') and fc.args else {}
                    pending_tool_calls[tool_name] = tool_args
                
                # function_responseの検出
                if hasattr(part, 'function_response') and part.function_response:
                    fr = part.function_response
                    tool_name = fr.name if hasattr(fr, 'name') else 'unknown'
                    tool_result = str(fr.response) if hasattr(fr, 'response') else str(fr)
                    
                    # 対応するツール呼び出しと結合
                    tool_args = pending_tool_calls.pop(tool_name, {})
                    tool_calls.append(ToolCall(
                        name=tool_name,
                        arguments=tool_args,
                        result=tool_result
                    ))
                
                # テキストレスポンス
                if hasattr(part, 'text') and part.text:
                    response_text += part.text
    
    return response_text, tool_calls


@app.post("/api/chat", response_model=ChatResponse)
async def chat(chat_message: ChatMessage):
    """チャットエンドポイント"""
    session_id = chat_message.session_id or str(uuid.uuid4())
    user_id = "web_user"
    
    # セッションが存在しない場合は新規作成
    if session_id not in sessions:
        # アクティブなMCPサーバーを取得してエージェントに追加
        additional_tools = mcp_manager.get_all_tools()
        agent = create_mcp_creator_agent(additional_tools if additional_tools else None)
        
        # セッションを作成（非同期）
        await session_service.create_session(
            app_name="mcp_creator",
            user_id=user_id,
            session_id=session_id
        )
        
        # Runnerを作成
        runner = Runner(
            agent=agent,
            app_name="mcp_creator",
            session_service=session_service
        )
        sessions[session_id] = runner
    
    runner = sessions[session_id]
    
    try:
        response_text, tool_calls = await run_agent_turn(runner, session_id, user_id, chat_message.message)
        return ChatResponse(response=response_text, session_id=session_id, tool_calls=tool_calls)
    except Exception as e:
        import traceback
        import re
        traceback.print_exc()
        
        error_str = str(e)
        
        # レート制限エラーの検出と分かりやすいメッセージへの変換
        if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
            # リトライ時間を抽出
            retry_match = re.search(r'retry\s*(?:in|Delay["\']?\s*:\s*["\']?)(\d+(?:\.\d+)?)', error_str, re.IGNORECASE)
            retry_seconds = retry_match.group(1) if retry_match else "不明"
            
            # クォータ情報を抽出
            quota_match = re.search(r'limit:\s*(\d+)', error_str)
            quota_limit = quota_match.group(1) if quota_match else "不明"
            
            # モデル名を抽出
            model_match = re.search(r"model['\"]?\s*:\s*['\"]?([^'\"}\s,]+)", error_str)
            model_name = model_match.group(1) if model_match else AGENT_MODEL
            
            error_message = (
                f"⚠️ **APIレート制限に達しました**\n\n"
                f"📊 **制限情報:**\n"
                f"- モデル: `{model_name}`\n"
                f"- 制限: 1日あたり {quota_limit} リクエスト（無料枠）\n"
                f"- 再試行可能時間: 約 {retry_seconds} 秒後\n\n"
                f"💡 **対処方法:**\n"
                f"1. しばらく待ってから再試行してください\n"
                f"2. `.env`ファイルで別のモデル（例: `gemini-2.0-flash`）を設定する\n"
                f"3. 有料プランにアップグレードする\n\n"
                f"📖 詳細: https://ai.google.dev/gemini-api/docs/rate-limits"
            )
            raise HTTPException(status_code=429, detail=error_message)
        
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat/reset")
async def reset_chat(session_id: Optional[str] = None):
    """チャットセッションをリセット"""
    if session_id and session_id in sessions:
        del sessions[session_id]
        return {"message": "Session reset", "session_id": session_id}
    return {"message": "New session will be created on next message"}


@app.get("/api/model")
async def get_model_info():
    """使用中のモデル情報を取得"""
    return {"model": AGENT_MODEL}


# WebSocket接続管理
class ConnectionManager:
    def __init__(self):
        self.active_connections: Dict[str, WebSocket] = {}
    
    async def connect(self, websocket: WebSocket, session_id: str):
        await websocket.accept()
        self.active_connections[session_id] = websocket
    
    def disconnect(self, session_id: str):
        if session_id in self.active_connections:
            del self.active_connections[session_id]
    
    async def send_message(self, message: str, session_id: str):
        if session_id in self.active_connections:
            await self.active_connections[session_id].send_text(message)


manager = ConnectionManager()


@app.websocket("/ws/{session_id}")
async def websocket_endpoint(websocket: WebSocket, session_id: str):
    """WebSocketエンドポイント（ストリーミング用）"""
    await manager.connect(websocket, session_id)
    user_id = "web_user"
    
    try:
        while True:
            data = await websocket.receive_text()
            
            # セッションが存在しない場合は新規作成
            if session_id not in sessions:
                additional_tools = mcp_manager.get_all_tools()
                agent = create_mcp_creator_agent(additional_tools if additional_tools else None)
                
                await session_service.create_session(
                    app_name="mcp_creator",
                    user_id=user_id,
                    session_id=session_id
                )
                
                runner = Runner(
                    agent=agent,
                    app_name="mcp_creator",
                    session_service=session_service
                )
                sessions[session_id] = runner
            
            runner = sessions[session_id]
            
            content = types.Content(
                role="user",
                parts=[types.Part.from_text(text=data)]
            )
            
            # ストリーミングレスポンス
            async for event in runner.run_async(
                user_id=user_id,
                session_id=session_id,
                new_message=content
            ):
                if hasattr(event, 'content') and event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            await websocket.send_text(part.text)
            
            # 終了マーカーを送信
            await websocket.send_text("[END]")
            
    except WebSocketDisconnect:
        manager.disconnect(session_id)
