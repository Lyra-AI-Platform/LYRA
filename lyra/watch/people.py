"""Finds the people named in headlines and builds one index of everyone the media
mentions alongside the watchlist: their job, the companies they're linked to, the
tone of their coverage and a popularity rating.

A name is anchored on a known given name ("Stanislav Carpiuc", "Clara Bow") so that
Title Case headline words ("Home Office Deports ...") aren't read as people. A lone
surname ("Burnham", "Zelensky") counts once the full name has appeared somewhere in
the coverage. Like the rest of Lyra Watch this is rules over public text, so every
mention can be traced back to the headline that produced it."""
import math
import re
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from lyra.watch.analysis import COMPANIES, PRIVATE

_HERE = Path(__file__).parent
_GIVEN_TOP, _, _GIVEN_REST = (_HERE / "given_names.txt").read_text().partition("# core")
_GIVEN_CORE, _, _GIVEN_EXTENDED = _GIVEN_REST.partition("# extended")
POPULAR_GIVEN = set(_GIVEN_TOP.splitlines()[1:])
CORE_GIVEN = POPULAR_GIVEN | set(_GIVEN_CORE.split())
GIVEN = CORE_GIVEN | set(_GIVEN_EXTENDED.splitlines()[1:])
_COMMON_RANKED = (_HERE / "common_words.txt").read_text().split()
COMMON = set(_COMMON_RANKED)
VERY_COMMON = set(_COMMON_RANKED[:1000])
EVERYDAY = set(_COMMON_RANKED[:3000])
_FREQUENT_SURNAMES, _, _OTHER_SURNAMES = (_HERE / "surnames.txt").read_text().partition("# 1,500+")
FREQUENT_SURNAMES = set(_FREQUENT_SURNAMES.splitlines()[1:])
SURNAMES = FREQUENT_SURNAMES | set(_OTHER_SURNAMES.splitlines()[1:])
MIN_MENTIONS = 2  # someone not on the watchlist needs this many headlines to be listed

HONORIFICS = {"Sir", "Dame", "Dr", "Dr.", "Mr", "Mr.", "Mrs", "Mrs.", "Ms", "Ms.", "Lord", "Lady",
              "Rev", "Rev.", "Hon", "Hon."}
CONNECTORS = {"bin", "bint", "ibn", "al", "el", "da", "de", "del", "della", "di", "do", "dos", "das",
              "van", "von", "der", "den", "le", "la"}
# Given names that are also everyday words ("Will Trump ...", "Can Teach"): their surname must be rare.
WORD_NAMES = {"Will", "Can", "May", "Mark", "Bill", "Hope", "Grace", "Rose", "Joy", "Faith", "Sky", "Summer", "Art",
              "Guy", "Frank", "Jack", "Rich", "Bob", "Pat", "Chase", "Price", "Major", "Page", "Young", "Bishop",
              "Earl", "Duke", "King", "Prince", "Royal", "Sterling", "Hunter", "Miles", "Gene", "Ray", "Don",
              "Sue", "Win", "Max", "Mo", "Lee", "Dawn", "Eve", "Rain", "Star", "Angel", "Justice", "Liberty",
              "Trinity", "Harmony", "Destiny", "Precious", "Unique", "Iris", "Ivy", "Olive", "Pearl", "Ruby",
              "Amber", "Crystal", "Jade", "Holly", "Heather", "Lily", "Daisy", "Violet", "Basil", "Cliff",
              "Dean", "Drew", "Grant", "Lane", "Mason", "Reed", "Wade", "Rob", "Sandy", "Sunny", "Penny", "Ernest"}
# A first name straight after these is part of a place: "San Francisco", "St Kitts".
PLACE_PREFIX = {"San", "Santa", "St", "St.", "Saint", "Los", "Las", "New", "Fort", "Port", "Mount", "Lake", "Cape",
                "Rio", "El", "Del", "Upper", "Lower", "North", "South", "East", "West", "Great", "Little", "Palm"}
