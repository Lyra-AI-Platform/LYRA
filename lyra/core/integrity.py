"""
Lyra AI Platform — Code Integrity, Attribution & Protection
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.
Licensed under the Lyra Community License v1.0. See LICENSE for details.

NOTICE: This software is proprietary. Unauthorized copying, modification,
reverse engineering, or distribution outside the terms of the Lyra Community
License v1.0 is strictly prohibited and may be subject to legal action.

This module enforces:
  1. Copyright header presence in all protected source files
  2. SHA-256 checksum verification — detects any file tampering
  3. Installation fingerprinting — unique per machine
  4. Audit logging of any integrity violations
  5. AI response watermarking with attribution metadata
"""
import base64
import hashlib
import json
import logging
import zlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List

logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent.parent.parent

# ── Copyright marker required in every protected file ──
COPYRIGHT_MARKER = "Copyright (C) 2026 Lyra Contributors"

# ── Files that must retain copyright headers ──
PROTECTED_FILES = [
    "lyra/core/engine.py",
    "lyra/core/integrity.py",
    "lyra/core/auto_learner.py",
    "lyra/core/cognition_engine.py",
    "lyra/core/synthesis_engine.py",
    "lyra/core/reasoning_engine.py",
    "lyra/core/reflection.py",
    "lyra/memory/vector_memory.py",
    "lyra/search/crawler.py",
    "lyra/api/chat.py",
    "lyra/main.py",
    "LICENSE",
]

# ── Checksum and fingerprint storage ──
_CHECKSUM_FILE = ROOT / "data" / ".c5"
_FINGERPRINT_FILE = ROOT / "data" / ".fp"
AUDIT_LOG = ROOT / "data" / "logs" / "integrity_audit.log"


def _enc(s: str) -> str:
    """Lightly encode a string to resist casual extraction."""
    return base64.b85encode(zlib.compress(s.encode(), 9)).decode()


def _dec(s: str) -> str:
    """Decode an encoded string."""
    try:
        return zlib.decompress(base64.b85decode(s)).decode()
    except Exception:
        return s


def _hash(path: Path) -> str:
    """SHA-256 of a file."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except Exception:
        return ""


def _fingerprint() -> str:
    """Get or create machine-unique installation fingerprint."""
    if _FINGERPRINT_FILE.exists():
        return _FINGERPRINT_FILE.read_text().strip()
    try:
        import uuid, platform
        raw = f"{uuid.getnode()}|{platform.node()}|{platform.machine()}"
        fp = hashlib.sha256(raw.encode()).hexdigest()
        _FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
        _FINGERPRINT_FILE.write_text(fp)
        return fp
    except Exception:
        return "unresolved"


def _save_checksums(cs: Dict[str, str]):
    try:
        _CHECKSUM_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CHECKSUM_FILE.write_text(_enc(json.dumps(cs)))
    except Exception:
        pass


def _load_checksums() -> Dict[str, str]:
    try:
        if _CHECKSUM_FILE.exists():
            return json.loads(_dec(_CHECKSUM_FILE.read_text().strip()))
    except Exception:
        pass
    return {}


class IntegrityChecker:
    """
    Startup integrity verification.

    On first run: fingerprints the installation and indexes checksums.
    On subsequent runs: verifies checksums, reports modified files.
    Always: checks copyright headers and LICENSE presence.
    """

    def check_all(self) -> Dict:
        report = {
            "timestamp": datetime.now().isoformat(),
            "passed": True,
            "violations": [],
            "warnings": [],
        }

        # 1. LICENSE file must exist
        license_path = ROOT / "LICENSE"
        if not license_path.exists():
            report["violations"].append(
                "LICENSE file missing — distribution terms violated."
            )
            report["passed"] = False
        else:
            content = license_path.read_text(errors="replace").upper()
            if "LYRA" not in content:
                report["violations"].append(
                    "LICENSE content does not reference Lyra — may have been replaced."
                )
                report["passed"] = False

        # 2. Copyright headers
        for rel in PROTECTED_FILES:
            full = ROOT / rel
            if not full.exists():
                continue
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    header = "".join(f.readline() for _ in range(20))
                if COPYRIGHT_MARKER not in header:
                    report["warnings"].append(
                        f"Copyright header missing: {rel}"
                    )
            except Exception:
                pass

        # 3. Checksum verification
        stored = _load_checksums()
        if stored:
            for rel, expected in stored.items():
                full = ROOT / rel
                if not full.exists():
                    report["warnings"].append(f"Protected file missing: {rel}")
                    continue
                actual = _hash(full)
                if actual != expected and actual != "":
                    report["warnings"].append(
                        f"File modified since installation: {rel}"
                    )

        if report["violations"] or report["warnings"]:
            self._audit(report)

        return report

    def _audit(self, report: Dict):
        try:
            AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
            with open(AUDIT_LOG, "a", encoding="utf-8") as f:
                f.write(f"\n{'='*55}\n[{report['timestamp']}]\n")
                for v in report["violations"]:
                    f.write(f"VIOLATION: {v}\n")
                for w in report["warnings"]:
                    f.write(f"WARNING: {w}\n")
        except Exception:
            pass

    def startup_check(self):
        """Run at startup. Never crashes the app — only logs."""
        try:
            fp = _fingerprint()
            stored = _load_checksums()

            if not stored:
                # First run: index all checksums
                cs = {
                    rel: _hash(ROOT / rel)
                    for rel in PROTECTED_FILES
                    if (ROOT / rel).exists()
                }
                _save_checksums(cs)
                logger.info(
                    f"Lyra: installation registered "
                    f"[{fp[:10]}...] | {len(cs)} modules indexed"
                )
            else:
                report = self.check_all()
                if report["violations"]:
                    logger.warning(
                        f"Lyra: integrity violations detected ({len(report['violations'])})"
                    )
                elif report["warnings"]:
                    logger.warning(
                        f"Lyra: {len(report['warnings'])} integrity warning(s) — "
                        "see data/logs/integrity_audit.log"
                    )
                else:
                    logger.info(f"Lyra: integrity verified [{fp[:10]}...]")
        except Exception as e:
            logger.debug(f"Integrity check error: {e}")


class ResponseWatermark:
    """
    Embeds invisible attribution metadata into AI response payloads.
    Does not modify visible text — adds a metadata field only.
    """

    # Encoded to resist trivial extraction
    _W = _enc(json.dumps({
        "platform": "Lyra AI",
        "copyright": "Copyright (C) 2026 Lyra Contributors",
        "license": "Lyra Community License v1.0",
    }))

    def stamp(self, response_data: dict) -> dict:
        response_data["_l"] = self._W
        return response_data

    def verify(self, response_data: dict) -> bool:
        try:
            meta = json.loads(_dec(response_data.get("_l", "")))
            return meta.get("platform") == "Lyra AI"
        except Exception:
            return False


# Global singletons
checker = IntegrityChecker()
watermark = ResponseWatermark()
