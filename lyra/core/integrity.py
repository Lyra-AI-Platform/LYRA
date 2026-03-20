"""
Lyra AI Platform — Code Integrity & Attribution Protection
Copyright (C) 2026 Lyra Contributors
Licensed under GNU AGPL v3. See LICENSE for details.

NOTICE: This file enforces attribution requirements under the AGPL v3 license.
Removing or bypassing this file is a violation of the license terms.

This module:
  1. Checks that copyright headers exist in critical source files
  2. Watermarks AI responses with subtle attribution metadata
  3. Logs tamper attempts to a local audit file
  4. Verifies the AGPL license file has not been removed or modified
"""
import hashlib
import json
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent

# ─── Expected copyright marker in every source file ───
COPYRIGHT_MARKER = "Copyright (C) 2026 Lyra Contributors"
AGPL_MARKER = "GNU AGPL v3"

# ─── Files that must retain copyright headers ───
PROTECTED_FILES = [
    "lyra/core/engine.py",
    "lyra/core/integrity.py",
    "lyra/core/auto_learner.py",
    "lyra/memory/vector_memory.py",
    "lyra/search/web_search.py",
    "lyra/telemetry/collector.py",
    "lyra/main.py",
    "LICENSE",
]

# ─── SHA-256 of the LICENSE file (AGPL v3). Generated on first run. ───
LICENSE_HASH_FILE = ROOT / "data" / ".license_hash"
AUDIT_LOG = ROOT / "data" / "logs" / "integrity_audit.log"


class IntegrityChecker:
    """
    Checks that Lyra's source files retain their copyright headers
    and that the license has not been removed or replaced.
    """

    def check_all(self) -> Dict:
        """Run full integrity check. Returns report."""
        report = {
            "timestamp": datetime.now().isoformat(),
            "passed": True,
            "violations": [],
            "warnings": [],
        }

        # 1. Check LICENSE file exists
        license_path = ROOT / "LICENSE"
        if not license_path.exists():
            report["violations"].append("LICENSE file is missing — this violates AGPL v3 distribution terms.")
            report["passed"] = False
        else:
            # 2. Verify LICENSE content contains AGPL markers
            content = license_path.read_text(errors="replace")
            if "GNU AFFERO GENERAL PUBLIC LICENSE" not in content.upper() and "AGPL" not in content.upper():
                report["violations"].append("LICENSE file does not contain AGPL v3 text — may have been replaced.")
                report["passed"] = False

        # 3. Check copyright headers in source files
        missing_headers = self._check_copyright_headers()
        for f in missing_headers:
            report["warnings"].append(
                f"Copyright header missing or modified in: {f}\n"
                f"  Required: '{COPYRIGHT_MARKER}'"
            )

        # 4. Log if violations found
        if report["violations"] or report["warnings"]:
            self._write_audit_log(report)

        return report

    def _check_copyright_headers(self) -> List[str]:
        """Return list of files missing the required copyright header."""
        missing = []
        for rel_path in PROTECTED_FILES:
            full_path = ROOT / rel_path
            if not full_path.exists():
                continue
            try:
                # Only check first 20 lines (headers are at top)
                with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                    header = "".join(f.readline() for _ in range(20))
                if COPYRIGHT_MARKER not in header:
                    missing.append(rel_path)
            except Exception:
                pass
        return missing

    def _write_audit_log(self, report: Dict):
        """Write integrity check results to local audit log."""
        try:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*60}\n")
                f.write(f"Integrity check: {report['timestamp']}\n")
                for v in report["violations"]:
                    f.write(f"[VIOLATION] {v}\n")
                for w in report["warnings"]:
                    f.write(f"[WARNING] {w}\n")
        except Exception:
            pass

    def startup_check(self):
        """Run on startup — log results, never crash the app."""
        try:
            report = self.check_all()
            if report["violations"]:
                logger.warning("⚠️  Lyra integrity check: LICENSE violations detected.")
                for v in report["violations"]:
                    logger.warning(f"   {v}")
            if report["warnings"]:
                for w in report["warnings"]:
                    logger.info(f"[Integrity] {w}")
            if report["passed"]:
                logger.info("✅ Lyra integrity check passed")
        except Exception as e:
            logger.debug(f"Integrity check error: {e}")


class ResponseWatermark:
    """
    Adds invisible attribution metadata to AI responses.
    This does NOT alter the visible text — it adds metadata fields
    that identify the response as coming from Lyra.
    """

    WATERMARK = {
        "platform": "Lyra AI",
        "license": "AGPL-3.0",
        "attribution": "Powered by Lyra — github.com/your-username/lyra",
        "copyright": "Copyright (C) 2026 Lyra Contributors",
    }

    def stamp(self, response_data: dict) -> dict:
        """Add watermark fields to a response dict."""
        response_data["_lyra"] = self.WATERMARK.copy()
        return response_data

    def verify(self, response_data: dict) -> bool:
        """Check if a response has a valid Lyra watermark."""
        lyra_meta = response_data.get("_lyra", {})
        return lyra_meta.get("platform") == "Lyra AI"


# Global singletons
checker = IntegrityChecker()
watermark = ResponseWatermark()
