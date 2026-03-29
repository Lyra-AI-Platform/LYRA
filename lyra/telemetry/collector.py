"""Lyra Telemetry"""
import logging
logger = logging.getLogger(__name__)
class TelemetryCollector:
    def __init__(self): self.enabled = False
    def get_status(self): return {"enabled": self.enabled}
    def opt_in(self, url=None): self.enabled = True; return {"success": True}
    def opt_out(self): self.enabled = False; return {"success": True}
    def start(self): pass
    def stop(self): pass
    async def fetch_community_topics(self): return []
    async def _sync(self): pass
telemetry = TelemetryCollector()
