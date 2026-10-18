"""Compile a 16-section safety data sheet from PubChem PUG-View records.

Every line keeps the reference number of the PubChem source it came from, so
the page can show where each statement was published. Nothing is generated:
a section with no source data says so.
"""
import json
import re
import statistics
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from lyra.coshh import guidance, wel

GHS_CODES = Path(__file__).parent / "data" / "ghs_codes.json"
CODE_RE = re.compile(r"\b(EUH\d{3}|H\d{3}[A-Za-z]{0,2})\b")
P_CODE_RE = re.compile(r"\bP\d{3}(?:\+P\d{3})*")
CAS_RE = re.compile(r"^\d{2,7}-\d\d-\d$")
PER_HEADING = 40


@lru_cache(maxsize=1)
def ghs_codes() -> dict:
    return json.loads(GHS_CODES.read_text())


# Section number, title, and the PubChem headings it draws on (heading, label).
SECTIONS = [
    (1, "Identification", [("Uses", "Identified uses"), ("Use Classification", "Use classification"),
                           ("Industry Uses", "Industry uses"), ("Consumer Uses", "Consumer uses")]),
    (2, "Hazard identification", [("Hazard Classes and Categories", "Hazard classes and categories"),
                                  ("NFPA Hazard Classification", "NFPA 704"), ("Health Hazards", "Health hazards"),
                                  ("Fire Hazards", "Fire hazards"), ("Hazards Summary", "Hazards summary"),
                                  ("Skin, Eye, and Respiratory Irritations", "Skin, eye and respiratory irritation")]),
    (3, "Composition / information on ingredients", []),
    (4, "First-aid measures", [("First Aid", "First aid"), ("Antidote and Emergency Treatment", "Antidote and emergency treatment"),
                               ("Medical Surveillance", "Medical surveillance"), ("Signs and Symptoms", "Signs and symptoms"),
                               ("Treatment", "Treatment")]),
    (5, "Firefighting measures", [("Fire Fighting Procedures", "Firefighting procedures"),
                                  ("Firefighting Hazards", "Firefighting hazards"), ("Fire Potential", "Fire potential"),
                                  ("Fire Prevention", "Fire prevention")]),
    (6, "Accidental release measures", [("Isolation and Evacuation", "Isolation and evacuation"),
                                        ("Spillage Disposal", "Spillage disposal"), ("Cleanup Methods", "Clean-up methods"),
                                        ("Nonfire Spill Response", "Non-fire spill response"),
                                        ("Preventive Measures", "Preventive measures")]),
    (7, "Handling and storage", [("Safe Storage", "Safe storage"), ("Storage Conditions", "Storage conditions")]),
    (8, "Exposure controls / personal protection", [
        ("Occupational Exposure Limits (OEL)", "Other occupational exposure limits"),
        ("Threshold Limit Values (TLV)", "ACGIH TLV (US)"), ("Recommended Exposure Limit (REL)", "NIOSH REL (US)"),
        ("Permissible Exposure Limit (PEL)", "OSHA PEL (US)"),
        ("Immediately Dangerous to Life or Health (IDLH)", "IDLH (US)"),
        ("Personal Protective Equipment (PPE)", "Personal protective equipment"),
        ("Respirator Recommendations", "Respirator recommendations"), ("Inhalation Prevention", "Inhalation prevention"),
        ("Skin Prevention", "Skin prevention"), ("Eye Prevention", "Eye prevention"),
        ("Ingestion Prevention", "Ingestion prevention"), ("Inhalation Risk", "Inhalation risk")]),
    (9, "Physical and chemical properties", [
        ("Physical Description", "Appearance"), ("Color/Form", "Colour / form"), ("Odor", "Odour"),
        ("Odor Threshold", "Odour threshold"), ("Melting Point", "Melting point"), ("Boiling Point", "Boiling point"),
        ("Flash Point", "Flash point"), ("Autoignition Temperature", "Auto-ignition temperature"),
        ("Lower Explosive Limit (LEL)", "Lower explosive limit"), ("Upper Explosive Limit (UEL)", "Upper explosive limit"),
        ("Flammable Limits", "Flammable limits"), ("Vapor Pressure", "Vapour pressure"),
        ("Vapor Density", "Vapour density (air = 1)"), ("Density", "Density"), ("Solubility", "Solubility"),
        ("LogP", "Partition coefficient (log Kow)"), ("Viscosity", "Viscosity"),
        ("Dissociation Constants", "pKa"), ("Decomposition", "Decomposition"), ("pH", "pH")]),
    (10, "Stability and reactivity", [
        ("Reactivity Profile", "Reactivity profile"), ("Hazardous Reactivities and Incompatibilities", "Incompatible materials"),
        ("Air and Water Reactions", "Air and water reactions"), ("Stability/Shelf Life", "Stability / shelf life"),
        ("Chemical Dangers", "Chemical dangers"), ("Physical Dangers", "Physical dangers"),
        ("Reactive Group", "Reactive groups")]),
    (11, "Toxicological information", [
        ("Toxicity Summary", "Toxicity summary"), ("Exposure Routes", "Routes of exposure"),
        ("Target Organs", "Target organs"), ("Acute Effects", "Acute effects"),
        ("Effects of Short Term Exposure", "Effects of short-term exposure"),
        ("Effects of Long Term Exposure", "Effects of long-term exposure"),
        ("Carcinogen Classification", "Carcinogen classification"), ("Evidence for Carcinogenicity", "Evidence for carcinogenicity"),
        ("Human Toxicity Values", "Human toxicity values"), ("Non-Human Toxicity Values", "Animal toxicity values (LD50 / LC50)"),
        ("Populations at Special Risk", "Populations at special risk"), ("Interactions", "Interactions")]),
    (12, "Ecological information", [
        ("Ecotoxicity Values", "Ecotoxicity values"), ("Environmental Fate/Exposure Summary", "Environmental fate"),
        ("Environmental Biodegradation", "Biodegradation"), ("Environmental Bioconcentration", "Bioaccumulation"),
        ("Soil Adsorption/Mobility", "Mobility in soil")]),
    (13, "Disposal considerations", [("Disposal Methods", "Disposal methods"),
                                     ("EPA Hazardous Waste Number", "US EPA hazardous waste number")]),
    (14, "Transport information", [
        ("UN Number", "UN number"), ("UN Classification", "UN classification"),
        ("Shipping Name/ Number DOT/UN/NA/IMO", "Proper shipping name"), ("DOT Label", "Transport label"),
        ("DOT Emergency Guidelines", "Emergency response guide"), ("Shipment Methods and Regulations", "Shipment rules")]),
    (15, "Regulatory information", [
        ("Regulatory Information", "Regulatory listings (REACH, EU and international)"),
        ("REACH Registered Substance", "REACH registration"), ("REACH Restricted Substance", "REACH restriction"),
        ("REACH Substances of Very High Concern (SVHC)", "REACH SVHC candidate list"),
        ("EU Regulations", "EU regulations"), ("Atmospheric Standards", "US atmospheric standards"),
        ("CERCLA Reportable Quantities", "US CERCLA reportable quantity"), ("RCRA Requirements", "US RCRA"),
        ("FDA Requirements", "US FDA requirements")]),
    (16, "Other information", []),
]


