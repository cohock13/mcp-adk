"""
AI コード生成サービス — Google ADK (Gemini) を使用

責務:
- ユーザーの自然言語指示から MCP サーバーコードを生成
- システムプロンプトに従った構造化 JSON 出力
- 会話履歴の管理
- Function Calling による稼働中 MCP ツールの利用
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, AsyncGenerator

from google import genai
from google.genai import types

from control_plane.config import GOOGLE_API_KEY, AGENT_MODEL

logger = logging.getLogger(__name__)

# プロンプトファイル読み込み
PROMPT_DIR = Path(__file__).parent.parent / "prompts"
CREATE_PROMPT = (PROMPT_DIR / "create_prompt.txt").read_text(encoding="utf-8")


class CodeGeneratorSession:
    """1つのチャットセッション（会話履歴保持）"""

    def __init__(self) -> None:
        self._history: list[types.Content] = []

    async def generate_stream(
        self,
        user_message: str,
        function_declarations: list[types.FunctionDeclaration] | None = None,
        tool_map: dict[str, dict] | None = None,
    ) -> AsyncGenerator[dict[str, Any], None]:
        """
        ユーザーメッセージを受け取り、AI の応答をイベントとしてストリーミング。
        Function Calling 対応: 稼働中コンテナのツールを呼び出し可能。

        Yields
        ------
        dict — イベント:
            {"type": "text", "content": str}
            {"type": "tool_call", "container": str, "tool": str, "args": dict}
            {"type": "tool_result", "container": str, "tool": str, "result": str}
        """
        client = genai.Client(api_key=GOOGLE_API_KEY)

        self._history.append(
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_message)],
            )
        )

        tools_param = None
        if function_declarations:
            tools_param = [types.Tool(function_declarations=function_declarations)]

        config = types.GenerateContentConfig(
            system_instruction=CREATE_PROMPT,
            temperature=0.7,
            max_output_tokens=8192,
            tools=tools_param,
        )

        max_rounds = 5
        for _ in range(max_rounds):
            full_text = ""
            function_call_parts: list[types.Part] = []

            try:
                stream = await client.aio.models.generate_content_stream(
                    model=AGENT_MODEL,
                    contents=self._history,
                    config=config,
                )

                async for chunk in stream:
                    # テキスト取得
                    try:
                        if chunk.text:
                            full_text += chunk.text
                            yield {"type": "text", "content": chunk.text}
                    except (ValueError, AttributeError):
                        pass

                    # Function call 検出
                    try:
                        if chunk.candidates and chunk.candidates[0].content:
                            for part in chunk.candidates[0].content.parts:
                                if hasattr(part, "function_call") and part.function_call:
                                    function_call_parts.append(part)
                    except (AttributeError, IndexError):
                        pass

            except Exception as exc:
                error_msg = f"\n\n❌ AI エラー: {exc}"
                yield {"type": "text", "content": error_msg}
                self._history.append(
                    types.Content(
                        role="model",
                        parts=[types.Part.from_text(text=error_msg)],
                    )
                )
                return

            if not function_call_parts:
                # テキスト応答のみ — 履歴に追加して終了
                if full_text:
                    self._history.append(
                        types.Content(
                            role="model",
                            parts=[types.Part.from_text(text=full_text)],
                        )
                    )
                break

            # --- Function Calling 処理 ---
            self._history.append(
                types.Content(role="model", parts=function_call_parts)
            )

            from control_plane.services.tool_executor import execute_tool

            response_parts: list[types.Part] = []
            for fc_part in function_call_parts:
                fc = fc_part.function_call
                # container__tool → container, tool
                if tool_map and fc.name in tool_map:
                    info = tool_map[fc.name]
                    container_name = info["container"]
                    tool_name = info["tool"]
                else:
                    parts = fc.name.split("__", 1)
                    container_name = parts[0]
                    tool_name = parts[1] if len(parts) > 1 else fc.name

                args = dict(fc.args) if fc.args else {}

                yield {
                    "type": "tool_call",
                    "container": container_name,
                    "tool": tool_name,
                    "args": args,
                }

                result = await execute_tool(container_name, tool_name, args)

                yield {
                    "type": "tool_result",
                    "container": container_name,
                    "tool": tool_name,
                    "result": result,
                }

                response_parts.append(
                    types.Part(
                        function_response=types.FunctionResponse(
                            name=fc.name,
                            response={"result": result},
                        )
                    )
                )

            self._history.append(
                types.Content(role="user", parts=response_parts)
            )
            # ループ継続 — モデルが結果に基づいてテキスト応答を生成

    def reset(self) -> None:
        """会話履歴をリセット"""
        self._history.clear()


def extract_server_spec(text: str) -> dict | None:
    """
    AI レスポンスから JSON サーバー仕様を抽出する。

    Markdown コードブロック内の JSON、または純粋な JSON テキストを検出。
    """
    # 1. ```json ... ``` 内を探す
    json_blocks = re.findall(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    for block in json_blocks:
        try:
            spec = json.loads(block.strip())
            if _is_valid_spec(spec):
                return spec
        except json.JSONDecodeError:
            continue

    # 2. { で始まるテキストブロックを探す
    brace_blocks = re.findall(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", text, re.DOTALL)
    for block in brace_blocks:
        try:
            spec = json.loads(block)
            if _is_valid_spec(spec):
                return spec
        except json.JSONDecodeError:
            continue

    return None


def _is_valid_spec(spec: dict) -> bool:
    """最低限のフィールドが含まれているか確認"""
    return (
        isinstance(spec, dict)
        and "name" in spec
        and "code" in spec
        and isinstance(spec.get("code"), str)
        and len(spec["code"]) > 10
    )
