"""MCPサーバーのセキュリティスキャン機能"""
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

from mcpscanner import Config, Scanner
from mcpscanner.core.models import AnalyzerEnum
from mcpscanner.core.mcp_models import StdioServer


@dataclass
class ScanResult:
    """スキャン結果"""
    is_safe: bool
    severity: str  # SAFE, LOW, MEDIUM, HIGH
    findings: List[Dict[str, Any]]
    summary: str
    raw_results: Optional[List[Any]] = None  # 生の結果オブジェクトを保持


class MCPSecurityScanner:
    """MCPサーバーのセキュリティスキャナー"""
    
    def __init__(self, use_api: bool = False, use_llm: bool = False):
        """
        Args:
            use_api: Cisco AI Defense APIを使用するか（APIキーが必要）
            use_llm: LLMアナライザーを使用するか（LLM APIキーが必要）
        """
        # YARAアナライザーは常に使用（APIキー不要）
        self.analyzers = [AnalyzerEnum.YARA]
        
        if use_api:
            self.analyzers.append(AnalyzerEnum.API)
        
        if use_llm:
            self.analyzers.append(AnalyzerEnum.LLM)
        
        # スキャナー設定（APIキーなしで動作）
        self.config = Config()
        self.scanner = Scanner(self.config)
    
    async def scan_server_code(self, server_path: Path) -> ScanResult:
        """
        MCPサーバーのPythonコードをスキャン
        
        Args:
            server_path: スキャン対象のPythonファイルパス
        
        Returns:
            ScanResult: スキャン結果
        """
        try:
            # ファイルが存在するか確認
            if not server_path.exists():
                return ScanResult(
                    is_safe=False,
                    severity="HIGH",
                    findings=[{"error": "File not found"}],
                    summary="ファイルが見つかりません"
                )
            
            # StdioServer設定を作成
            server_config = StdioServer(
                command="python",
                args=[str(server_path)]
            )
            
            # MCPサーバーをstdioサーバーとして起動してツールをスキャン
            results = await self.scanner.scan_stdio_server_tools(
                server_config,
                analyzers=self.analyzers,
                timeout=60
            )
            
            # 結果を変換（生データも保持）
            findings = []
            raw_results_list = []
            
            for result in results:
                # 生の結果を保存（JSON化のため辞書に変換）
                raw_result = {
                    "tool_name": result.tool_name,
                    "tool_description": result.tool_description if hasattr(result, 'tool_description') else None,
                    "status": result.status if hasattr(result, 'status') else None,
                    "is_safe": result.is_safe,
                    "findings": []
                }
                
                if not result.is_safe and hasattr(result, 'findings'):
                    # 各検出結果を処理
                    for finding in result.findings:
                        # 生のfindingデータ
                        raw_finding = {
                            "severity": str(finding.severity) if hasattr(finding, 'severity') else 'UNKNOWN',
                            "threat_category": finding.threat_category if hasattr(finding, 'threat_category') else 'Unknown',
                            "summary": finding.summary if hasattr(finding, 'summary') else 'N/A',
                            "analyzer": finding.analyzer if hasattr(finding, 'analyzer') else 'mcp-scanner',
                            "details": finding.details if hasattr(finding, 'details') else None,
                        }
                        
                        # MCP taxonomy情報があれば追加
                        if hasattr(finding, 'mcp_taxonomy') and finding.mcp_taxonomy:
                            raw_finding["mcp_taxonomy"] = finding.mcp_taxonomy
                        
                        raw_result["findings"].append(raw_finding)
                        
                        # 表示用のfindingsにも追加
                        finding_entry = {
                            "tool_name": result.tool_name,
                            "pattern": finding.threat_category if hasattr(finding, 'threat_category') else 'Unknown',
                            "description": finding.summary if hasattr(finding, 'summary') else 'N/A',
                            "severity": str(finding.severity) if hasattr(finding, 'severity') else 'MEDIUM',
                            "analyzer": finding.analyzer if hasattr(finding, 'analyzer') else 'mcp-scanner',
                            "details": finding.details if hasattr(finding, 'details') else None
                        }
                        findings.append(finding_entry)
                
                raw_results_list.append(raw_result)
            
            # 結果を判定
            is_safe = len(findings) == 0
            severity = self._calculate_severity(findings)
            summary = self._generate_summary(findings)
            
            return ScanResult(
                is_safe=is_safe,
                severity=severity,
                findings=findings,
                summary=summary,
                raw_results=raw_results_list  # 生データを含める
            )
            
        except Exception as e:
            error_msg = str(e)
            error_type = type(e).__name__
            
            # エラーの詳細情報を含める
            return ScanResult(
                is_safe=False,
                severity="HIGH",
                findings=[{
                    "error": error_msg, 
                    "error_type": error_type,
                    "server_path": str(server_path)
                }],
                summary=f"スキャンエラー ({error_type}): {error_msg}",
                raw_results=[{
                    "error": True,
                    "error_type": error_type,
                    "error_message": error_msg,
                    "server_path": str(server_path),
                    "note": "MCPサーバーの起動に失敗しました。ファイルが有効なMCPサーバーか確認してください。"
                }]
            )
    
    def _calculate_severity(self, findings: List[Dict[str, Any]]) -> str:
        """検出結果から総合的な深刻度を計算"""
        if not findings:
            return "SAFE"
        
        severities = [f.get("severity", "LOW") for f in findings]
        
        # 文字列として比較
        severity_order = {"HIGH": 3, "MEDIUM": 2, "LOW": 1, "SAFE": 0}
        
        max_severity = "SAFE"
        max_level = 0
        
        for sev in severities:
            # Enum型の場合は.valueまたはstrで文字列に変換
            sev_str = str(sev).upper()
            if 'HIGH' in sev_str:
                level = 3
                sev_str = 'HIGH'
            elif 'MEDIUM' in sev_str:
                level = 2
                sev_str = 'MEDIUM'
            elif 'LOW' in sev_str:
                level = 1
                sev_str = 'LOW'
            else:
                level = 0
                sev_str = 'SAFE'
            
            if level > max_level:
                max_level = level
                max_severity = sev_str
        
        return max_severity
    
    def _generate_summary(self, findings: List[Dict[str, Any]]) -> str:
        """検出結果のサマリーを生成"""
        if not findings:
            return "✅ セキュリティ上の問題は検出されませんでした"
        
        severity_counts = {}
        for f in findings:
            sev = str(f.get("severity", "UNKNOWN")).upper()
            # Enum型の処理
            if 'HIGH' in sev:
                sev = 'HIGH'
            elif 'MEDIUM' in sev:
                sev = 'MEDIUM'
            elif 'LOW' in sev:
                sev = 'LOW'
            
            severity_counts[sev] = severity_counts.get(sev, 0) + 1
        
        parts = []
        if "HIGH" in severity_counts:
            parts.append(f"🔴 高リスク: {severity_counts['HIGH']}件")
        if "MEDIUM" in severity_counts:
            parts.append(f"🟡 中リスク: {severity_counts['MEDIUM']}件")
        if "LOW" in severity_counts:
            parts.append(f"🔵 低リスク: {severity_counts['LOW']}件")
        
        return "⚠️ " + ", ".join(parts) + " の潜在的な問題を検出しました"
    
    async def scan_stdio_server(self, command: str, args: List[str]) -> ScanResult:
        """
        Stdio MCPサーバーをスキャン
        
        Args:
            command: 実行コマンド（例: "uvx"）
            args: コマンド引数（例: ["mcp-server-fetch"]）
        
        Returns:
            ScanResult: スキャン結果
        """
        try:
            # StdioServer設定を作成
            server_config = StdioServer(
                command=command,
                args=args
            )
            
            # スキャンを実行
            results = await self.scanner.scan_stdio_server_tools(
                server_config,
                analyzers=self.analyzers,
                timeout=60
            )
            
            # 結果を集約
            findings = []
            for result in results:
                if not result.is_safe:
                    for finding in result.findings:
                        findings.append({
                            "tool_name": result.tool_name,
                            "pattern": finding.threat_category if hasattr(finding, 'threat_category') else 'Unknown',
                            "description": finding.summary if hasattr(finding, 'summary') else 'N/A',
                            "severity": str(finding.severity) if hasattr(finding, 'severity') else 'MEDIUM',
                            "analyzer": finding.analyzer if hasattr(finding, 'analyzer') else 'mcp-scanner'
                        })
            
            is_safe = len(findings) == 0
            severity = self._calculate_severity(findings)
            summary = self._generate_summary(findings)
            
            return ScanResult(
                is_safe=is_safe,
                severity=severity,
                findings=findings,
                summary=summary
            )
            
        except Exception as e:
            return ScanResult(
                is_safe=False,
                severity="HIGH",
                findings=[{"error": str(e), "error_type": type(e).__name__}],
                summary=f"スキャンエラー: {str(e)}"
            )


# グローバルインスタンス（APIキーなしで動作）
_scanner_instance = None


def get_scanner(use_api: bool = False, use_llm: bool = False) -> MCPSecurityScanner:
    """スキャナーインスタンスを取得（シングルトン）"""
    global _scanner_instance
    if _scanner_instance is None:
        _scanner_instance = MCPSecurityScanner(use_api=use_api, use_llm=use_llm)
    return _scanner_instance
