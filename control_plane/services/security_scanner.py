"""
セキュリティスキャナー

責務:
- Python コードの静的解析 (ruff, bandit)
- 危険パターンの検出
- Trivy によるコンテナイメージの脆弱性スキャン
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

import docker
from docker.errors import NotFound

from control_plane.config import TRIVY_CONTAINER_NAME

logger = logging.getLogger(__name__)

# ------------------------------------------------------------------
# コードに含まれてはいけない危険パターン
# ------------------------------------------------------------------
DANGEROUS_PATTERNS: list[tuple[str, str, bool]] = [
    # (regex, message, is_blocking)
    (r"\bexec\s*\(", "exec() の使用は禁止されています", True),
    (r"\beval\s*\(", "eval() の使用は禁止されています", True),
    (r"\b__import__\s*\(", "__import__() の使用は禁止されています", True),
    (r"\bos\.system\s*\(", "os.system() の使用は禁止されています", True),
    (r"\bsubprocess\b", "subprocess モジュールの使用は禁止されています", True),
    (r"\bos\.popen\s*\(", "os.popen() の使用は禁止されています", True),
    (r"\bctypes\b", "ctypes モジュールの使用は危険です", True),
    (r"\bpickle\b", "pickle モジュールの使用は危険です", False),
    (r"\bsocket\.socket\b", "socket の直接使用は禁止されています", True),
    (r"\bopen\s*\([^)]*['\"]\/", "絶対パスでのファイルアクセスは禁止されています", True),
]


class SecurityScanner:
    """静的解析 + Trivy スキャン"""

    def __init__(self) -> None:
        self._client = docker.from_env()

    # ==================================================================
    # コードスキャン（静的解析 + パターン検査）
    # ==================================================================

    def scan_code(self, code: str) -> tuple[bool, list[str]]:
        """
        コードの静的解析とセキュリティパターン検査を実行。

        Returns
        -------
        (passed, findings)
            passed: ブロッキング問題がなければ True
            findings: 検出結果メッセージのリスト
        """
        findings: list[str] = []
        has_blocker = False

        # 1. 危険パターン検出
        for pattern, message, blocking in DANGEROUS_PATTERNS:
            if re.search(pattern, code):
                prefix = "🚫" if blocking else "⚠️"
                findings.append(f"{prefix} パターン検出: {message}")
                if blocking:
                    has_blocker = True

        # 2. ruff lint
        ruff_issues = self._run_ruff(code)
        findings.extend(ruff_issues)

        # 3. bandit security check
        bandit_issues = self._run_bandit(code)
        for issue in bandit_issues:
            if issue.startswith("🚫"):
                has_blocker = True
        findings.extend(bandit_issues)

        if not findings:
            findings.append("✅ コード解析: 問題は検出されませんでした")

        return (not has_blocker), findings

    # ------------------------------------------------------------------
    # ruff
    # ------------------------------------------------------------------

    def _run_ruff(self, code: str) -> list[str]:
        findings: list[str] = []
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as f:
                f.write(code)
                f.flush()
                tmp_path = Path(f.name)

            result = subprocess.run(
                ["ruff", "check", "--select", "E,F,W", "--no-fix", str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    cleaned = re.sub(r"^.*\.py:", "L", line)
                    findings.append(f"📝 ruff: {cleaned}")
        except FileNotFoundError:
            logger.info("ruff が未インストールです — スキップ")
        except subprocess.TimeoutExpired:
            findings.append("⚠️ ruff: タイムアウト")
        except Exception as exc:
            logger.warning("ruff check failed: %s", exc)
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)
        return findings

    # ------------------------------------------------------------------
    # bandit
    # ------------------------------------------------------------------

    def _run_bandit(self, code: str) -> list[str]:
        findings: list[str] = []
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as f:
                f.write(code)
                f.flush()
                tmp_path = Path(f.name)

            result = subprocess.run(
                ["bandit", "-f", "json", "-q", str(tmp_path)],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.stdout.strip():
                data = json.loads(result.stdout)
                for issue in data.get("results", []):
                    severity = issue.get("issue_severity", "UNKNOWN")
                    text = issue.get("issue_text", "")
                    line = issue.get("line_number", "?")
                    prefix = "🚫" if severity == "HIGH" else "⚠️"
                    findings.append(
                        f"{prefix} bandit: L{line} {text} ({severity})"
                    )
        except FileNotFoundError:
            logger.info("bandit が未インストールです — スキップ")
        except subprocess.TimeoutExpired:
            findings.append("⚠️ bandit: タイムアウト")
        except Exception as exc:
            logger.warning("bandit check failed: %s", exc)
        finally:
            if tmp_path:
                tmp_path.unlink(missing_ok=True)
        return findings

    # ==================================================================
    # Trivy イメージスキャン
    # ==================================================================

    def scan_image_trivy(self, image_name: str) -> tuple[bool, list[str]]:
        """
        Trivy でコンテナイメージの脆弱性をスキャン。

        Returns
        -------
        (passed, findings)
        """
        findings: list[str] = []
        try:
            trivy = self._client.containers.get(TRIVY_CONTAINER_NAME)
            exit_code, output = trivy.exec_run(
                [
                    "trivy", "image",
                    "--severity", "HIGH,CRITICAL",
                    "--no-progress",
                    "--format", "json",
                    image_name,
                ],
                demux=True,
            )
            stdout = (output[0] or b"").decode("utf-8", errors="replace")
            stderr = (output[1] or b"").decode("utf-8", errors="replace")

            if not stdout.strip():
                findings.append("⚠️ Trivy: 出力なし（スキップ）")
                return True, findings

            try:
                report = json.loads(stdout)
            except json.JSONDecodeError:
                findings.append("⚠️ Trivy: JSON パース失敗（スキップ）")
                return True, findings

            critical_count = 0
            high_count = 0
            for result in report.get("Results", []):
                for vuln in result.get("Vulnerabilities", []):
                    sev = vuln.get("Severity", "")
                    if sev == "CRITICAL":
                        critical_count += 1
                    elif sev == "HIGH":
                        high_count += 1

            if critical_count > 0:
                findings.append(
                    f"🚫 Trivy: CRITICAL 脆弱性 {critical_count} 件検出"
                )
                return False, findings

            if high_count > 0:
                findings.append(
                    f"⚠️ Trivy: HIGH 脆弱性 {high_count} 件（続行可能）"
                )
            else:
                findings.append("✅ Trivy: 重大な脆弱性は検出されませんでした")

            return True, findings

        except NotFound:
            findings.append("⚠️ Trivy コンテナが見つかりません — スキップ")
            return True, findings
        except Exception as exc:
            findings.append(f"⚠️ Trivy スキャンエラー: {exc}")
            return True, findings
