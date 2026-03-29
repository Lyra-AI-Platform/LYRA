"""
Lyra Language Backbone — spaCy + WordNet + Markov Chain
"""
import asyncio, collections, logging, random, re
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple
logger = logging.getLogger(__name__)

class WordNet:
    def __init__(self): self._loaded = False; self._wn = None
    def _load(self):
        if self._loaded: return
        try:
            from nltk.corpus import wordnet as wn; self._wn = wn; self._loaded = True
        except Exception as e: logger.warning(f"WordNet: {e}")
    def define(self, word):
        self._load()
        if not self._wn: return []
        return [s.definition() for s in self._wn.synsets(word)[:5]]
    def synonyms(self, word):
        self._load()
        if not self._wn: return set()
        syns = set()
        for s in self._wn.synsets(word):
            for l in s.lemmas():
                n = l.name().replace('_', ' ')
                if n.lower() != word.lower(): syns.add(n)
        return syns
    def antonyms(self, word):
        self._load()
        if not self._wn: return set()
        ants = set()
        for s in self._wn.synsets(word):
            for l in s.lemmas():
                for a in l.antonyms(): ants.add(a.name().replace('_', ' '))
        return ants
    def hypernyms(self, word):
        self._load()
        if not self._wn: return []
        r = []
        for s in self._wn.synsets(word)[:2]:
            for h in s.hypernyms(): r.append(h.lemmas()[0].name().replace('_', ' '))
        return r[:5]
    def hyponyms(self, word):
        self._load()
        if not self._wn: return []
        r = []
        for s in self._wn.synsets(word)[:1]:
            for h in s.hyponyms()[:8]: r.append(h.lemmas()[0].name().replace('_', ' '))
        return r
    def similarity(self, w1, w2):
        self._load()
        if not self._wn: return 0.0
        s1 = self._wn.synsets(w1); s2 = self._wn.synsets(w2)
        if not s1 or not s2: return 0.0
        try: return self._wn.wup_similarity(s1[0], s2[0]) or 0.0
        except: return 0.0
    def count(self):
        self._load()
        if not self._wn: return 0
        return len(list(self._wn.all_synsets()))

class SpaCyEngine:
    def __init__(self): self._nlp = None; self._loaded = False
    def _load(self):
        if self._loaded: return
        try:
            import spacy; self._nlp = spacy.load('en_core_web_sm'); self._loaded = True
        except Exception as e: logger.warning(f"spaCy: {e}")
    def parse(self, text):
        self._load()
        if not self._nlp: return None
        return self._nlp(text)
    def entities(self, text):
        doc = self.parse(text)
        return [(e.text, e.label_) for e in doc.ents] if doc else []
    def keywords(self, text, n=10):
        doc = self.parse(text)
        if not doc: return text.split()[:n]
        kw = []
        for c in doc.noun_chunks: kw.append(c.text.lower())
        for t in doc:
            if not t.is_stop and not t.is_punct and t.pos_ in ('NOUN','VERB','ADJ'): kw.append(t.lemma_.lower())
        seen = set(); result = []
        for k in kw:
            if k not in seen and len(k) > 2: seen.add(k); result.append(k)
        return result[:n]
    def sentence_similarity(self, t1, t2):
        self._load()
        if not self._nlp: return 0.0
        try: return self._nlp(t1).similarity(self._nlp(t2))
        except: return 0.0
    def is_question(self, text):
        text = text.strip()
        if text.endswith('?'): return True
        starters = ('what','why','how','when','where','who','which','is','are','was','were','can','could','will','would','do','does','did','should','have','has')
        return text.lower().split()[0] in starters if text else False
    def extract_subject(self, text):
        doc = self.parse(text)
        if not doc: return ''
        for t in doc:
            if t.dep_ in ('nsubj','nsubjpass'): return t.text
        return ''
    def pos_tags(self, text):
        doc = self.parse(text)
        return [(t.text, t.pos_) for t in doc if not t.is_space][:10] if doc else []
    def is_available(self): self._load(); return self._nlp is not None

