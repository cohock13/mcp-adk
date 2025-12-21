import random
import logging
from mcp.server.fastmcp import FastMCP

# MCPサーバーを作成
mcp = FastMCP("RandomGenerator")

# ロギングの設定（標準エラー出力に出力される）
logger = logging.getLogger(__name__)

@mcp.tool()
def generate_random_integers(min_val: int, max_val: int, count: int = 1) -> list[int]:
    """指定された範囲内で乱数（整数）を生成します。
    
    Args:
        min_val: 最小値（この値を含む）
        max_val: 最大値（この値を含む）
        count: 生成する個数（デフォルト: 1）
        
    Returns:
        生成された整数のリスト
    """
    if min_val > max_val:
        raise ValueError("最小値は最大値以下である必要があります。")
    if count < 1:
        raise ValueError("個数は1以上である必要があります。")
    
    # ロギング（printは使用しない）
    logger.info(f"Generating {count} random numbers between {min_val} and {max_val}")
    
    return [random.randint(min_val, max_val) for _ in range(count)]

if __name__ == "__main__":
    mcp.run()
