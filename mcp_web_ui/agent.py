"""MCP作成エージェント - MCPサーバーを作成・管理するエージェント"""
import os
from pathlib import Path
from typing import List, Optional, Callable, Any
from google.adk.agents import Agent
from google.adk.agents.callback_context import CallbackContext
from google.adk.tools import ToolContext
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams, StdioServerParameters

from .config import AGENT_MODEL, AI_ALLOWED_FOLDER, MCP_SERVERS_DIR


# システムプロンプトファイルのパス
SYSTEM_PROMPT_FILE = Path(__file__).parent / "system_prompt.txt"


def load_system_prompt() -> str:
    """system_prompt.txtからシステムプロンプトを読み込む"""
    if SYSTEM_PROMPT_FILE.exists():
        return SYSTEM_PROMPT_FILE.read_text(encoding="utf-8")
    else:
        raise FileNotFoundError(f"System prompt file not found: {SYSTEM_PROMPT_FILE}")


def get_dynamic_prompt_section() -> str:
    """動的に生成されるプロンプトセクション"""
    return f"""
---
## ファイルシステムツールについて

- パスは絶対パスで指定する必要があります
- MCPサーバーの作成先: {MCP_SERVERS_DIR}
- ファイルの削除は行えません

## Fetchツールについて

- Webページの情報をマークダウン形式で取得できます
- URLはユーザーから提供される必要があります
- URLを捏造してはいけません
- 参照ドキュメントURLは取得して参照できます
"""


def get_full_system_prompt() -> str:
    """完全なシステムプロンプトを取得（静的 + 動的部分）"""
    base_prompt = load_system_prompt()
    dynamic_section = get_dynamic_prompt_section()
    return base_prompt + dynamic_section


def get_filesystem_mcp() -> MCPToolset:
    """ファイルシステムMCPツールセットを取得"""
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command='npx',
                args=[
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    str(MCP_SERVERS_DIR),
                ],
            ),
            timeout=60,
        ),
    )


def get_fetch_mcp() -> MCPToolset:
    """FetchMCPツールセットを取得"""
    return MCPToolset(
        connection_params=StdioConnectionParams(
            server_params=StdioServerParameters(
                command='uvx',
                args=["mcp-server-fetch"],
            ),
            timeout=60,
        ),
    )


def create_mcp_creator_agent(
    additional_tools: Optional[List[MCPToolset]] = None,
    before_tool_callback: Optional[Callable[[CallbackContext, ToolContext], Optional[dict]]] = None
) -> Agent:
    """MCP作成エージェントを生成する
    
    Args:
        additional_tools: 追加のMCPツールセット
        before_tool_callback: ツール実行前に呼ばれるコールバック関数
            - Noneを返すとツールが実行される
            - dictを返すとそれがツールの結果として使用され、実際のツールは実行されない
    """
    tools = [get_filesystem_mcp(), get_fetch_mcp()]
    
    if additional_tools:
        tools.extend(additional_tools)
    
    return Agent(
        name="mcp_creator",
        model=AGENT_MODEL,
        description="MCPサーバーを作成・管理するAIエージェント",
        instruction=get_full_system_prompt(),
        tools=tools,
        before_tool_callback=before_tool_callback,
    )
