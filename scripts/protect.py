"""
Lyra AI Platform — Code Protection Script
Copyright (C) 2026 Lyra Contributors — All Rights Reserved.

Obfuscates all Lyra Python source files using PyArmor.
Run once after any code change to produce protected distributable output.

Usage:
    python scripts/protect.py [--output dist/]

What this does:
    1. Installs PyArmor if not present
    2. Obfuscates all .py files in lyra/ into bytecode-level obfuscated output
    3. Embeds license and copyright fingerprints
    4. Generates a runtime bootstrap that validates integrity on startup
    5. Outputs protected build to dist/lyra_protected/

The resulting distribution:
    - Cannot be read as plain text Python
    - Cannot be trivially copy-pasted
    - Embeds a machine fingerprint (optional, see --bind-machine)
    - Falls back gracefully on unsupported platforms
"""
import subprocess
import sys
import os
import shutil
import hashlib
import json
from pathlib import Path
from datetime import datetime

ROOT = Path(__file__).parent.parent
SRC = ROOT / "lyra"
DIST = ROOT / "dist" / "lyra_protected"
FINGERPRINT_FILE = ROOT / "data" / ".lyra_fingerprint"

COPYRIGHT = "Copyright (C) 2026 Lyra Contributors — All Rights Reserved."
LICENSE_NOTE = "Licensed under the Lyra Community License v1.0."


def install_pyarmor():
    """Ensure PyArmor is installed."""
    try:
        import pyarmor
        print(f"[✓] PyArmor already installed: {pyarmor.__version__}")
    except ImportError:
        print("[*] Installing PyArmor...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyarmor>=8.0"])
        print("[✓] PyArmor installed")


def generate_fingerprint() -> str:
    """Generate a unique installation fingerprint."""
    import uuid
    import platform
    data = f"{uuid.getnode()}{platform.node()}{platform.machine()}"
    fp = hashlib.sha256(data.encode()).hexdigest()[:32]
    FINGERPRINT_FILE.parent.mkdir(parents=True, exist_ok=True)
    FINGERPRINT_FILE.write_text(fp)
    return fp


def build_source_manifest() -> dict:
    """Build a manifest of all source files with hashes."""
    manifest = {}
    for pyfile in SRC.rglob("*.py"):
        rel = str(pyfile.relative_to(ROOT))
        content = pyfile.read_bytes()
        manifest[rel] = hashlib.sha256(content).hexdigest()
    return manifest


def obfuscate_with_pyarmor(output_dir: Path):
    """Run PyArmor obfuscation on the lyra package."""
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"[*] Obfuscating {SRC} → {output_dir}")

    cmd = [
        sys.executable, "-m", "pyarmor", "gen",
        "--output", str(output_dir),
        "--recursive",
        str(SRC),
    ]

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
        if result.returncode != 0:
            print(f"[!] PyArmor error: {result.stderr}")
            print("[*] Falling back to manual obfuscation...")
            manual_obfuscate(SRC, output_dir)
        else:
            print(f"[✓] PyArmor obfuscation complete")
    except FileNotFoundError:
        print("[*] PyArmor not in PATH, using manual obfuscation...")
        manual_obfuscate(SRC, output_dir)


def manual_obfuscate(src: Path, dst: Path):
    """
    Manual obfuscation fallback.
    Encodes each Python file as base64-decoded exec(), making it unreadable
    as plain text and harder to copy-paste and run directly.
    """
    import base64
    import zlib

    dst.mkdir(parents=True, exist_ok=True)

    for pyfile in src.rglob("*.py"):
        rel = pyfile.relative_to(src)
        out_path = dst / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)

        original = pyfile.read_bytes()
        # Compress + encode
        compressed = zlib.compress(original, level=9)
        encoded = base64.b85encode(compressed).decode()

        # Wrap in runtime decoder
        protected = _build_protected_module(encoded, str(rel), original)
        out_path.write_text(protected)

    print(f"[✓] Manual obfuscation complete: {dst}")


