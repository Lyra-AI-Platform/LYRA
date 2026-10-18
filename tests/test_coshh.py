"""Offline tests for COSHH AI: EH40 lookups, SDS compilation and the guidance rules.
The PubChem fixture is a trimmed copy of the real acetone record (CID 180)."""
import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("LYRA_COSHH_DIR", tempfile.mkdtemp(prefix="lyra-coshh-test-"))

from lyra.coshh import guidance, sds, wel  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "pubchem_acetone"
ACETONE_PROPS = {"CID": 180, "MolecularFormula": "C3H6O", "MolecularWeight": "58.08", "SMILES": "CC(=O)C",
                 "InChIKey": "CSCPPACGZOOCGX-UHFFFAOYSA-N", "IUPACName": "propan-2-one", "Title": "Acetone"}


def acetone_parts():
    return {f.stem.replace("_", " "): json.loads(f.read_text())["Record"] for f in FIXTURES.glob("*.json")}


def acetone_sheet():
    return sds.compile_sheet(180, ACETONE_PROPS, acetone_parts(), "2026-10-18 00:00 UTC")


# ---- EH40 -------------------------------------------------------------------

def test_wel_by_cas_matches_eh40_table_1():
    w = wel.lookup("67-64-1")
    assert w["limits"] == [{"fraction": None, "twa_ppm": "500", "twa_mg_m3": "1210",
                            "stel_ppm": "1500", "stel_mg_m3": "3620"}]
    assert w["notations"] == []


def test_wel_notations_and_bmgv():
    benzene = wel.lookup("71-43-2")
    assert set(benzene["notations"]) == {"Carc", "Sk"}
    mek = wel.lookup("78-93-3")
    assert mek["notations"] == ["Sk"]
    assert "butan-2-one" in mek["bmgv"]["bmgv"]


def test_wel_by_eh40_synonym_and_dust_fractions():
    assert wel.lookup(None, ["Methyl ethyl ketone"])["cas"] == "78-93-3"
    al = wel.lookup("7429-90-5")
    assert [l["fraction"] for l in al["limits"]] == ["inhalable dust", "respirable dust"]
    assert [l["twa_mg_m3"] for l in al["limits"]] == ["10", "4"]


def test_wel_isocyanate_group_but_not_methyl_isocyanate():
    mdi = wel.lookup("26447-40-5", ["Diphenylmethane diisocyanate"])
    assert mdi["group_entry"] and mdi["substance"].startswith("Isocyanates, all")
    # Methyl isocyanate has its own, much lower entry and must never fall into the group.
    assert wel.lookup(None, ["Methyl isocyanate"]) is None
    assert wel.lookup("624-83-9")["substance"].startswith("Methyl isocyanate")


def test_wel_unknown_is_none():
    assert wel.lookup("9999-99-9", ["not a chemical"]) is None


# ---- SDS compilation ---------------------------------------------------------

def test_sheet_identity_and_ghs():
    s = acetone_sheet()
    i = s["identity"]
    assert (i["cas"], i["ec"], i["un"]) == ("67-64-1", "200-662-2", ["1090"])
    g = s["ghs"]
    assert g["signal"] == "Danger"
    assert {"H225", "H319", "H336"} <= set(g["codes"])
    assert {p["code"] for p in g["pictograms"]} == {"GHS02", "GHS07"}
    p210 = next(p for p in g["precautions"] if p["code"] == "P210")
    assert p210["text"].startswith("Keep away from heat")


def test_sheet_has_16_sections_and_every_item_is_cited():
    s = acetone_sheet()
    assert [x["number"] for x in s["sections"]] == list(range(1, 17))
    for sec in s["sections"]:
        for b in sec["blocks"]:
            for it in b["items"]:
                assert it["ref"] in s["references"], (b["heading"], it)
    assert s["wel"]["cas"] == "67-64-1"


def test_spectra_peaks_and_kovats():
    sp = acetone_sheet()["spectra"]
    nmr = next(r for r in sp["records"] if r["technique"] == "1H NMR" and r["peaks"])
    assert nmr["peaks"][0][0] == 2.22
    ms = next(r for r in sp["records"] if r["technique"] == "GC-MS" and r["peaks"])
    assert ms["peaks"][0] == [43.0, 99.99]
    assert any(k["column"] == "Standard polar" for k in sp["kovats"])


# ---- Guidance rules ----------------------------------------------------------

def _sheet_with(codes, notations=(), bmgv=None):
    return {"ghs": {"codes": list(codes), "classified": bool(codes),
                    "precautions": [{"code": "P280"}]},
            "wel": {"notations": list(notations), "limits": [{}], "bmgv": bmgv} if notations or bmgv else None}


def labels(g):
    return {f["label"] for f in g["flags"]}


def test_acetone_is_flammable_but_not_a_peroxide_former():
    # "Contact with ... hydrogen peroxide generates explosive peroxides" is a reaction, not peroxide formation on storage.
    g = acetone_sheet()["guidance"]
    assert "DSEAR dangerous substance" in labels(g)
    assert "Peroxide former" not in labels(g)
    assert any(c["title"].startswith("DSEAR") for c in g["cards"])


def test_peroxide_former_from_cited_text():
    idx = {"Stability/Shelf Life": [{"Information": [{"Value": {"StringWithMarkup": [
        {"String": "Tends to form explosive peroxides under influence of air and light."}]}}]}]}
    assert "Peroxide former" in labels(guidance.build(_sheet_with(["H224"]), idx))


def test_carcinogen_asthmagen_and_reproductive_rules():
    g = guidance.build(_sheet_with(["H350i", "H334", "H360FD"]), {})
    assert {"Carcinogen / mutagen", "Asthmagen (respiratory sensitiser)", "Reproductive toxin"} <= labels(g)
    titles = {c["title"] for c in g["cards"]}
    assert "Can cause occupational asthma" in titles
    assert any("40 years" in p for c in g["cards"] for p in c["points"])


def test_skin_notation_and_bmgv_reach_health_surveillance():
    g = guidance.build(_sheet_with(["H315"], ["Sk"], {"bmgv": "650 mmol x/mol creatinine", "sampling": "Post shift"}), {})
    hs = next(c for c in g["cards"] if c["category"] == "Health surveillance")
    assert any("650 mmol" in p for p in hs["points"])


def test_water_reactive_and_no_hazard_cases():
    g = guidance.build(_sheet_with(["H260", "H314"]), {})
    assert "Reacts with water" in labels(g)
    assert any("Do NOT use water" in p for c in g["cards"] for p in c["points"])
    none = guidance.build({"ghs": {"codes": [], "classified": False, "precautions": []}, "wel": None}, {})
    assert labels(none) == {"No GHS classification found"}
