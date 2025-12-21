from mcp.server.fastmcp import FastMCP
import logging

# ロギング設定 (STDIOベースのサーバーではprint()の代わりにloggingを使用)
logging.basicConfig(level=logging.INFO)

# MCPサーバーを作成
mcp = FastMCP("CharacterCounter")

@mcp.tool()
def count_characters(text: str) -> int:
    """与えられた文字列の文字数をカウントします。

    Args:
        text: 文字数をカウントする対象の文字列。

    Returns:
        文字列の文字数。
    """
    logging.info(f"Received text for character count: {text[:50]}...") # ログ出力例
    return len(text)

if __name__ == "__main__":
    mcp.run()
