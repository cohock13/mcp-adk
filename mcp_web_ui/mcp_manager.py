"""MCPサーバー管理モジュール - 動的にMCPサーバーを読み込み・管理する"""
import os
import sys
import subprocess
import asyncio
from pathlib import Path
from typing import Dict, List, Optional, Any
import importlib.util

from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset, StdioConnectionParams, StdioServerParameters

from .config import MCP_SERVERS_DIR


class MCPServerManager:
    """MCPサーバーの管理クラス"""
    
    def __init__(self):
        self.servers_dir = MCP_SERVERS_DIR
        self.active_servers: Dict[str, MCPToolset] = {}
        self.server_processes: Dict[str, subprocess.Popen] = {}
    
    def list_available_servers(self) -> List[Dict[str, Any]]:
        """利用可能なMCPサーバーの一覧を取得"""
        servers = []
        for file in self.servers_dir.glob("*.py"):
            if file.name.startswith("_"):
                continue
            servers.append({
                "name": file.stem,
                "path": str(file),
                "active": file.stem in self.active_servers
            })
        return servers
    
    def get_server_code(self, server_name: str) -> Optional[str]:
        """MCPサーバーのコードを取得"""
        server_path = self.servers_dir / f"{server_name}.py"
        if server_path.exists():
            return server_path.read_text(encoding="utf-8")
        return None
    
    def save_server_code(self, server_name: str, code: str) -> str:
        """MCPサーバーのコードを保存"""
        server_path = self.servers_dir / f"{server_name}.py"
        server_path.write_text(code, encoding="utf-8")
        return str(server_path)
    
    def delete_server(self, server_name: str) -> bool:
        """MCPサーバーを削除"""
        # まずアクティブな場合は停止
        if server_name in self.active_servers:
            self.stop_server(server_name)
        
        server_path = self.servers_dir / f"{server_name}.py"
        if server_path.exists():
            server_path.unlink()
            return True
        return False
    
    def load_server(self, server_name: str) -> Optional[MCPToolset]:
        """MCPサーバーをツールセットとして読み込む"""
        server_path = self.servers_dir / f"{server_name}.py"
        if not server_path.exists():
            return None
        
        # PythonスクリプトをMCPサーバーとして起動
        toolset = MCPToolset(
            connection_params=StdioConnectionParams(
                server_params=StdioServerParameters(
                    command=sys.executable,
                    args=[str(server_path)],
                ),
                timeout=60,
            ),
        )
        
        self.active_servers[server_name] = toolset
        return toolset
    
    def stop_server(self, server_name: str) -> bool:
        """MCPサーバーを停止"""
        if server_name in self.active_servers:
            del self.active_servers[server_name]
            return True
        return False
    
    def get_active_toolsets(self) -> List[MCPToolset]:
        """アクティブなMCPツールセットのリストを取得"""
        return list(self.active_servers.values())
    
    def get_all_tools(self) -> List[MCPToolset]:
        """すべてのアクティブなツールセットを取得"""
        return self.get_active_toolsets()


# シングルトンインスタンス
mcp_manager = MCPServerManager()