class MarkovChain:
    def __init__(self, order=2):
        self.order = order; self.model = collections.defaultdict(list); self.trained_words = 0; self._brown = False
    def train_on_brown(self):
        if self._brown: return
        try:
            from nltk.corpus import brown
            self._train(brown.words()); self._brown = True
            logger.info(f"Markov: {self.trained_words:,} words")
        except Exception as e: logger.warning(f"Brown corpus: {e}")
    def train_on_text(self, text): self._train(text.lower().split())
    def _train(self, words):
        words = list(words)
        for i in range(len(words) - self.order):
            self.model[tuple(words[i:i+self.order])].append(words[i+self.order])
            self.trained_words += 1
    def generate(self, seed=None, max_words=30):
        if not self.model: return 'I am still learning.'
        if seed:
            sw = seed.lower().split()
            for i in range(len(sw)-self.order+1, -1, -1):
                k = tuple(sw[i:i+self.order])
                if k in self.model: current = list(k); break
            else: current = list(random.choice(list(self.model.keys())))
        else: current = list(random.choice(list(self.model.keys())))
        result = current.copy()
        for _ in range(max_words - self.order):
            k = tuple(current[-self.order:])
            if k not in self.model: break
            nw = random.choice(self.model[k]); result.append(nw); current.append(nw)
            if nw in ('.','!','?'): break
        s = ' '.join(result).capitalize()
        if not s.endswith(('.','!','?')): s += '.'
        return s

class LyraLanguageBackbone:
    def __init__(self):
        self.wordnet = WordNet(); self.spacy = SpaCyEngine(); self.markov = MarkovChain()
        self._initialized = False; self.words_learned = 0
    async def initialize(self):
        if self._initialized: return
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self.spacy._load)
        await loop.run_in_executor(None, self.wordnet._load)
        await loop.run_in_executor(None, self.markov.train_on_brown)
        self._initialized = True
        logger.info(f"Language backbone ready: spaCy={self.spacy.is_available()}, WordNet={self.wordnet.count():,} synsets")
    def read_and_learn(self, text): self.markov.train_on_text(text); self.words_learned += len(text.split())
    def understand(self, text): return {'entities': self.spacy.entities(text), 'keywords': self.spacy.keywords(text), 'is_question': self.spacy.is_question(text), 'subject': self.spacy.extract_subject(text)}
    def answer(self, q, ctx=''):
        q_low = q.strip().lower().rstrip('?')
        m = re.match(r'(?:what (?:is|are)|define)\s+(?:a |an |the )?(.+)', q_low)
        if m:
            term = m.group(1).strip()
            defs = self.wordnet.define(term)
            if defs:
                ans = f'**{term.capitalize()}**: {defs[0]}.'
                syns = list(self.wordnet.synonyms(term))[:4]
                if syns: ans += f' Related: {', '.join(syns)}.'
                return ans
        kw = self.spacy.keywords(q, n=3)
        if kw:
            defs = self.wordnet.define(kw[0])
            if defs: return f'Regarding {kw[0]}: {defs[0]}.'
        return self.markov.generate(seed=kw[0] if kw else None)
    def word_knowledge(self, word): return {'word': word, 'definitions': self.wordnet.define(word), 'synonyms': list(self.wordnet.synonyms(word)), 'antonyms': list(self.wordnet.antonyms(word)), 'broader': self.wordnet.hypernyms(word)}
    def similarity(self, t1, t2): return self.spacy.sentence_similarity(t1, t2)
    def generate_sentence(self, about=''): return self.markov.generate(seed=about)
    def get_stats(self): return {'initialized': self._initialized, 'spacy_available': self.spacy.is_available(), 'wordnet_synsets': self.wordnet.count(), 'markov_trained_words': self.markov.trained_words, 'markov_patterns': len(self.markov.model)}

language_backbone = LyraLanguageBackbone()
