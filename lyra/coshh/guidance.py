"""COSHH guidance a classic SDS leaves out, derived by rule from the GHS
hazard statements and the EH40 entry.

Each card names the UK regulation or HSE guidance it rests on. The rules only
fire on a hazard code or notation that is actually present; they never infer
a hazard. Glove materials and breakthrough times are deliberately not given:
those depend on the product and glove maker and must come from the supplier
SDS section 8 or the glove manufacturer's chemical resistance data.
"""
import re
from typing import Dict, List, Set

FLAMMABLE = {"H220", "H221", "H222", "H223", "H224", "H225", "H226", "H228", "H229", "H230", "H231", "H232"}
EXPLOSIVE = {"H200", "H201", "H202", "H203", "H204", "H205", "H206", "H207", "H208", "H209", "H210", "H211",
             "H240", "H241", "H242"}
PYROPHORIC = {"H250", "H251", "H252"}
WATER_REACTIVE = {"H260", "H261", "EUH014", "EUH029"}
OXIDISER = {"H270", "H271", "H272"}
GAS = {"H280", "H281", "H282", "H283", "H284"}
ACUTE_SEVERE = {"H300", "H310", "H330"}
ACUTE = {"H301", "H311", "H331", "H302", "H312", "H332"} | ACUTE_SEVERE
INHALATION = {"H330", "H331", "H332", "H334", "H335", "H336", "EUH071"}
CORROSIVE = {"H314", "H318"}
CARC_MUT_1 = {"H340", "H350"}
CARC_MUT_2 = {"H341", "H351"}
REPRO = {"H360", "H361", "H362"}
STOT_RE = {"H372", "H373"}
AQUATIC = {"H400", "H410", "H411", "H412", "H413"}


def base_codes(codes: List[str]) -> Set[str]:
    """H350i -> H350, H360FD -> H360; EUH codes unchanged."""
    return {c if c.startswith("EUH") else c[:4] for c in codes}


def _card(cat, level, title, points, basis):
    return {"category": cat, "level": level, "title": title, "points": points, "basis": basis}


def _texts(idx, heading) -> List[str]:
    out = []
    for sec in idx.get(heading, []):
        for info in sec.get("Information", []):
            for s in info.get("Value", {}).get("StringWithMarkup", []):
                out.append(s.get("String", ""))
    return out


PEROXIDE_RE = re.compile(r"(explosive|unstable) peroxides|formation of peroxides|peroxide formation|forms? peroxides",
                         re.I)
# Peroxide formation on storage happens with air or light. A sentence about reacting with an oxidant
# ("contact with hydrogen peroxide generates explosive peroxides") is a reactivity hazard, not this.
STORAGE_CONTEXT_RE = re.compile(r"\b(air|light|oxygen|standing|storage|stored|containers?|autoxid\w*|on exposure)\b", re.I)
OXIDANT_CONTEXT_RE = re.compile(r"contact with|mixed with|hydrogen peroxide|oxidants? such|reaction with", re.I)
REACTIVITY_HEADINGS = ("Stability/Shelf Life", "Chemical Dangers", "Hazardous Reactivities and Incompatibilities",
                       "Air and Water Reactions", "Reactivity Profile")


def peroxide_former(codes: Set[str], idx: Dict[str, list]) -> bool:
    """EUH019, or a cited section-10 statement that it forms peroxides in air or light on storage.
    PubChem's aggregated GHS data omits EU-only EUH codes, so the text check is needed."""
    if "EUH019" in codes:
        return True
    for h in REACTIVITY_HEADINGS:
        for text in _texts(idx, h):
            for sentence in re.split(r"(?<=[.;])\s+", text):
                if PEROXIDE_RE.search(sentence) and STORAGE_CONTEXT_RE.search(sentence) \
                        and not OXIDANT_CONTEXT_RE.search(sentence):
                    return True
    return False


