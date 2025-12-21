"""設定管理モジュール"""
import os
from pathlib import Path
from dotenv import load_dotenv

# .envファイルの読み込み（mcp_agentフォルダから、またはプロジェクトルートから）
PROJECT_ROOT = Path(__file__).parent.parent

# 複数の場所から.envを探す
env_paths = [
    PROJECT_ROOT / "mcp_agent" / ".env",  # mcp_agent内
    PROJECT_ROOT / ".env",  # プロジェクトルート
    Path(__file__).parent / ".env",  # mcp_web_ui内
]

loaded_env_path = None
for env_path in env_paths:
    if env_path.exists():
        load_dotenv(env_path, override=True)
        loaded_env_path = env_path
        print(f"✅ .env loaded from: {env_path}")
        break

if not loaded_env_path:
    print("⚠️ No .env file found, using default values")

# モデル設定
AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")

# MCPサーバーの保存先
MCP_SERVERS_DIR = Path(__file__).parent / "mcp_servers"
MCP_SERVERS_DIR.mkdir(exist_ok=True)

# ファイルシステムMCPの許可ディレクトリ
AI_ALLOWED_FOLDER = Path(__file__).parent.parent / "mcp_agent" / "ai_allowed_folder"
