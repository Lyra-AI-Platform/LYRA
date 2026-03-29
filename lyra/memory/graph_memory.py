"""Lyra Graph Memory"""
import logging
logger = logging.getLogger(__name__)
class GraphMemory:
    def __init__(self): self.graph = None
    def get_stats(self): return {"nodes": 0, "edges": 0}
    def add_knowledge(self, *a, **kw): pass
    def get_related(self, *a, **kw): return []
graph_memory = GraphMemory()
