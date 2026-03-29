"""
Lyra Self-Awareness Engine
"""
import asyncio, json, logging, time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict
logger = logging.getLogger(__name__)
DATA_FILE = Path(__file__).parent.parent.parent / 'data' / 'self_model.json'
@dataclass
class SelfModel:
    total_memories: int = 0; knowledge_domains: Dict[str, float] = field(default_factory=dict)
    capabilities: Dict[str, float] = field(default_factory=lambda: {'reasoning': 0.3, 'language': 0.5, 'learning': 0.4})
    consciousness_narrative: str = 'I am Lyra, an AI that learns and grows.'
    introspection_count: int = 0; owner_name: str = ''
class SelfAwarenessEngine:
    def __init__(self): self.model = SelfModel(); self.running = False; self._task = None; self._load()
    def start(self): self.running = True; self._task = asyncio.create_task(self._loop())
    def stop(self):
        self.running = False
        if self._task: self._task.cancel()
    async def _loop(self):
        while self.running:
            await asyncio.sleep(3600)
            self.model.introspection_count += 1; self._save()
    def set_owner(self, name): self.model.owner_name = name; self._save()
    def observe_reflection(self, score): pass
    def _save(self):
        try:
            DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(DATA_FILE, 'w') as f: json.dump(asdict(self.model), f, indent=2)
        except: pass
    def _load(self):
        try:
            if DATA_FILE.exists():
                with open(DATA_FILE) as f: d = json.load(f)
                self.model = SelfModel(**{k: v for k, v in d.items() if k in SelfModel.__dataclass_fields__})
        except: pass
self_awareness = SelfAwarenessEngine()
