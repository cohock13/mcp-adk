# 環境準備

このプロジェクトを実行するには、Pythonの仮想環境が必要です。

## 1. 仮想環境の作成

プロジェクトのルートディレクトリで、次のコマンドを実行して仮想環境を作成します。

```bash
python -m venv .venv
```

## 2. 仮想環境のアクティベート

作成した仮想環境をアクティベート（有効化）します。

**Windows (PowerShell):**

```powershell
.venv\Scripts\Activate.ps1
```

**macOS / Linux:**

```bash
source .venv/bin/activate
```

アクティベートされると、ターミナルのプロンプトの先頭に `(.venv)` と表示されます。

## 3. ライブラリのインストール

必要なライブラリをインストールします。

```bash
pip install -r requirements.txt
```

## 4. node,uvのインストール

mcpサーバーを起動するにはnode,uvが必要なため、公式サイトからのインストールが必要です。
公式サイトに従ってインストールを完了させてください。

## 5. 環境変数の設定

.envファイルを参照し、GOOGLE_API_KEYを設定してください。

google以外のモデル(OpenAI,Claudeなど)を使用する場合は、適切に環境変数を設定したうえで、LiteLLMを使用する必要があります。

## 6. ADK Webの実行（会話UI）
google-ADKは標準でチャットUIが用意されており、以下のコマンドで実行できます。

※mcp-adkディレクトリ下で実行しないと失敗します。mcp_agentディレクトリなどで作業している場合は親ディレクトリに移動してください。

**Windows:**
```bash
adk web --no-reload
```

**macOS / Linux:**
```bash
adk web
```

mcp_agentディレクトリと同様のものをmcp-adkディレクトリ下に用意することで、画面左上からディレクトリを選択し、エージェントを切り替えることが可能です。

## 7. MCPサーバーの書かせ方（例）

mcp_agentにはファイル操作MCPとWebページ情報取得MCPを搭載しています。これにより、Web上の情報を基にMCPサーバーを実装させることが可能です。

四則演算のMCPサーバーを実装させる例はmcp_agent/prompt_example.txtにあります。この内容をコピペしてチャットに貼り付けるか、AIエージェントにこのファイルを参照させてください。

なお、プロンプト内のURLはMCPのpythonSDKの公式ページのREADMEのrawファイルです。

## 番外編 MCPツールの検証

MCPサーバーのツール一覧や動作確認が行える検査ツールがあります。以下のコマンドで実行できます。

```bash
mcp dev mcp_server.py
```

または、直接npxコマンドで実行することもできます。

```bash
npx -y @modelcontextprotocol/inspector
```

UI上では適切にCommand,Argments(スペース区切り),Environment(proxy,api_keyなど)を設定することで接続に成功します。

自作MCPサーバーの場合は、以下のように設定します。（mcp-adk/mcp_agent/servers/sampleを起動する例です。mcp-adkディレクトリで検査ツールを実行中とします。）

**Command**
```
mcp
```

**Arguments**
```
run mcp_agent/servers/sample.py
```

なお、`mcp dev mcp_agent/servers/sample.py`で起動した場合は、uv利用時のコマンドが最初から設定されています。

pythonコマンドで実行する場合は、以下のようにします。

MCPサーバーが実装されたファイルで、以下の内容を追加します。

```python
if __name__ == "__main__":
    mcp.run()
```

**Command**
```
python
```

**Arguments**
```
mcp_agent/servers/sample.py
```
