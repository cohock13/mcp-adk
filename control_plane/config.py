"""
MCP Container Control Plane - Configuration
"""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ===== パス定義 =====
BASE_DIR = Path(__file__).parent
PROJECT_ROOT = BASE_DIR.parent
DATA_DIR = Path(os.getenv("DATA_DIR", PROJECT_ROOT / "data"))

# サーバー設定JSONの保存先
SERVER_CONFIGS_DIR = DATA_DIR / "server_configs"
# ビルド作業領域
BUILD_WORKSPACE_DIR = DATA_DIR / "build_workspace"
# Squid関連
SQUID_CONF_PATH = DATA_DIR / "squid" / "squid.conf"
SQUID_WHITELIST_DIR = DATA_DIR / "squid" / "whitelist"

# ===== Docker / Registry =====
REGISTRY_URL = os.getenv("REGISTRY_URL", "localhost:5000")
SQUID_CONTAINER_NAME = "mcp-squid"
TRIVY_CONTAINER_NAME = "mcp-trivy"
MCP_NETWORK_NAME = "mcp-internal"
MCP_SUBNET_PREFIX = "172.20.0"
# MCPサーバーに割り当てるIPの開始オフセット（172.20.0.10〜）
MCP_IP_START_OFFSET = 10

# ===== AI / LLM =====
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY", "")
AGENT_MODEL = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

# ===== コンテナセキュリティ設定 =====
CONTAINER_SECURITY = {
    "user": "10001:10001",
    "read_only": True,
    "cap_drop": ["ALL"],
    "security_opt": ["no-new-privileges:true"],
    "mem_limit": "256m",
    "cpu_quota": 50000,
    "pids_limit": 64,
    "tmpfs": {"/tmp": "size=64m,mode=1777"},
}

# ===== ベースイメージ =====
MCP_BASE_IMAGE = "mcp-base:latest"