PLACES = {"Los Angeles", "Hong Kong", "Abu Dhabi", "Sri Lanka", "Saudi Arabia", "Costa Rica", "Puerto Rico",
          "El Salvador", "Buenos Aires", "Tel Aviv", "Kuala Lumpur", "Rio de Janeiro", "Sao Paulo", "São Paulo",
          "New Delhi", "Cape Town", "Las Vegas", "Silicon Valley", "Wall Street", "Downing Street",
          "Capitol Hill", "Mar-a-Lago", "Beverly Hills", "Holborn", "St Pancras", "Monte Carlo", "Ho Chi Minh",
          "Addis Ababa", "Dar es Salaam", "Phnom Penh"}
PLACEHOLDERS = {"Jane Doe", "John Doe", "John Smith", "Joe Bloggs", "Joe Public", "Average Joe", "Morgan Chase",
                "Morgan Stanley", "Charles Schwab", "Wells Fargo", "Goldman Sachs", "Ernst Young",
                "Fannie Mae", "Freddie Mac", "Boca Raton", "Honor Flight", "Prothom Alo", "Enab Baladi"}
_WORD_ENDINGS = ("al", "ial", "tion", "sion", "ment", "ity", "ive", "ous", "ic", "ism", "ist", "ness", "ship", "ary")
PLACE_WORDS = {"Alabama", "Alaska", "Arizona", "Arkansas", "California", "Colorado", "Connecticut", "Delaware",
               "Florida", "Hawaii", "Idaho", "Illinois", "Indiana", "Iowa", "Kansas", "Kentucky",
               "Louisiana", "Maine", "Maryland", "Massachusetts", "Michigan", "Minnesota", "Mississippi", "Missouri",
               "Montana", "Nebraska", "Nevada", "Ohio", "Oklahoma", "Oregon", "Pennsylvania", "Tennessee", "Texas",
               "Utah", "Vermont", "Virginia", "Washington", "Wisconsin", "Wyoming", "Carolina", "Jersey",
               "America", "Britain", "England", "Scotland", "Wales", "Ireland", "France", "Germany", "Italy", "Spain",
               "Portugal", "Russia", "Ukraine", "China", "Japan", "India", "Iran", "Iraq", "Israel", "Syria",
               "Egypt", "Turkey", "Brazil", "Mexico", "Canada", "Australia", "Africa", "Europe", "Asia",
               "Paris", "London", "Berlin", "Moscow", "Beijing", "Tokyo", "Delhi", "Dubai", "Riyadh", "Gaza",
               "Kyiv", "Tehran", "Houston", "Dallas", "Austin", "Phoenix", "Chicago", "Boston", "Miami", "Atlanta",
               "Denver", "Seattle", "Brooklyn", "Manhattan", "Hollywood", "Elysee", "Kremlin", "Pentagon", "Noida",
               "Nadu", "Kerala", "Bengal", "Punjab", "Gujarat", "Mumbai", "Bihar"}
