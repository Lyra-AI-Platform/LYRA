"""UK workplace exposure limits from HSE EH40/2005 Table 1 (stored, never guessed)."""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

DATA = Path(__file__).parent / "data" / "eh40.json"
CAS_RE = re.compile(r"^\d{2,7}-\d\d-\d$")


def _norm(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _value(v: str) -> Optional[str]:
    v = v.strip()
    return None if v in ("", "-") else v


def _rows(entry: dict) -> List[dict]:
    """One row per dust fraction. Multi-line entries list inhalable then respirable."""
    names = entry["substance"].split("\n")
    cols = {k: entry[k].split("\n") for k in ("twa_ppm", "twa_mg_m3", "stel_ppm", "stel_mg_m3")}
    n = max(len(c) for c in cols.values())
    fractions = [f.strip() for f in names[1:]] if len(names) > 1 else []
    out = []
    for i in range(n):
        out.append({
            "fraction": fractions[i] if i < len(fractions) else None,
            **{k: _value(c[i]) if i < len(c) else None for k, c in cols.items()},
        })
    return out


@lru_cache(maxsize=1)
def table() -> dict:
    return json.loads(DATA.read_text())


@lru_cache(maxsize=1)
def _index() -> Dict[str, List[dict]]:
    idx: Dict[str, List[dict]] = {}
    for e in table()["entries"]:
        if CAS_RE.match(e["cas"]):
            idx.setdefault(e["cas"], []).append(e)
        idx.setdefault("n:" + _norm(e["substance"].split("\n")[0]), []).append(e)
    for synonym, listed in table().get("synonyms", []):
        idx.setdefault("n:" + _norm(synonym), idx.get("n:" + _norm(listed), []))
    return idx


def _bmgv(substance: str) -> Optional[dict]:
    """EH40 Table 2 biological monitoring guidance value, matched by name prefix."""
    key = _norm(substance)
    for b in table().get("bmgv", []):
        if key.startswith(_norm(b["substance"]).split("applies")[0][:12]):
            return b
    return None


def lookup(cas: Optional[str] = None, names: Optional[List[str]] = None) -> Optional[dict]:
    """The EH40 entry for a substance, matched by CAS number first, then by exact name."""
    hits = _index().get(cas or "") or []
    for n in names or []:
        if hits:
            break
        hits = _index().get("n:" + _norm(n)) or []
    group = None
    if not hits and any("isocyanate" in n.lower() for n in names or []) \
            and not any(_norm(n) == "methylisocyanate" for n in names or []):
        # EH40 covers every isocyanate except methyl isocyanate under one group entry.
        hits = [e for e in table()["entries"] if e["substance"].startswith("Isocyanates, all")]
        group = "Isocyanates, all (as –NCO)"
    if not hits:
        return None
    e = hits[0]
    comments = e["comments"]
    notations = [n for n in ("Carc", "Sen", "Sk") if re.search(rf"\b{n}\b", comments)]
    return {
        "substance": " ".join(e["substance"].split("\n")[:1]),
        "cas": e["cas"] or None,
        "limits": _rows(e),
        "notations": notations,
        "comments": comments or None,
        "bmgv": _bmgv(e["substance"]) if "BMGV" in comments else None,
        "group_entry": group,
        "source": table()["source"],
    }
