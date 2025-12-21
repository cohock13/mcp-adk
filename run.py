"""
MCP Creator Web UI 起動スクリプト

使用方法:
    python run.py

または:
    uvicorn mcp_web_ui.main:app --host 0.0.0.0 --port 8000
"""
import uvicorn

if __name__ == "__main__":
    print("=" * 50)
    print("🔧 MCP Creator Web UI を起動しています...")
    print("=" * 50)
    print()
    print("ブラウザで以下のURLを開いてください:")
    print("  http://localhost:8000")
    print()
    print("終了するには Ctrl+C を押してください")
    print("=" * 50)
    
    uvicorn.run(
        "mcp_web_ui.main:app",
        host="0.0.0.0",
        port=8000,
        reload=False  # MCPサーバー作成時の自動リロードを防ぐ
    )