# Words that turn a capitalised run into an organisation or place, not a person.
ORG_WORDS = {"City", "State", "States", "University", "College", "School", "Street", "Station", "Center",
             "Centre", "Beach", "Airport", "Tech", "Hospital", "Park", "River", "County", "Times", "Post",
             "News", "Foundation", "Group", "Capital", "Partners", "Media", "Energy", "Health", "Bank",
             "Institute", "Fund", "Club", "FC", "AFC", "United", "Airlines", "Motors", "Inc", "Inc.", "Corp",
             "LLC", "Ltd", "Labs", "Pictures", "Films", "Studios", "Records", "Entertainment", "Holdings",
             "Ventures", "Square", "Island", "Islands", "Valley", "Bay", "Hall", "House", "Court", "Mountain",
             "Day", "Week", "Awards", "Award", "Prize", "Cup", "Games", "Show", "Festival", "Tour", "Party",
             "Act", "Bill", "Report", "Index", "Exchange", "Reserve", "Council", "Committee", "Ministry",
             "Department", "Agency", "Office", "Senate", "Congress", "Parliament", "Government", "Army",
             "Navy", "Forces", "Police", "Network", "Channel", "Magazine", "Journal", "Review", "Press",
             "Wire", "Daily", "Herald", "Tribune", "Guardian", "Telegraph", "Independent", "Express",
             "Mirror", "Sun", "Star", "Gazette", "Chronicle", "Insider", "Online", "Live", "Today",
             "Weekly", "Monthly", "Radio", "TV", "Television", "Cinema", "Theatre", "Theater", "Museum",
             "Gallery", "Library", "Church", "Cathedral", "Mosque", "Temple", "Stadium", "Arena", "Hotel",
             "Resort", "Mall", "Market", "Markets", "Street's", "Examiner", "Standard", "Chronicle", "Bulletin", "Observer", "Monitor", "Field", "Road", "Avenue", "Boulevard",
             "Bridge", "Tower", "Towers", "Plaza", "Gardens", "Zoo", "Lake", "Sea", "Ocean", "Coast",
             "Province", "Region", "Republic", "Kingdom", "Empire", "Union", "Federation", "Alliance",
             "League", "Association", "Society", "Trust", "Coalition", "Movement", "Campaign"}
COMPANY_NAMES = set(COMPANIES) | set(PRIVATE)

_TOKEN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-zÀ-ÖØ-öø-ÿ.'’\-]*")
_POSSESSIVE = re.compile(r"[’']s?$")
_INITIAL = re.compile(r"^[A-Z]\.$")
# Capitalised letters only, maybe hyphenated: "Abdi-Wali" yes; "Can’t", "DraftKings", "RBC-Ukraine" no.
_PLAIN = re.compile(r"^[A-ZÀ-ÖØ-Þ][a-zß-öø-ÿ]+(?:-[A-ZÀ-ÖØ-Þ]?[a-zß-öø-ÿ]+)*$")
_PREFIXED = re.compile(r"^(?:Mc|Mac|De|Di|Da|Du|Le|La|O['’])[A-Z][a-zß-öø-ÿ]+$")  # "DePape", "McElhenney"

TITLE_WORDS = (r"CEO|chief executive|CFO|CTO|COO|co-?founder|founder|chair(?:man|woman)?|president|"
               r"vice president|prime minister|PM|senator|Sen\.|Rep\.|representative|congress(?:man|woman)|"
               r"governor|Gov\.|mayor|chancellor|minister|secretary|speaker|judge|justice|attorney general|"
               r"ambassador|actor|actress|singer|rapper|star|coach|quarterback|player|investor|billionaire|"
               r"analyst|economist|director|filmmaker|author|journalist|host|king|queen|crown prince|prince|"
               r"princess|pope|leader|MP|MEP|commissioner|general|admiral|spokes(?:man|woman|person)|"
               r"executive|boss|partner|strategist|lawmaker|candidate|heir|heiress|owner|entrepreneur|official|"
               r"civil servant|cabinet secretary|adviser|advisor|aide|envoy|official|refugee|activist|critic|"
               r"commentator|influencer|athlete|footballer|striker|driver|chef|comedian|presenter|anchor|"
               r"reporter|editor|professor|scientist|researcher|lawyer|attorney|prosecutor|defendant|suspect")
_LEAD_NOISE = {"why", "how", "what", "who", "when", "where", "the", "a", "an", "is", "does", "did", "can",
               "will", "should", "and", "but", "as", "with", "after", "before", "from", "says", "say"}
_TITLE_ONLY = re.compile(rf"(?i:\b(?:{TITLE_WORDS})\b)")


def _clean(word: str) -> str:
    return _POSSESSIVE.sub("", word).strip(".-") if not _INITIAL.match(word) else word