def index_sections(parts: Dict[str, Optional[dict]]) -> Dict[str, List[dict]]:
    """Every PUG-View section across the fetched records, keyed by heading."""
    idx: Dict[str, List[dict]] = {}

    def walk(sec):
        for s in sec.get("Section", []):
            idx.setdefault(s["TOCHeading"], []).append(s)
            walk(s)
    for rec in parts.values():
        if rec:
            walk(rec)
    return idx


def references(parts: Dict[str, Optional[dict]]) -> Dict[int, dict]:
    refs = {}
    for rec in parts.values():
        for r in (rec or {}).get("Reference", []):
            refs[r["ReferenceNumber"]] = {"source": r.get("SourceName", ""), "name": r.get("Name", ""),
                                          "url": r.get("URL", ""), "license": r.get("LicenseURL", "")}
    return refs


def value_text(value: dict) -> List[str]:
    """The readable strings in a PUG-View Value."""
    if "StringWithMarkup" in value:
        return [s["String"].strip() for s in value["StringWithMarkup"] if s.get("String", "").strip()]
    if "Number" in value:
        nums = ", ".join(f"{n:g}" for n in value["Number"])
        return [f"{nums} {value.get('Unit', '')}".strip()]
    return []


def _info(idx: Dict[str, List[dict]], heading: str) -> Iterable[dict]:
    for sec in idx.get(heading, []):
        yield from sec.get("Information", [])


