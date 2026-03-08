"""
Cisco MCP Scanner によるセキュリティスキャン

非コンテナ版 (mcp_web_ui/security_scanner.py) から移植。
Cisco AI Defense 製 cisco-ai-mcp-scanner (v3.1.0) の YARA アナライザーを使用し、
MCPサーバーのツールを動的にスキャンして脅威を検出する。

方式: コンテナの server.py コードを取得 → ホスト側で一時ファイルとして
stdio MCP サーバーを起動 → mcp-scanner でツールをスキャン
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Any

from mcpscanner import Config, Scanner, AnalyzerEnum
from mcpscanner.core.mcp_models import StdioServer

from control_plane.models.scan import CiscoScanResponse, ScanFinding

logger = logging.getLogger(__name__)


class CiscoScanner:
    """Cisco mcp-scanner を使った MCP ツール動的スキャナー"""

    def __init__(self, use_api: bool = False, use_llm: bool = False) -> None:
        """
        Args:
            use_api: Cisco AI Defense API を使用するか（APIキーが必要）
            use_llm: LLM アナライザーを使用するか（LLM APIキーが必要）
        """
        self.analyzers: list[AnalyzerEnum] = [AnalyzerEnum.YARA]

        if use_api:
            self.analyzers.append(AnalyzerEnum.API)

        if use_llm:
            self.analyzers.append(AnalyzerEnum.LLM)

        self.config = Config()
        self.scanner = Scanner(self.config)

    # ------------------------------------------------------------------
    # コンテナのコードをスキャン
    # ------------------------------------------------------------------

    async def scan_code(self, container_name: str, code: str) -> CiscoScanResponse:
        """
        MCP サーバーのコードを Cisco mcp-scanner でスキャン。

        コンテナ内の server.py コードをホスト側の一時ファイルに書き出し、
        stdio MCP サーバーとして起動してツールを動的にスキャンする。

        Args:
            container_name: コンテナ名（レスポンス用）
            code: server.py のソースコード

        Returns:
            CiscoScanResponse: スキャン結果
        """
        tmp_path: Path | None = None
        try:
            # コードを一時ファイルに書き出し
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as f:
                f.write(code)
                f.flush()
                tmp_path = Path(f.name)

            # StdioServer として起動してスキャン
            server_config = StdioServer(
                command="python",
                args=[str(tmp_path)],
            )

            # scan_stdio_server_tools は async メソッド
            results = await self.scanner.scan_stdio_server_tools(
                server_config,
                analyzers=self.analyzers,
                timeout=60,
            )

            # 結果を変換
            # ToolScanResult: tool_name, tool_description, status, analyzers, findings, server_source, server_name
            # SecurityFinding: severity, summary, analyzer, threat_category, details
            findings: list[ScanFinding] = []
            raw_results_list: list[dict[str, Any]] = []

            for result in results:
                tool_findings = result.findings or []
                is_safe = len(tool_findings) == 0

                raw_result: dict[str, Any] = {
                    "tool_name": result.tool_name,
                    "tool_description": result.tool_description,
                    "status": result.status,
                    "is_safe": is_safe,
                    "findings": [],
                }

                for finding in tool_findings:
                    raw_finding: dict[str, Any] = {
                        "severity": finding.severity,
                        "threat_category": finding.threat_category,
                        "summary": finding.summary,
                        "analyzer": finding.analyzer,
                        "details": finding.details,
                    }
                    raw_result["findings"].append(raw_finding)

                    findings.append(
                        ScanFinding(
                            tool_name=result.tool_name,
                            pattern=finding.threat_category,
                            description=finding.summary,
                            severity=_normalize_severity(finding.severity),
                            analyzer=finding.analyzer,
                            details=finding.details,
                        )
                    )

                raw_results_list.append(raw_result)

            is_safe_overall = len(findings) == 0
            severity = _calculate_severity(findings)
            summary_text = _generate_summary(findings)

            return CiscoScanResponse(
                container_name=container_name,
                is_safe=is_safe_overall,
                severity=severity,
                findings=findings,
                summary=summary_text,
                raw_results=raw_results_list,
            )

        except Exception as exc:
            error_msg = str(exc)
            error_type = type(exc).__name__
            logger.warning(
                "Cisco scan failed for %s: %s: %s",
                container_name,
                error_type,
                error_msg,
            )
            return CiscoScanResponse(
                container_name=container_name,
                is_safe=False,
                severity="HIGH",
                findings=[
                    ScanFinding(
                        tool_name="(scan error)",
                        pattern="scan_error",
                        description=f"{error_type}: {error_msg}",
                        severity="HIGH",
                        analyzer="system",
                        details={
                            "note": "MCPサーバーの起動に失敗しました。"
                            "ファイルが有効なMCPサーバーか確認してください。"
                        },
                    )
                ],
                summary=f"スキャンエラー ({error_type}): {error_msg}",
                raw_results=[
                    {
                        "error": True,
                        "error_type": error_type,
                        "error_message": error_msg,
                        "container_name": container_name,
                    }
                ],
            )
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)


# ------------------------------------------------------------------
# ヘルパー関数
# ------------------------------------------------------------------


def _normalize_severity(severity_str: str) -> str:
    """Enum 型や文字列の severity を正規化"""
    s = str(severity_str).upper()
    if "HIGH" in s:
        return "HIGH"
    if "MEDIUM" in s:
        return "MEDIUM"
    if "LOW" in s:
        return "LOW"
    return "UNKNOWN"


def _calculate_severity(findings: list[ScanFinding]) -> str:
    """検出結果から総合的な深刻度を計算"""
    if not findings:
        return "SAFE"

    level_map = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    max_level = 0
    max_sev = "SAFE"

    for f in findings:
        s = _normalize_severity(f.severity)
        level = level_map.get(s, 0)
        if level > max_level:
            max_level = level
            max_sev = s

    return max_sev


def _generate_summary(findings: list[ScanFinding]) -> str:
    """検出結果のサマリーを日本語で生成"""
    if not findings:
        return "✅ セキュリティ上の問題は検出されませんでした"

    counts: dict[str, int] = {}
    for f in findings:
        s = _normalize_severity(f.severity)
        counts[s] = counts.get(s, 0) + 1

    parts: list[str] = []
    if "HIGH" in counts:
        parts.append(f"🔴 高リスク: {counts['HIGH']}件")
    if "MEDIUM" in counts:
        parts.append(f"🟡 中リスク: {counts['MEDIUM']}件")
    if "LOW" in counts:
        parts.append(f"🔵 低リスク: {counts['LOW']}件")

    return "⚠️ " + ", ".join(parts) + " の潜在的な問題を検出しました"


# ------------------------------------------------------------------
# シングルトン
# ------------------------------------------------------------------

_scanner_instance: CiscoScanner | None = None


def get_cisco_scanner(
    use_api: bool = False, use_llm: bool = False
) -> CiscoScanner:
    """CiscoScanner インスタンスを取得（シングルトン）"""
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = CiscoScanner(use_api=use_api, use_llm=use_llm)
    return _scanner_instance
