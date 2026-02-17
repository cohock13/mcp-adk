#!/usr/bin/env bash
# ==============================================================================
# MCP Container Control Plane — セットアップスクリプト
#
# まっさらな Ubuntu/Debian VM 上でこのシステムを動作させるためのスクリプト。
# 使い方:
#   chmod +x setup.sh
#   sudo ./setup.sh
#
# 前提: Ubuntu 22.04+ / Debian 12+ (x86_64)
# ==============================================================================
set -euo pipefail

# --- 色定義 ---
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${GREEN}[✔]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }
info() { echo -e "${BLUE}[→]${NC} $*"; }

# --- root チェック ---
if [[ $EUID -ne 0 ]]; then
    err "このスクリプトは root で実行してください: sudo ./setup.sh"
    exit 1
fi

REAL_USER="${SUDO_USER:-$(whoami)}"
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo ""
echo "========================================"
echo "  MCP Container Control Plane Setup"
echo "========================================"
echo ""

# ==============================================================================
# 1. システムパッケージの更新 & 基本ツール
# ==============================================================================
info "Step 1/7: システムパッケージの更新"
apt-get update -y
apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    gnupg \
    lsb-release \
    git \
    jq
log "基本パッケージのインストール完了"

# ==============================================================================
# 2. Docker のインストール
# ==============================================================================
info "Step 2/7: Docker のインストール"

if command -v docker &>/dev/null; then
    DOCKER_VER=$(docker --version)
    log "Docker は既にインストール済み: ${DOCKER_VER}"
else
    info "Docker をインストールします..."
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/$(. /etc/os-release && echo "$ID")/gpg \
        | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
        https://download.docker.com/linux/$(. /etc/os-release && echo "$ID") \
        $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update -y
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    log "Docker のインストール完了"
fi

# Docker Compose v2 確認
if docker compose version &>/dev/null; then
    log "Docker Compose: $(docker compose version --short)"
else
    err "Docker Compose v2 が見つかりません"
    exit 1
fi

# ユーザーを docker グループに追加
if ! groups "${REAL_USER}" | grep -q docker; then
    usermod -aG docker "${REAL_USER}"
    warn "${REAL_USER} を docker グループに追加しました（再ログイン後に有効）"
fi

# Docker 起動
systemctl enable docker
systemctl start docker
log "Docker サービスが稼働中"

# ==============================================================================
# 3. プロジェクトディレクトリの確認
# ==============================================================================
info "Step 3/7: プロジェクト構成の確認"

cd "${PROJECT_DIR}"

if [[ ! -f "docker-compose.yml" ]]; then
    err "docker-compose.yml が見つかりません: ${PROJECT_DIR}"
    err "このスクリプトをプロジェクトルートに配置してから実行してください"
    exit 1
fi

log "プロジェクトディレクトリ: ${PROJECT_DIR}"

# ==============================================================================
# 4. 環境変数の設定
# ==============================================================================
info "Step 4/7: 環境変数の設定"

if [[ ! -f ".env" ]]; then
    if [[ -f ".env.example" ]]; then
        cp .env.example .env
        warn ".env.example から .env を作成しました"
    else
        cat > .env << 'ENVEOF'
# Google API Key for AI Agent (必須)
GOOGLE_API_KEY=your_google_api_key_here

# AI Model (デフォルト: gemini-2.5-flash)
AGENT_MODEL=gemini-2.5-flash

# Vertex AI を使わない場合
GOOGLE_GENAI_USE_VERTEXAI=FALSE
ENVEOF
        warn ".env ファイルを作成しました"
    fi
    echo ""
    warn "┌─────────────────────────────────────────────────┐"
    warn "│  ⚠️  .env に GOOGLE_API_KEY を設定してください   │"
    warn "│     nano .env                                   │"
    warn "└─────────────────────────────────────────────────┘"
    echo ""
else
    # GOOGLE_API_KEY が設定済みか確認
    if grep -q "your_google_api_key_here" .env 2>/dev/null; then
        warn "GOOGLE_API_KEY がプレースホルダのままです。.env を編集してください"
    else
        log ".env は設定済み"
    fi
fi

# ==============================================================================
# 5. データディレクトリの初期化
# ==============================================================================
info "Step 5/7: データディレクトリの初期化"

# Squid 設定
mkdir -p data/squid/whitelist
if [[ ! -f "data/squid/squid.conf" ]]; then
    cat > data/squid/squid.conf << 'SQUIDEOF'
http_port 3128

# ===== 動的生成 ACL =====
# (なし)

# ===== アクセス制御 =====
# (なし)

# デフォルト拒否
http_access deny all

# ログ設定
access_log /var/log/squid/access.log
cache_log /var/log/squid/cache.log
cache deny all
SQUIDEOF
    log "Squid 設定ファイルを作成"
else
    log "Squid 設定ファイルは既存"
fi

# サーバー設定・ビルドワークスペース
mkdir -p data/server_configs
mkdir -p data/build_workspace
mkdir -p data/registry

# 権限修正
chown -R "${REAL_USER}:${REAL_USER}" data/
log "データディレクトリの初期化完了"

# ==============================================================================
# 6. Docker イメージのビルド & 起動
# ==============================================================================
info "Step 6/7: Docker イメージのビルド & コンテナ起動"

docker compose build --no-cache
log "イメージのビルド完了"

docker compose up -d
log "全サービスを起動"

# 起動待ち
info "サービスの起動を待機中..."
for i in $(seq 1 30); do
    if curl -s http://localhost:8000/health 2>/dev/null | grep -q '"ok"'; then
        log "Control Plane が正常に起動しました"
        break
    fi
    if [[ $i -eq 30 ]]; then
        err "Control Plane の起動に失敗しました。ログを確認してください:"
        err "  docker compose logs control-plane"
        exit 1
    fi
    sleep 2
done

# ==============================================================================
# 7. 動作確認
# ==============================================================================
info "Step 7/7: 動作確認"

echo ""
echo "  コンテナ状態:"
docker compose ps --format "table {{.Name}}\t{{.Status}}\t{{.Ports}}"
echo ""

# ヘルスチェック
HEALTH=$(curl -s http://localhost:8000/health)
if echo "$HEALTH" | grep -q '"ok"'; then
    log "ヘルスチェック: OK"
else
    warn "ヘルスチェック: ${HEALTH}"
fi

echo ""
echo "========================================"
echo "  ✅ セットアップ完了！"
echo "========================================"
echo ""
echo "  🌐 Web UI:  http://localhost:8000"
echo ""
echo "  📋 主要コマンド:"
echo "    docker compose ps          # コンテナ状態確認"
echo "    docker compose logs -f     # ログ表示"
echo "    docker compose down        # 停止"
echo "    docker compose up -d       # 起動"
echo ""

if grep -q "your_google_api_key_here" .env 2>/dev/null; then
    echo "  ⚠️  .env に GOOGLE_API_KEY を設定後、以下を実行:"
    echo "    docker compose restart control-plane"
    echo ""
fi