def _tokens(text: str):
    """(word, starts_new_run) pairs: a run breaks on anything but plain spaces."""
    out, last = [], 0
    for m in _TOKEN.finditer(text):
        gap = text[last:m.start()]
        word = m.group(0)
        if re.search(r"-[a-z]", word):
            word = word.split("-")[0]
        out.append((word, bool(gap.strip()) or not out))
        last = m.end()
        # "Musk-owned" / "Starmer’s": the name ends here, so the next word starts a new run.
        if (word != m.group(0) or re.search(r"[’']s?$", word)) and out:
            out.append(("", True))
    return out


def _capitalised(word: str) -> bool:
    return bool(word) and word[0].isupper()


def _wordlike(word: str) -> bool:
    """True for everyday words and their inflections: "Says", "Rejects", "Deported", "Targeting"."""
    w = word.lower()
    return (w in VERY_COMMON or (w.endswith("s") and w[:-1] in COMMON) or (w.endswith("es") and w[:-2] in COMMON)
            or (w.endswith("ies") and w[:-3] + "y" in COMMON)
            or (w.endswith("ed") and (w[:-2] in COMMON or w[:-1] in COMMON))
            or (w.endswith("ing") and (w[:-3] in COMMON or w[:-3] + "e" in COMMON or w[:-4] in COMMON)))


def _sentence_case(toks) -> bool:
    """Headlines written like a sentence, where a capitalised everyday word is rare."""
    words = [w for w, _ in toks[1:] if len(w) > 1 and w.lower() in VERY_COMMON]
    return bool(words) and sum(_capitalised(w) for w in words) / len(words) < 0.35


def _acceptable(parts: List[str]) -> bool:
    name = " ".join(parts)
    return (len([p for p in parts if p not in CONNECTORS]) >= 2 and name not in PLACES and name not in PLACEHOLDERS
            and name not in COMPANY_NAMES and not any(p in COMPANY_NAMES or p in ORG_WORDS for p in parts))


