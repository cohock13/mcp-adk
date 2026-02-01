# MCP Web UI

MCPサーバーを作成・管理するためのWebアプリケーションです。
Google ADK (Agent Development Kit) を使用したAIエージェントが、チャットベースでMCPサーバーを自動生成します。

## 機能

- 🤖 **AIエージェントによるMCP作成**: チャットで指示するだけでMCPサーバーを自動生成
- 📝 **コードエディタ**: 作成されたMCPサーバーのコードを直接編集
- ▶️ **動的読み込み**: 作成したMCPサーバーをその場で起動・停止
- 🔄 **リアルタイム管理**: サーバーの状態をリアルタイムで確認
- 🔍 **セキュリティスキャン**: 作成したMCPサーバーの脆弱性をチェック（APIキー不要）

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
- 📝 ボタン: コードを表示・編集
- 🔍 ボタン: セキュリティスキャンを実行（潜在的な脆弱性をチェック）
- ▶️ ボタン: サーバーを起動（エージェントのツールとして使用可能に）
- 🗑️ ボタン: サーバーを削除

### 6. セキュリティスキャン機能

🔍 ボタンをクリックすると、MCPサーバーコードの脆弱性チェックを実行します。

**スキャナー:**
- **mcp-scanner** (Cisco AI Defense製) のYARAアナライザーを使用
- 本格的なパターンマッチングとコード解析を実施
- MCPサーバーを実際に起動してツールを動的にスキャン

**検出される脅威:**
- 🔴 **HIGH**: システムコマンド実行（`os.system`）、動的コード実行（`eval`, `exec`）
- 🟡 **MEDIUM**: サブプロセス実行（`subprocess.*`）、動的インポート（`__import__`）
- 🔵 **LOW**: ファイル操作（`open`）、外部通信（`requests`, `urllib`）

**判定レベル:**
- ✅ **SAFE**: セキュリティ上の問題なし
- 🔵 **LOW**: 低リスク - 注意が必要だが一般的な操作
- 🟡 **MEDIUM**: 中リスク - 実装の確認が必要
- 🔴 **HIGH**: 高リスク - セキュリティ上の重大な懸念

**スキャン結果の見方:**
- サマリーで全体の深刻度を確認
- 検出された問題の一覧を確認
- 「詳細スキャン結果 (JSON)」を展開して完全な検出情報を確認

**注意:** 
- この機能はYARAアナライザーを使用しており、**APIキーは不要**です
- より高度なスキャンが必要な場合は、Cisco AI Defense APIやLLMアナライザーを追加できます
- テスト用に脆弱性を含むサンプル（scan_test1.py, scan_test2.py, scan_test3.py）が同梱されています

詳細は [SECURITY_SCAN_GUIDE.md](mcp_servers/SECURITY_SCAN_GUIDE.md) を参照してください。

## ディレクトリ構造

```
mcp_web_ui/
├── __init__.py
├── main.py              # FastAPIアプリケーション
├── agent.py             # ADKエージェント定義
├── system_prompt.txt    # エージェントのシステムプロンプト
├── config.py            # 設定管理
├── mcp_manager.py       # MCPサーバー管理
├── security_scanner.py  # セキュリティスキャン機能（mcp-scanner統合）
├── static/              # CSS, JavaScript
│   ├── styles.css
│   └── app.js
├── templates/           # HTMLテンプレート
│   └── index.html
└── mcp_servers/         # 作成されたMCPサーバー
    ├── calculator.py              # サンプル: 四則演算
    ├── random_generator.py        # サンプル: 乱数生成
    ├── scan_test1.py             # テスト: システムコマンド実行（HIGH）
    ├── scan_test2.py             # テスト: 動的コード実行（HIGH）
    ├── scan_test3.py             # テスト: ファイル・ネットワーク（MEDIUM/LOW）
    └── SECURITY_SCAN_GUIDE.md    # セキュリティスキャンガイド
```

## 技術スタック

- **バックエンド**: FastAPI, Google ADK
- **フロントエンド**: HTML, CSS, JavaScript (バニラ)
- **AI**: Google Gemini (設定可能)
- **MCP**: Model Context Protocol Python SDK
- **セキュリティ**: Cisco MCP Scanner 4.1.0 (YARAアナライザー)

## セキュリティスキャン詳細

### 使用しているツール

**mcp-scanner** (Cisco AI Defense製)
- バージョン: 4.1.0
- ライセンス: Apache 2.0
- リポジトリ: https://github.com/cisco-ai-defense/mcp-scanner

### スキャン方式

1. **動的スキャン**: MCPサーバーをstdioサーバーとして起動
2. **ツール検査**: 公開されているツールを列挙
3. **YARA分析**: 本格的なYARAルールでパターンマッチング
4. **脅威判定**: 検出された脅威を深刻度別に分類

### オプション機能（環境変数で有効化）

```bash
# Cisco AI Defense APIを使用（要APIキー）
export MCP_SCANNER_API_KEY="your_cisco_api_key"

# LLMアナライザーを使用（要APIキー）
export MCP_SCANNER_LLM_API_KEY="your_llm_api_key"
export MCP_SCANNER_LLM_MODEL="gpt-4o"
```

これらを設定すると、より高度なセマンティック分析が可能になります。

## トラブルシューティング

### セキュリティスキャンで「Connection closed」エラーが出る

MCPサーバーファイルに問題がある可能性があります：
- Pythonの構文エラーがないか確認
- 必要なパッケージがインストールされているか確認
- `if __name__ == "__main__": mcp.run()` が含まれているか確認

### スキャンが遅い

- YARAアナライザーのみ使用している場合、通常10-30秒程度
- MCPサーバーの起動に時間がかかる場合があります
- タイムアウトはデフォルト60秒に設定されています
