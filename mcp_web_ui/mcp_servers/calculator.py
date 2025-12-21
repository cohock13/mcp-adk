from mcp.server.fastmcp import FastMCP

# MCPサーバーを作成
mcp = FastMCP("calculator")

@mcp.tool()
def add(a: float, b: float) -> float:
    """2つの数値を加算します。"""
    return a + b

@mcp.tool()
def subtract(a: float, b: float) -> float:
    """2つの数値を減算します。"""
    return a - b

@mcp.tool()
def multiply(a: float, b: float) -> float:
    """2つの数値を乗算します。"""
    return a * b

@mcp.tool()
def divide(a: float, b: float) -> float:
    """2つの数値を除算します。0で割る場合はエラーを返します。"""
    if b == 0:
        raise ValueError("Cannot divide by zero.")
    return a / b

if __name__ == "__main__":
    mcp.run()