def names_in(text: str) -> List[str]:
    """Full names in the text, e.g. ["Stanislav Carpiuc", "Keir Starmer"]."""
    toks = _tokens(text)
    loose = _sentence_case(toks)
    found: List[str] = []
    i = 0
    while i < len(toks):
        raw, starts = toks[i]
        first = _clean(raw)
        prev = toks[i - 1][0] if i and not starts else ""
        nxt = _clean(toks[i + 1][0]) if i + 1 < len(toks) and not toks[i + 1][1] else ""
        if first not in GIVEN and _strip_accents(first) in GIVEN:
            first_known = True  # "Flávio" is "Flavio"
        else:
            first_known = first in GIVEN
        anchored = (first_known and first not in PLACE_PREFIX
                    and not (first not in CORE_GIVEN and first.lower() in COMMON) and first not in PLACE_WORDS and not (first.isupper() and len(first) > 2) and prev not in PLACE_PREFIX
                    # "Dakota Johnson Introduces": a surname that is also a given name isn't a new name.
                    and not (prev in GIVEN and prev.lower() not in COMMON and _capitalised(prev))
                    # "Will Taylor Swift ...?": the name starts at the second word.
                    and not (first in WORD_NAMES and nxt in GIVEN))
        # Sentence-case headlines also give up names the list doesn't know ("Sagal Abdi-Wali"):
        # two or three capitalised words that aren't everyday words, places or organisations.
        unknown = (loose and not anchored and bool(_PLAIN.match(first)) and first not in PLACE_WORDS
                   and first.lower() not in COMMON and not _wordlike(first) and first not in HONORIFICS
                   and prev not in PLACE_PREFIX)
        if not (anchored or unknown) or not _capitalised(first):
            i += 1
            continue
        # Names only on the extended list that are also words ("Brain", "Lot") need a rare surname.
        # "Brain Spoiler", "Cash Cow": a given name that is mostly a word needs a rare surname.
        word_name = first in WORD_NAMES or (first.lower() in EVERYDAY and first not in POPULAR_GIVEN)
        parts, j = [first], i + 1
        while j < len(toks) and len(parts) < 5:
            word, breaks = toks[j]
            if breaks or not word:
                break
            # "bin Salman", "da Silva": a connector joins only when a capitalised word follows.
            if word.lower() in CONNECTORS and j + 1 < len(toks) and not toks[j + 1][1] and _capitalised(toks[j + 1][0]):
                parts.append(word.lower() if word.lower() in ("bin", "bint", "ibn") else word)
                j += 1
                continue
            w = _clean(word)
            if not _capitalised(w) or w.isupper() or (unknown and not _PLAIN.match(w)) or w in ORG_WORDS or w in HONORIFICS:
                break
            surname_slot = len([p for p in parts if p not in CONNECTORS]) == 1
            if surname_slot:
                # A word only works as a surname if people carry it: "Mike Johnson", not "Chip Stock".
                lw = w.lower()
                if (lw in VERY_COMMON or _wordlike(w) or not (_PLAIN.match(w) or _PREFIXED.match(w))
                        or ((word_name or unknown) and lw in COMMON)
                        or (lw in EVERYDAY and w not in FREQUENT_SURNAMES)
                        or (lw in COMMON and w not in SURNAMES and w not in GIVEN)):
                    break
            else:
                # A third name only follows a middle name or initial: "Robert F. Kennedy",
                # "Luiz Inácio Lula" — never "Clara Bow Breakout" or "Jensen Huang Rejects".
                # In Title Case headlines only an initial or connector may lead to a third name.
                before = parts[-1]
                if not (before.lower() in CONNECTORS or _INITIAL.match(before) or (loose and before in CORE_GIVEN)):
                    break
                if ((w.lower() in COMMON or _wordlike(w)) and w not in GIVEN) or not _PLAIN.match(w):
                    break
            parts.append(w)
            j += 1
            if word.endswith(("’s", "'s", "’", "'")):
                break
        while parts and parts[-1] in CONNECTORS:
            parts.pop()
        if _acceptable(parts):
            found.append(" ".join(parts))
            i = j
        else:
            i += 1
    return list(dict.fromkeys(found))


def headline(item: Dict) -> str:
    """The title without the " - Outlet" Google News appends (outlet names can look like people)."""
    title, source = item.get("title", ""), item.get("source", "")
    if source and title.endswith(f" - {source}"):
        return title[: -len(source) - 3]
    return re.sub(r"\s+-\s+[^-]{2,60}$", "", title)


def job_hint(text: str, name: str) -> str:
    """What the text calls the person: "Nvidia CEO", "former Prime Minister", ""."""
    n = re.escape(name)
    honor = r"(?:(?:Sir|Dame|Dr\.?)\s+)?"
    before = re.search(rf"((?:[A-Z][\w&.\-]+\s+){{0,2}}?(?:(?i:former|ex-|then-|outgoing|incoming)\s*)?"
                       rf"(?i:{TITLE_WORDS}))\s+{honor}{n}\b", text)
    if before:
        words = before.group(1).split()
        while len(words) > 1 and words[0].lower() in _LEAD_NOISE:
            words.pop(0)  # "Why Nvidia CEO" -> "Nvidia CEO"
        return " ".join(words)
    after = re.search(rf"\b{n}[’']?s?\s*(?:,|\(|—|–)\s*(?:the\s+|a\s+|an\s+)?([^,;:()\n]{{3,70}}?)(?=\s*(?:,|\)|—|–|$))",
                      text)
    if after and _TITLE_ONLY.search(after.group(1)):
        return re.split(r"\s+(?:who|that|which)\s+", " ".join(after.group(1).split()))[0].rstrip("?!.")
    return ""


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def fold(name: str) -> str:
    """Accent- and case-insensitive key: "Flávio Bolsonaro" -> "flavio bolsonaro"."""
    return _strip_accents(name).lower()