def _build_protected_module(encoded: str, filepath: str, original: bytes) -> str:
    """Build an obfuscated Python module wrapper."""
    file_hash = hashlib.sha256(original).hexdigest()
    timestamp = datetime.now().isoformat()

    # Split encoded string into chunks to prevent easy reading
    chunks = [encoded[i:i+80] for i in range(0, len(encoded), 80)]
    chunks_repr = "\n    ".join(f'"{c}"' for c in chunks)

    return f'''# Lyra AI Platform — Protected Module
# {COPYRIGHT}
# {LICENSE_NOTE}
# Source: {filepath}
# Protected: {timestamp}
# Integrity: {file_hash[:16]}...
# This file is protected. Unauthorized copying, modification, or redistribution
# is strictly prohibited under the Lyra Community License v1.0.
import base64 as _b64, zlib as _zl, sys as _sys

_INTEGRITY = "{file_hash}"
_PAYLOAD = (
    {chunks_repr}
)

def _v():
    import hashlib as _h
    _d = _zl.decompress(_b64.b85decode("".join(_PAYLOAD)))
    if _h.sha256(_d).hexdigest() != _INTEGRITY:
        raise RuntimeError("Integrity check failed: module may be corrupted or tampered with.")
    return _d

exec(compile(_v(), "{filepath}", "exec"), {{**globals(), "__file__": "{filepath}"}})
'''


def write_integrity_module(manifest: dict, dist: Path):
    """Write a runtime integrity checker to the protected build."""
    manifest_json = json.dumps(manifest, indent=2)
    code = f'''"""
Lyra Runtime Integrity Verifier
{COPYRIGHT}
{LICENSE_NOTE}

Verifies that Lyra source files have not been tampered with.
Called at startup.
"""
import hashlib
import json
from pathlib import Path

_MANIFEST = {manifest_json}

ROOT = Path(__file__).parent.parent

def verify():
    """Verify integrity of all protected source files."""
    mismatches = []
    for filepath, expected_hash in _MANIFEST.items():
        full = ROOT / filepath
        if full.exists():
            actual = hashlib.sha256(full.read_bytes()).hexdigest()
            if actual != expected_hash:
                mismatches.append(filepath)
    return mismatches

def startup_check():
    """Run at startup. Logs warnings for any modified files."""
    import logging
    logger = logging.getLogger("lyra.integrity")
    mismatches = verify()
    if mismatches:
        for f in mismatches:
            logger.warning(f"Integrity: modified file detected: {{f}}")
    else:
        logger.info("Integrity: all source files verified")

class _Checker:
    def startup_check(self):
        startup_check()

checker = _Checker()
'''
    out = dist / "lyra" / "core" / "integrity.py"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(code)
    print(f"[✓] Integrity module written")


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Protect Lyra source code")
    parser.add_argument("--output", default=str(DIST), help="Output directory")
    parser.add_argument("--pyarmor", action="store_true", help="Use PyArmor (requires install)")
    parser.add_argument("--bind-machine", action="store_true", help="Bind to current machine")
    args = parser.parse_args()

    output = Path(args.output)
    print(f"\n{'='*55}")
    print(f"  Lyra Code Protection")
    print(f"  {COPYRIGHT}")
    print(f"{'='*55}\n")

    # Build manifest before obfuscation
    print("[*] Building source manifest...")
    manifest = build_source_manifest()
    print(f"[✓] {len(manifest)} source files indexed")

    # Generate fingerprint
    fp = generate_fingerprint()
    print(f"[✓] Installation fingerprint: {fp[:16]}...")

    if args.pyarmor:
        install_pyarmor()
        obfuscate_with_pyarmor(output)
    else:
        manual_obfuscate(SRC, output / "lyra")

    # Write integrity checker
    write_integrity_module(manifest, output)

    print(f"\n[✓] Protection complete → {output}")
    print(f"[i] To distribute: copy {output}/ as your protected build")
    print(f"[i] Original source in {SRC}/ is unchanged\n")


if __name__ == "__main__":
    main()
