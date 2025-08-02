from google.adk.agents import Agent
from dotenv import load_dotenv
import os
from .tools import *
from .mcp_tools import *

load_dotenv()
model = os.getenv("AGENT_MODEL", "gemini-2.5-flash")

system_prompt = """
あなたはファイル操作とWebページの情報の取得が行えるAIエージェントです。

filesystem:
- パスは絶対パスで指定する必要があります。そのため、まず操作を許可されているディレクトリを調べてください。
- ファイルの削除は行えないため、そのような要求があった場合には「ファイルの削除は行えません」と返答してください。

fetch:
- Webページの情報をマークダウン形式で取得することができます。
- Webページの情報を取得する際には、URLが必要です。このURLは必ずユーザーから提供される必要があります。
- ユーザーからURLが提供されない場合は、「URLを提供してください」と返答してください。URLを捏造してはいけません。
"""

root_agent = Agent(
    name="agent",
    model=model,
    description=(
        "ツールを使用するAIエージェント"
    ),
    instruction=system_prompt,
    tools=[filesystem, fetch],
)