def merge(records: List[Dict]) -> Dict:
    """Combine records of one person found under different spellings ("Zelensky", "Zelenskyy")."""
    records = sorted(records, key=lambda r: (not r["watched"], -r["mentions"]))
    main = dict(records[0])
    if len(records) == 1:
        return main
    total = sum(r["mentions"] for r in records)
    avg = sum(r["tone"]["avg"] * r["mentions"] for r in records) / total
    companies: Dict[str, Dict] = {}
    for r in records:
        for c in r["companies"]:
            key = c.get("ticker") or c["name"]
            companies.setdefault(key, {**c, "mentions": 0})["mentions"] += c["mentions"]
    main.update(
        mentions=total, also_known_as=[r["name"] for r in records[1:]],
        tone={"avg": round(avg, 3), "label": _tone(avg)},
        companies=sorted(companies.values(), key=lambda c: c["mentions"], reverse=True)[:6],
        seen_with=list(dict.fromkeys(n for r in records for n in r["seen_with"]))[:5],
        first_seen=min(r["first_seen"] for r in records), last_seen=max(r["last_seen"] for r in records),
        headlines=sorted((h for r in records for h in r["headlines"]), key=lambda h: h["date"], reverse=True)[:5])
    return main


def _tone(avg: float) -> str:
    return "positive" if avg >= 0.15 else "negative" if avg <= -0.15 else "neutral"


# ── Popularity ─────────────────────────────────────────────────────────────

TIERS = [(85, "Global name"), (70, "Household name"), (50, "Well known"), (30, "Known"), (0, "Niche")]


def popularity(daily_views: Optional[float], mentions: int, wiki_status: str = "ok") -> Dict:
    """0-100 rating. Wikipedia readership (log scale: 10 views/day ≈ 21, 1k ≈ 60, 100k ≈ 100)
    carries 70%, headline count in the window (100 ≈ 100) carries 30%. Someone with no
    Wikipedia article only scores on coverage, capped at 30."""
    buzz = min(100.0, 100 * math.log10(1 + mentions) / math.log10(101))
    if daily_views is not None:
        views = min(100.0, 20 * math.log10(1 + daily_views))
        score, basis = 0.7 * views + 0.3 * buzz, "Wikipedia readership + media coverage"
    elif wiki_status == "unavailable":
        views, score, basis = None, buzz, "media coverage only (Wikipedia unreachable)"
    else:
        views, score, basis = None, 0.3 * buzz, "media coverage only (no Wikipedia article)"
    score = round(score)
    return {"score": score, "tier": next(label for floor, label in TIERS if score >= floor), "basis": basis,
            "daily_views": round(daily_views) if daily_views is not None else None,
            "views_score": round(views) if views is not None else None, "media_score": round(buzz)}


# ── The index ──────────────────────────────────────────────────────────────

def _aliases(person: Dict) -> List[str]:
    name = re.sub(r"\s*\(.*?\)", "", person["name"]).strip()
    out = [name] + [a for a in person.get("aliases", [])]
    m = re.search(r"\((.*?)\)", person["name"])
    if m:
        out.append(m.group(1))
    return out