def items(idx: Dict[str, List[dict]], heading: str, limit: int = PER_HEADING) -> dict:
    """De-duplicated statements under one heading, each with its source reference."""
    out, seen, total = [], set(), 0
    for info in _info(idx, heading):
        text = " ".join(value_text(info.get("Value", {})))
        if not text:
            continue
        key = re.sub(r"\W+", "", text.lower())[:300]
        if key in seen:
            continue
        seen.add(key)
        total += 1
        if len(out) < limit:
            name = info.get("Name")
            out.append({"text": f"{name}: {text}" if name and name not in ("Value", heading) else text,
                        "ref": info.get("ReferenceNumber")})
    return {"items": out, "more": total - len(out)}


def ghs(idx: Dict[str, List[dict]]) -> dict:
    """The GHS classification, preferring the aggregated ECHA C&L notifications (the EU/GB view)."""
    groups: Dict[int, dict] = {}
    for info in _info(idx, "GHS Classification"):
        g = groups.setdefault(info.get("ReferenceNumber"), {"ref": info.get("ReferenceNumber"), "fields": {}})
        g["fields"].setdefault(info.get("Name", ""), []).append(info.get("Value", {}))
    if not groups:
        return {"classified": False, "pictograms": [], "signal": None, "hazards": [], "precautions": [],
                "codes": [], "ref": None, "notes": [], "other_sources": 0}
    chosen = next((g for g in groups.values() if "ECHA C&L Notifications Summary" in g["fields"]),
                  next(iter(groups.values())))
    f = chosen["fields"]
    pictograms = []
    for v in f.get("Pictogram(s)", []):
        for s in v.get("StringWithMarkup", []):
            for m in s.get("Markup", []):
                if m.get("Type") == "Icon":
                    code = re.search(r"GHS\d\d", m.get("URL", ""))
                    pictograms.append({"code": code.group(0) if code else "", "name": m.get("Extra", ""),
                                       "url": m.get("URL", "")})
    hazards = [t for v in f.get("GHS Hazard Statements", []) for t in value_text(v)]
    codes = sorted({c for h in hazards for c in CODE_RE.findall(h.split(":")[0])})
    p_text = " ".join(t for v in f.get("Precautionary Statement Codes", []) for t in value_text(v))
    table = ghs_codes()["p"]
    precautions = []
    for code in dict.fromkeys(P_CODE_RE.findall(p_text)):
        text = table.get(code) or " ".join(table.get(c, "") for c in code.split("+")).strip()
        precautions.append({"code": code, "text": text or None})
    signal = next((t for v in f.get("Signal", []) for t in value_text(v)), None)
    notes = [t for k in ("Note", "ECHA C&L Notifications Summary") for v in f.get(k, []) for t in value_text(v)]
    return {"classified": bool(hazards), "pictograms": pictograms, "signal": signal, "hazards": hazards,
            "precautions": precautions, "codes": codes, "ref": chosen["ref"], "notes": notes,
            "other_sources": len(groups) - 1}


def _first(idx, heading) -> Optional[str]:
    for info in _info(idx, heading):
        t = value_text(info.get("Value", {}))
        if t:
            return t[0]
    return None


def _all(idx, heading, pattern=None) -> List[str]:
    out = []
    for info in _info(idx, heading):
        for t in value_text(info.get("Value", {})):
            if (pattern is None or re.match(pattern, t)) and t not in out:
                out.append(t)
    return out


def _records(sec: dict) -> List[dict]:
    """Split a spectra section's flat Information list into one record per spectrum."""
    recs: List[dict] = []
    cur: Optional[dict] = None
    for info in sec.get("Information", []):
        name = info.get("Name", "")
        ref = info.get("ReferenceNumber")
        if cur is None or name in cur["fields"] or ref != cur["ref"]:
            cur = {"ref": ref, "fields": {}, "links": {}}
            recs.append(cur)
        v = info.get("Value", {})
        cur["fields"][name] = " ".join(value_text(v)) if name != "Top 5 Peaks" else value_text(v)
        if info.get("URL"):
            cur["links"][name] = info["URL"]
        if v.get("ExternalDataURL"):
            cur["links"].setdefault(name, v["ExternalDataURL"][0])
    return recs


