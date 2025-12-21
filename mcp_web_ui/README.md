# MCP Web UI

MCPサーバーを作成・管理するためのWebアプリケーションです。
Google ADK (Agent Development Kit) を使用したAIエージェントが、チャットベースでMCPサーバーを自動生成します。

## 機能

- 🤖 **AIエージェントによるMCP作成**: チャットで指示するだけでMCPサーバーを自動生成
- 📝 **コードエディタ**: 作成されたMCPサーバーのコードを直接編集
- ▶️ **動的読み込み**: 作成したMCPサーバーをその場で起動・停止
- 🔄 **リアルタイム管理**: サーバーの状態をリアルタイムで確認

## 使用方法

### 1. パッケージのインストール

```bash
pip install -r requirements.txt
```

### 2. 環境変数の設定

`.env` ファイルを作成し、以下を設定:

```
GOOGLE_API_KEY=your_api_key_here
AGENT_MODEL=gemini-2.5-flash
```

### 3. Webアプリケーションの起動

```bash
python run.py
```

ブラウザで http://localhost:8000 を開いてください。

### 4. MCPサーバーの作成

チャットでエージェントに指示を出すと、MCPサーバーを自動生成します。

例:
- 「四則演算のMCPサーバーを作成して」
- 「天気取得APIのMCPを作って」
- 「ファイル変換ツールのMCPサーバーを実装して」

### 5. 作成したMCPサーバーの使用

サイドバーに表示されるMCPサーバーリストから:
- ▶️ ボタン: サーバーを起動（エージェントのツールとして使用可能に）
- 📝 ボタン: コードを表示・編集
- 🗑️ ボタン: サーバーを削除

## ディレクトリ構造

```
mcp_web_ui/
├── __init__.py
├── main.py          # FastAPIアプリケーション
├── agent.py         # ADKエージェント定義
├── config.py        # 設定管理
├── mcp_manager.py   # MCPサーバー管理
├── static/          # CSS, JavaScript
│   ├── styles.css
│   └── app.js
├── templates/       # HTMLテンプレート
│   └── index.html
└── mcp_servers/     # 作成されたMCPサーバー
    └── calculator.py  # サンプル
```

## 技術スタック

- **バックエンド**: FastAPI, Google ADK
- **フロントエンド**: HTML, CSS, JavaScript (バニラ)
- **AI**: Google Gemini (設定可能)
- **MCP**: Model Context Protocol Python SDK