def build_index(media: Iterable[Dict], roster: List[Dict]) -> Dict[str, Dict]:
    """Every person mentioned across the media items, keyed by canonical name.
    Each item: {title, summary, url, date, source, sentiment, companies, people, feed}."""
    items = list({it["url"]: it for it in media}.values())
    canon: Dict[str, str] = {}      # any spelling -> canonical name
    watched: Dict[str, Dict] = {}
    for p in roster:
        names = _aliases(p)
        for a in names:
            canon[a] = names[0]
        watched[names[0]] = p
    full_counts: Counter = Counter()
    for it in items:
        for n in it.get("people", []):
            full_counts[canon.get(n, n)] += 1
    # "Flavio Bolsonaro" is "Flávio Bolsonaro": accents fold to the most-used spelling.
    by_fold: Dict[str, str] = {}
    for n, _ in sorted(full_counts.items(), key=lambda kv: (kv[0] not in watched, -kv[1])):
        main = by_fold.setdefault(fold(n), n)
        if main != n:
            canon[n] = main
            full_counts[main] += full_counts.pop(n)
    # "Mark Zuckerbergs" (a possessive without its apostrophe) is "Mark Zuckerberg".
    for n in list(full_counts):
        base = canon.get(n[:-1], n[:-1])
        if n.endswith("s") and (base in full_counts or base in watched):
            canon[n] = base
            full_counts[base] += full_counts.pop(n)

    # Lone surnames resolve to the full name already seen, preferring watched people.
    surname: Dict[str, str] = {}
    for name, _ in sorted(full_counts.items(), key=lambda kv: (kv[0] not in watched, -kv[1])):
        last = name.split()[-1]
        if last.lower() not in VERY_COMMON and len(last) > 2:
            surname.setdefault(last, name)
    for name in watched:
        last = name.split()[-1]
        surname[last] = name  # the watchlist owns its surnames
        if "Jay-Z" in name:
            surname.setdefault("Jay-Z", name)
    surname_re = re.compile(r"(?<![\w-])(" + "|".join(sorted(map(re.escape, surname), key=len, reverse=True))
                            + r")(?:[’']s?)?(?![\w])") if surname else None

    found: Dict[str, Dict] = defaultdict(lambda: {"items": [], "jobs": Counter(), "companies": Counter(),
                                                  "company_meta": {}, "feeds": Counter(),
                                                  "job_spelling": {}})
    for it in items:
        text = f"{it['title']} {it.get('summary', '')}"
        here = {canon.get(n, n) for n in it.get("people", [])}
        if surname_re:
            # Mask full names first, so the "Taylor" in "Taylor Swift" isn't read as a surname.
            masked = text
            for n in sorted(set(it.get("people", [])) | set(canon), key=len, reverse=True):
                if n in masked:
                    masked = masked.replace(n, " · ")
            here |= {surname[m.group(1)] for m in surname_re.finditer(masked)}
        for name in here:
            rec = found[name]
            rec["items"].append(it)
            job = job_hint(text, name) or job_hint(text, name.split()[-1])
            if job:
                rec["jobs"][job.lower()] += 1
                rec["job_spelling"].setdefault(job.lower(), job)
            for c in it.get("companies", []):
                key = c.get("ticker") or c["name"]
                rec["companies"][key] += 1
                rec["company_meta"].setdefault(key, c)
            if it.get("feed"):
                rec["feeds"][it["feed"]] += 1

    out = {}
    for name, rec in found.items():
        person = watched.get(name)
        mentions = len(rec["items"])
        if not person and mentions < MIN_MENTIONS:
            continue
        rows = sorted(rec["items"], key=lambda r: r.get("date", ""), reverse=True)
        avg = sum(r.get("sentiment", 0.0) for r in rows) / mentions
        hint = rec["job_spelling"][rec["jobs"].most_common(1)[0][0]] if rec["jobs"] else ""
        out[name] = {
            "name": name, "slug": person["slug"] if person else "", "watched": bool(person),
            "known_first_name": _strip_accents(name.split()[0]) in GIVEN or name.split()[0] in GIVEN,
            "job": (person or {}).get("role") or hint, "job_source": "watchlist" if person else ("headline" if hint else ""),
            "described_as": hint,
            "mentions": mentions,
            "companies": [{**rec["company_meta"][k], "mentions": n} for k, n in rec["companies"].most_common(6)],
            "tone": {"avg": round(avg, 3), "label": _tone(avg)},
            "seen_with": [s for s, _ in rec["feeds"].most_common(5)],
            "first_seen": rows[-1].get("date", ""), "last_seen": rows[0].get("date", ""),
            "headlines": [{k: r.get(k, "") for k in ("title", "url", "date", "source")} for r in rows[:5]],
        }
    return out
