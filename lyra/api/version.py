"""Which commit is running, for /health. No web imports, so it can be tested on its own."""
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent


def read_git_head(root: Path) -> Optional[str]:
    """The commit in root/.git, read directly: the container may not have the git program."""
    git = root / ".git"
    try:
        head = (git / "HEAD").read_text().strip()
        if not head.startswith("ref: "):
            return head or None
        ref = head[5:]
        loose = git / ref
        if loose.exists():
            return loose.read_text().strip() or None
        for line in (git / "packed-refs").read_text().splitlines():
            if line.endswith(" " + ref):
                return line.split(" ", 1)[0]
    except OSError:
        pass
    return None


@lru_cache(maxsize=1)
def commit() -> str:
    return os.environ.get("LYRA_COMMIT", "").strip() or read_git_head(ROOT) or "unknown"