def _peaks(fields: dict) -> List[List[float]]:
    for k, v in fields.items():
        if k.startswith("Shifts [ppm]") and isinstance(v, str):
            pts = []
            for part in v.split(","):
                xs = part.strip().split(":")
                try:
                    pts.append([float(x) for x in xs])
                except ValueError:
                    pass
            return pts
        if k == "Top 5 Peaks":
            pts = []
            for line in v:
                try:
                    mz, inten = line.split()[:2]
                    pts.append([float(mz), float(inten)])
                except ValueError:
                    pass
            return pts
    return []


SPECTRA_GROUPS = {
    "1H NMR Spectra": "nmr", "13C NMR Spectra": "nmr", "15N NMR Spectra": "nmr", "17O NMR Spectra": "nmr",
    "19F NMR Spectra": "nmr", "31P NMR Spectra": "nmr", "Other NMR Spectra": "nmr", "1H-13C NMR Spectra": "nmr2d",
    "1H-1H NMR Spectra": "nmr2d", "GC-MS": "ms", "MS-MS": "ms", "LC-MS": "ms", "Other MS": "ms",
    "FTIR Spectra": "ir", "ATR-IR Spectra": "ir", "Near IR Spectra": "ir", "Vapor Phase IR Spectra": "ir",
    "Other IR Spectra": "ir", "IR Spectra": "ir", "Raman Spectra": "raman", "UV Spectra": "uv", "UV-VIS Spectra": "uv",
}


def spectra(idx: Dict[str, List[dict]]) -> dict:
    out = []
    for heading, kind in SPECTRA_GROUPS.items():
        for sec in idx.get(heading, []):
            for rec in _records(sec):
                fields = {k: v for k, v in rec["fields"].items() if k not in ("Thumbnail",)}
                if not fields:
                    continue
                out.append({"technique": heading.replace(" Spectra", ""), "kind": kind, "ref": rec["ref"],
                            "fields": fields, "links": rec["links"], "peaks": _peaks(rec["fields"])})
    kovats = []
    for info in _info(idx, "Kovats Retention Index"):
        nums = info.get("Value", {}).get("Number") or []
        if nums:
            kovats.append({"column": info.get("Name", ""), "median": round(statistics.median(nums), 1),
                           "min": min(nums), "max": max(nums), "n": len(nums), "ref": info.get("ReferenceNumber")})
    return {"records": out, "kovats": kovats}


def compile_sheet(cid: int, props: dict, parts: Dict[str, Optional[dict]], retrieved: str) -> dict:
    idx = index_sections(parts)
    refs = references(parts)
    cas_all = _all(idx, "CAS", r"^\d{2,7}-\d\d-\d$")
    cas = cas_all[0] if cas_all else None
    title = props.get("Title") or props.get("IUPACName") or f"CID {cid}"
    ident = {
        "cid": cid, "name": title, "iupac": props.get("IUPACName"), "formula": props.get("MolecularFormula"),
        "molecular_weight": props.get("MolecularWeight"), "smiles": props.get("SMILES"),
        "inchikey": props.get("InChIKey"), "cas": cas, "other_cas": cas_all[1:5],
        "ec": _first(idx, "European Community (EC) Number"),
        "un": [u for u in _all(idx, "UN Number") if re.fullmatch(r"\d{4}", u)][:6],
        "icsc": _first(idx, "ICSC Number"),
        "structure_image": f"https://pubchem.ncbi.nlm.nih.gov/rest/pug/compound/cid/{cid}/PNG?image_size=300x300",
        "pubchem_url": f"https://pubchem.ncbi.nlm.nih.gov/compound/{cid}",
    }
    classification = ghs(idx)
    limit = wel.lookup(cas, [title, props.get("IUPACName") or ""])
    sections = []
    for num, name, headings in SECTIONS:
        blocks = []
        for heading, label in headings:
            got = items(idx, heading)
            if got["items"]:
                blocks.append({"label": label or heading, "heading": heading, **got})
        sections.append({"number": num, "title": name, "blocks": blocks})
    sheet = {
        "identity": ident, "ghs": classification, "wel": limit, "sections": sections,
        "spectra": spectra(idx), "references": refs, "retrieved": retrieved,
        "sources": {
            "pubchem": "PubChem, National Library of Medicine (NIH). Each line cites the depositor.",
            "eh40": wel.table()["source"],
            "ghs_codes": ghs_codes()["source"],
        },
    }
    sheet["guidance"] = guidance.build(sheet, idx)
    return sheet