# "Simple asphyxiant" is the term the sources use for gases whose danger is displacing oxygen. Mentions of
# "asphyxiation" alone (vapours in a confined space, foaming on ingestion) don't make a substance one.
ASPHYXIANT_RE = re.compile(r"\basphyxiants?\b|displac\w* (the )?oxygen|oxygen[- ]deficien", re.I)


def asphyxiant(idx: Dict[str, list]) -> bool:
    return any(ASPHYXIANT_RE.search(t) for h in ("Hazards Summary", "Physical Dangers", "Health Hazards",
                                                  "Inhalation Risk")
               for t in _texts(idx, h))


def build(sheet: dict, idx: Dict[str, list]) -> dict:
    g = sheet["ghs"]
    codes = base_codes(g["codes"])
    full = set(g["codes"])
    w = sheet.get("wel") or {}
    notations = set(w.get("notations") or [])
    has = lambda s: bool(codes & s)  # noqa: E731
    peroxide = peroxide_former(codes, idx)
    asphyx = asphyxiant(idx)
    cards: List[dict] = []
    flags: List[dict] = []

    # ---- Headline flags -------------------------------------------------
    if has(CARC_MUT_1) or "Carc" in notations:
        flags.append({"label": "Carcinogen / mutagen", "level": "critical"})
    elif has(CARC_MUT_2):
        flags.append({"label": "Suspected carcinogen / mutagen", "level": "warn"})
    if has(REPRO):
        flags.append({"label": "Reproductive toxin", "level": "critical" if "H360" in codes else "warn"})
    if "H334" in codes or "Sen" in notations:
        flags.append({"label": "Asthmagen (respiratory sensitiser)", "level": "critical"})
    if "H317" in codes:
        flags.append({"label": "Skin sensitiser", "level": "warn"})
    if "Sk" in notations:
        flags.append({"label": "Absorbed through skin (Sk)", "level": "warn"})
    if has(ACUTE_SEVERE):
        flags.append({"label": "Fatal if swallowed / on skin / inhaled", "level": "critical"})
    if has(CORROSIVE):
        flags.append({"label": "Corrosive / serious eye damage", "level": "warn"})
    if has(FLAMMABLE | EXPLOSIVE | PYROPHORIC | OXIDISER):
        flags.append({"label": "DSEAR dangerous substance", "level": "warn"})
    if peroxide:
        flags.append({"label": "Peroxide former", "level": "critical"})
    if has(WATER_REACTIVE):
        flags.append({"label": "Reacts with water", "level": "critical"})
    if has(PYROPHORIC):
        flags.append({"label": "Pyrophoric / self-heating", "level": "critical"})
    if has(GAS):
        flags.append({"label": "Gas under pressure", "level": "warn"})
    if asphyx:
        flags.append({"label": "Asphyxiant (reported)", "level": "warn"})
    if has(AQUATIC):
        flags.append({"label": "Harmful to aquatic life", "level": "info"})
    if not g["classified"]:
        flags.append({"label": "No GHS classification found", "level": "info"})

    # ---- Key risks --------------------------------------------------------
    if has(CARC_MUT_1) or "Carc" in notations:
        cards.append(_card("Key risks", "critical", "Carcinogen or mutagen: no safe level", [
            "Substitute with a less hazardous substance or process wherever reasonably practicable.",
            "Where it can't be substituted: use a totally enclosed system where reasonably practicable, keep quantities "
            "and the number of people exposed to a minimum, and keep exposure as low as reasonably practicable even "
            "below any WEL.",
            "Ban eating, drinking and smoking where it is used, mark the area and keep containers labelled and sealed.",
            "Keep health records and personal exposure monitoring records for 40 years.",
        ], "COSHH Regulation 7 and Schedule 2A; Regulations 10 and 11; EH40 para 5"))
    elif has(CARC_MUT_2):
        cards.append(_card("Key risks", "warn", "Suspected carcinogen or mutagen", [
            "Treat as a substance requiring a high standard of control: prefer substitution, closed handling and LEV.",
            "Tell workers about the suspected long-term effect when you train them.",
        ], "COSHH Regulations 7 and 12"))
    if has(REPRO):
        cards.append(_card("Key risks", "critical" if "H360" in codes else "warn",
                           "Reproductive toxin: new and expectant mothers", [
            "Your risk assessment must cover women of child-bearing age, and new or expectant mothers once you are told.",
            "Where the risk can't be removed, change working conditions or hours, offer suitable alternative work, "
            "or suspend on full pay.",
            *(["H362: may harm breast-fed children. Include breastfeeding workers."] if "H362" in codes else []),
        ], "Management of Health and Safety at Work Regulations 1999, Regulations 16 to 18"))
    if "H334" in codes or "Sen" in notations:
        cards.append(_card("Key risks", "critical", "Can cause occupational asthma", [
            "Prevent exposure wherever reasonably practicable; otherwise reduce it as low as reasonably practicable.",
            "Pay particular attention to short peak exposures such as decanting, cleaning and maintenance.",
            "Once a worker is sensitised, even tiny exposures can trigger symptoms; they may need to be moved away "
            "from the substance.",
        ], "EH40 paras 53 to 56; COSHH Regulation 7"))
    if "H304" in codes:
        cards.append(_card("Key risks", "warn", "Aspiration hazard", [
            "If swallowed, do NOT induce vomiting. Get medical help immediately.",
        ], "GHS H304 / P301+P310, P331"))
    if has(STOT_RE):
        organs = [t for t in _texts(idx, "Target Organs")][:3]
        cards.append(_card("Key risks", "warn", "Damage to organs on repeated exposure", [
            "Long-term, low-level exposure matters as much as accidents: monitor exposure and review controls.",
            *([f"Target organs reported: {'; '.join(organs)}"] if organs else []),
        ], "GHS H372 / H373; COSHH Regulations 10 and 11"))

    if asphyx:
        cards.append(_card("Key risks", "warn", "Asphyxiant: oxygen depletion", [
            "At high concentrations it displaces oxygen. Many asphyxiants give no warning by smell or colour.",
            "Fit fixed oxygen-depletion alarms where a leak could collect (stores, plant rooms, cold rooms), and "
            "carry a personal monitor in enclosed areas.",
            "Treat tanks, pits and poorly ventilated rooms as confined spaces: avoid entry, or use a safe system "
            "of work with rescue arrangements.",
        ], "EH40 para 57; Confined Spaces Regulations 1997; DSEAR"))

    # ---- Controls -----------------------------------------------------------
    inhal = has(INHALATION) or bool(w.get("limits"))
    if inhal:
        pts = ["Follow the hierarchy: eliminate, substitute, enclose, extract (LEV), then safe systems of work, "
               "and PPE / RPE last.",
               "If you use local exhaust ventilation, have it thoroughly examined and tested at least every 14 months, "
               "and keep the record for 5 years. Check airflow indicators daily."]
        if w.get("limits"):
            pts.append("Where there is a WEL, carry out air monitoring if you can't otherwise be sure exposure stays "
                       "below it. 8-hour TWA and 15-minute STEL both apply.")
        cards.append(_card("Controls", "info", "Inhalation controls", pts,
                           "COSHH Regulations 7, 9 and 10; HSG258 (LEV); EH40"))
    if has(FLAMMABLE | EXPLOSIVE | PYROPHORIC | OXIDISER | WATER_REACTIVE) or peroxide:
        cards.append(_card("Controls", "warn", "DSEAR: fire and explosion", [
            "Carry out a DSEAR risk assessment covering fire, explosion and runaway reactions.",
            "Where an explosive atmosphere may form (vapour, dust, gas), classify zones and use ATEX-rated equipment.",
            "Remove ignition sources: no smoking, static control (earthing / bonding when decanting), suitable "
            "electrical equipment.",
            "Keep the quantity in the workroom to the minimum needed for the task.",
        ], "Dangerous Substances and Explosive Atmospheres Regulations 2002 (DSEAR); HSG140"))
    elif "H290" in codes or has(GAS):
        cards.append(_card("Controls", "info", "DSEAR: corrosive to metals / gas under pressure", [
            "DSEAR also covers substances corrosive to metals and gases under pressure: assess the risk of "
            "container failure and release, and use compatible containers, pipework and fittings.",
        ], "Dangerous Substances and Explosive Atmospheres Regulations 2002 (as amended 2015)"))
    cards.append(_card("Controls", "info", "Assessment, training and review", [
        "Record a COSHH assessment for each task that uses this substance: who, how much, how often, how long.",
        "Give workers information, instruction and training on the hazards, the controls and what to do in an emergency.",
        "Review the assessment when the work changes, after an incident, when the supplier SDS is revised, "
        "and at a set interval (12 months is common practice).",
    ], "COSHH Regulations 6 and 12"))

    # ---- PPE ----------------------------------------------------------------
    ppe = []
    p_codes = {p["code"] for p in g["precautions"]}
    p_all = " ".join(p_codes)
    if "P280" in p_all or has(CORROSIVE) or "H317" in codes or "Sk" in notations or "H315" in codes:
        ppe.append("Gloves: chemical-protective gloves to EN ISO 374-1. Choose the material and check the "
                   "breakthrough time from the supplier SDS section 8 or the glove maker's chart for this substance; "
                   "replace before breakthrough.")
    if "P280" in p_all or has(CORROSIVE) or "H319" in codes or "H320" in codes:
        ppe.append("Eyes: eye protection to EN 166. Use goggles for liquids and splashes, plus a face shield where "
                   "there is a splash risk with corrosives.")
    if "P284" in p_all or has(ACUTE_SEVERE & {"H330"}) or "H334" in codes:
        ppe.append("Respiratory protective equipment: choose by the assigned protection factor needed (HSG53). "
                   "Tight-fitting masks need a face-fit test for each wearer (INDG479). RPE is the last line of "
                   "defence, not a substitute for LEV.")
    if "P282" in p_all or "H281" in codes:
        ppe.append("Cold-insulating gloves and a face shield or eye protection (cryogenic liquid).")
    if "P283" in p_all:
        ppe.append("Fire-resistant or flame-retardant clothing.")
    if ppe:
        ppe.append("Provide PPE free of charge, train workers to use it, store it clean and maintain it. Check it "
                   "suits the wearer and the task.")
        cards.append(_card("PPE", "info", "Personal protective equipment", ppe,
                           "COSHH Regulation 7; Personal Protective Equipment at Work Regulations 1992 (as amended 2022)"))

    # ---- Storage ------------------------------------------------------------
    store, segregate = [], []
    if has(FLAMMABLE):
        store.append("Flammable: keep in a fire-resisting cabinet or a dedicated, ventilated flammables store, away "
                     "from ignition sources. Keep lids on.")
        segregate.append("oxidisers")
    if has(OXIDISER):
        store.append("Oxidiser: store separately from flammable, combustible and organic materials.")
        segregate.append("flammables and combustibles")
    if has(WATER_REACTIVE):
        store.append("Water-reactive: store dry, away from water, sinks and aqueous chemicals. Do not use water "
                     "on a fire involving it.")
        segregate.append("water and aqueous materials")
    if has(PYROPHORIC):
        store.append("Pyrophoric or self-heating: store under an inert atmosphere or as the supplier directs, and "
                     "in small quantities.")
    if has(EXPLOSIVE):
        store.append("Explosive or self-reactive: follow the supplier's storage temperature and quantity limits. "
                     "Check whether the Explosives Regulations 2014 apply.")
    if peroxide:
        store.append("Peroxide former: date the container on receipt and on opening, test for peroxides before "
                     "distilling or concentrating it, and dispose of it within the supplier's shelf life.")
    if has(GAS):
        store.append("Gas cylinders: secure them upright, in a well-ventilated area, with valves protected. "
                     "Separate full cylinders from empty ones.")
    if has(CORROSIVE) or "H290" in codes:
        store.append("Corrosive: store at low level in a corrosion-resistant cabinet with a spill tray. Keep acids "
                     "and alkalis apart.")
        segregate.append("incompatible acids / alkalis")
    if has(ACUTE_SEVERE) or "P405" in p_all or has(CARC_MUT_1):
        store.append("Store locked up, with access restricted to trained, authorised people. Keep a stock record.")
    if not store:
        store.append("Store in the original, labelled, closed container in a cool, dry, well-ventilated place.")
    incompat = _texts(idx, "Hazardous Reactivities and Incompatibilities")[:3]
    cards.append(_card("Storage", "info", "Storage and segregation", [
        *store,
        *([f"Keep away from: {', '.join(dict.fromkeys(segregate))}."] if segregate else []),
        *([f"Reported incompatibilities: {t}" for t in incompat]),
    ], "HSG51 (flammable liquids in containers); HSG71 (chemical warehousing); DSEAR; supplier SDS section 7"))

    # ---- Health surveillance & monitoring ------------------------------------
    hs = []
    if "H334" in codes or "Sen" in notations:
        hs.append("Respiratory health surveillance (questionnaires and lung function), arranged with an "
                  "occupational health professional, for everyone exposed or liable to be exposed.")
    if "H317" in codes or "H315" in codes or "EUH066" in codes:
        hs.append("Skin surveillance for dermatitis: regular skin checks by a responsible person, with referral "
                  "to occupational health.")
    if "Sk" in notations:
        hs.append("Absorbed through the skin: the WEL alone doesn't control this route. Prevent skin contact and "
                  "consider biological monitoring.")
    if w.get("bmgv"):
        b = w["bmgv"]
        hs.append(f"EH40 biological monitoring guidance value: {b['bmgv']} (sample: {b['sampling'].lower()}).")
    if has(CARC_MUT_1) or "Carc" in notations or has(STOT_RE):
        hs.append("Keep health records for at least 40 years where health surveillance is carried out.")
    if hs:
        cards.append(_card("Health surveillance", "warn", "Health surveillance and biological monitoring", hs,
                           "COSHH Regulation 11 and Schedule 6; EH40 Table 2; HSE G402"))

    # ---- Emergency ------------------------------------------------------------
    em = ["Have spill kits suited to the substance at the point of use, and write and practise the emergency "
          "procedure."]
    if has(CORROSIVE):
        em.append("Eyewash station or sealed eyewash bottles within immediate reach. Provide an emergency shower "
                  "where large volumes or body splashes are possible.")
    if has(ACUTE_SEVERE):
        em.append("Fatal by at least one route: trained first-aiders on site whenever it is used, and the SDS "
                  "section 4 to hand for the emergency services. Check whether a specific antidote is required.")
    if has(FLAMMABLE | EXPLOSIVE | OXIDISER | PYROPHORIC):
        em.append("Include it in the fire risk assessment. Tell the fire service where it is stored "
                  "(premises information box or site plan).")
    if "EUH014" in codes or "H260" in codes or "H261" in codes:
        em.append("Do NOT use water extinguishers or water for clean-up.")
    cards.append(_card("Emergency", "info", "Accidents, incidents and emergencies", em,
                       "COSHH Regulation 13; Health and Safety (First-Aid) Regulations 1981; RIDDOR 2013 "
                       "(report dangerous occurrences and occupational diseases)"))

    # ---- Waste & environment ----------------------------------------------------
    waste = ["Dispose of the substance and contaminated packaging, wipes and PPE through a licensed waste carrier. "
             "Classify the waste and keep consignment notes or waste transfer notes."]
    if has(AQUATIC):
        waste.append("Toxic to aquatic life: never pour it down drains. Contain spills to stop them reaching "
                     "surface water drains, and bund bulk storage.")
    cards.append(_card("Waste & environment", "info", "Waste and environment", waste,
                       "Hazardous Waste (England and Wales) Regulations 2005 / Special Waste Regulations (Scotland); "
                       "Environmental Protection Act 1990 duty of care"))

    return {"flags": flags, "cards": cards, "codes": sorted(full)}
