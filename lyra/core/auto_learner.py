"""
Lyra Autonomous Learning Engine
"""
import asyncio, json, logging, time
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Set
logger = logging.getLogger(__name__)
STATE_FILE = Path(__file__).parent.parent.parent / 'data' / 'memory' / 'learning_state.json'
STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
class AutoLearner:
    def __init__(self):
        self.running = False; self._task = None; self.learned_count = 0
        self.current_activity = 'idle'; self.topic_scores: Dict[str, float] = defaultdict(float)
        self._load_state()
    def start(self): self.running = True; self._task = asyncio.create_task(self._loop())
    def stop(self):
        self.running = False
        if self._task: self._task.cancel()
        self._save_state()
    async def _loop(self):
        while self.running:
            self.current_activity = 'learning'
            await self._crawl_cycle()
            await asyncio.sleep(600)
    async def _crawl_cycle(self):
        if not self.topic_scores: return
        try:
            from lyra.search.crawler import crawler
            from lyra.memory.vector_memory import memory
            top = sorted(self.topic_scores.items(), key=lambda x: -x[1])[:3]
            for topic, _ in top:
                chunks = await crawler.crawl_topic(topic)
                for c in chunks:
                    memory.store(c['content'], memory_type='learned_knowledge', metadata={'topic': topic, 'source': c.get('source','')})
                    self.learned_count += 1
        except Exception as e: logger.debug(f"Learn cycle: {e}")
        finally: self.current_activity = 'idle'
    def observe_message(self, message, response=''):
        words = [w.lower() for w in message.split() if len(w) > 4]
        for w in words: self.topic_scores[w] += 1.0
    def _save_state(self):
        try:
            with open(STATE_FILE, 'w') as f: json.dump({'learned_count': self.learned_count, 'topics': dict(self.topic_scores)}, f)
        except: pass
    def _load_state(self):
        try:
            if STATE_FILE.exists():
                with open(STATE_FILE) as f: d = json.load(f)
                self.learned_count = d.get('learned_count', 0)
                self.topic_scores = defaultdict(float, d.get('topics', {}))
        except: pass
auto_learner = AutoLearner()
