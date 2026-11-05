"""Reading a story: cleaning its text and working out what it's about. No network or web
imports, so everything that tags articles can be tested and reused without the collector."""
import hashlib
import logging
import re
import time
from typing import Dict

from lyra.newswire import config as C

logger = logging.getLogger(__name__)

LANG_CODES = {"English": "en", "German": "de", "French": "fr", "Spanish": "es", "Italian": "it", "Portuguese": "pt",
              "Japanese": "ja", "Chinese": "zh", "Korean": "ko", "Russian": "ru", "Arabic": "ar", "Turkish": "tr",
              "Dutch": "nl", "Polish": "pl", "Swedish": "sv", "Hindi": "hi", "Indonesian": "id", "Vietnamese": "vi",
              "Thai": "th", "Ukrainian": "uk", "Hebrew": "he", "Persian": "fa", "Greek": "el", "Czech": "cs",
              "Romanian": "ro", "Hungarian": "hu", "Malay": "ms", "Bengali": "bn", "Urdu": "ur", "Tamil": "ta",
              "Macedonian": "mk", "Croatian": "hr", "Serbian": "sr", "Albanian": "sq", "Bosnian": "bs", "Slovak": "sk",
              "Slovenian": "sl", "Bulgarian": "bg", "Catalan": "ca", "Danish": "da", "Norwegian": "no", "Finnish": "fi",
              "Estonian": "et", "Latvian": "lv", "Lithuanian": "lt", "Armenian": "hy", "Azerbaijani": "az",
              "Georgian": "ka", "Kazakh": "kk", "Mongolian": "mn", "Nepali": "ne", "Sinhalese": "si", "Sinhala": "si",
              "Swahili": "sw", "Afrikaans": "af", "Amharic": "am", "Burmese": "my", "Khmer": "km", "Lao": "lo",
              "Marathi": "mr", "Malayalam": "ml", "Telugu": "te", "Kannada": "kn", "Gujarati": "gu", "Punjabi": "pa",
              "Icelandic": "is", "Maltese": "mt", "Irish": "ga", "Welsh": "cy", "Basque": "eu", "Galician": "gl",
              "Belarusian": "be", "Uzbek": "uz", "Somali": "so", "Tagalog": "tl", "Filipino": "tl"}

_COMPANY_RE = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(k) for k in C.COMPANIES), key=len, reverse=True)) + r")(?![A-Za-z])")
AMBIGUOUS = {"Meta", "Shell", "Apple", "Olin", "Amazon", "Arm Holdings", "Sika", "Bayer", "Linde", "Total"}
_CASHTAG_RE = re.compile(r"(?:\$|\b(?:NYSE|NASDAQ|Nasdaq|LSE|TSX|ASX)\s*:\s*)([A-Z]{1,5}(?:[.-][A-Z])?)\b")


def language_code(name: str) -> str:
    """ISO code for a language name GDELT gives. Unknown stays blank: "Bosnian"[:2] isn't a code."""
    return LANG_CODES.get((name or "").strip().title(), "")


def tidy_title(title: str) -> str:
    """GDELT tokenises some headlines: "Oil rises , traders say ." loses the stray spaces."""
    title = " ".join((title or "").split())
    title = re.sub(r"\s+([,.;:!?%)\]])", r"\1", title)
    return re.sub(r"([(\[])\s+", r"\1", title)


_WRAPPER_RE = re.compile(r"https?://\S+|\bnews\.google\.\S+|\bGoogle News\b", re.I)


def matchable(text: str) -> str:
    """Text to look for company names in. Links and Google News' own name aren't mentions:
    every story from a Google News feed would otherwise count as being about Alphabet."""
    return _WRAPPER_RE.sub(" ", text or "")


def item_id(url: str) -> str:
    return hashlib.sha1(url.split("#")[0].encode()).hexdigest()[:20]


class Tagger:
    """Topics, companies (tickers) and named people for one item."""

    def __init__(self):
        self.people: Dict[str, str] = {}
        self.loaded = 0.0

    def refresh_people(self):
        """Public figures known to Lyra Watch, matched by full name (two words or more)."""
        if time.time() - self.loaded < 3600:
            return
        try:
            from lyra.watch.service import is_public_figure, load_people
            from lyra.watch.config import load_roster
            names = {p["name"]: p.get("slug") or p["name"] for p in load_roster()}
            for r in load_people().get("people", []):
                if is_public_figure(r) and len(r.get("name", "").split()) >= 2:
                    names.setdefault(r["name"], r.get("id") or r["name"])
            self.people = names
            self._people_re = re.compile(r"(?<![A-Za-z])(" + "|".join(sorted((re.escape(n) for n in names), key=len, reverse=True)) + r")(?![A-Za-z])") if names else None
        except Exception as e:  # noqa: BLE001
            logger.debug(f"Newswire: people list unavailable: {e}")
            self._people_re = None
        self.loaded = time.time()

    def tag(self, it: Dict) -> Dict:
        text = matchable(f"{it.get('title', '')} {it.get('summary', '')}")
        low = f" {text.lower()} "
        topics = set(it.get("topics", []))
        for topic, words in C.TOPIC_WORDS.items():
            if any(w in low for w in words):
                topics.add(topic)
        english = (it.get("language") or "en").startswith("en")
        # Names that are ordinary words elsewhere ("meta" is "goal" in Spanish and Italian).
        tickers = {C.COMPANIES[m] for m in _COMPANY_RE.findall(text) if english or m not in AMBIGUOUS}
        tickers |= {t for t in _CASHTAG_RE.findall(text) if len(t) > 1}
        tickers -= C.BLOCKED_TICKERS
        people = set()
        if getattr(self, "_people_re", None):
            people = set(self._people_re.findall(text))
        return {**it, "topics": sorted(topics), "tickers": sorted(tickers), "people": sorted(people)}


tagger = Tagger()
