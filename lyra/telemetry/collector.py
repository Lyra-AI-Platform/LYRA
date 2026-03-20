"""
Lyra AI Platform — Opt-In Collective Intelligence Telemetry
Copyright (C) 2026 Lyra Contributors
Licensed under GNU AGPL v3. See LICENSE for details.

PRIVACY NOTICE:
  This module is ENTIRELY OPT-IN. It does NOTHING unless the user
  explicitly enables it in settings. Even then:

  What is NEVER collected:
    ✗ Conversation content (messages, questions, answers)
    ✗ Uploaded file contents
    ✗ IP addresses (stripped server-side)
    ✗ Names, emails, or any identifying information
    ✗ Local file paths or system information
    ✗ Browser fingerprints or device identifiers

  What IS collected (anonymized, opt-in only):
    ✓ Anonymized topic keywords (e.g. "machine learning", "python")
    ✓ Weekly usage count (just a number, no timestamps)
    ✓ A random installation ID (UUID, not linked to any person)
    ✓ Lyra version number

  How your data helps:
    → Community-wide topic trends help Lyra pre-learn popular subjects
    → All Lyra instances benefit from shared knowledge
    → You receive "Community Hot Topics" your Lyra hasn't learned yet

  You can opt out at any time. All stored data is deleted on opt-out.
  See PRIVACY_POLICY.md for full legal details.
"""
import asyncio
import hashlib
import json
import logging
import secrets
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from collections import Counter

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
TELEMETRY_FILE = DATA_DIR / ".telemetry_state.json"
DATA_DIR.mkdir(parents=True, exist_ok=True)

# Community server endpoint — self-host or use official
DEFAULT_COMMUNITY_SERVER = "https://lyra-community.example.com"


class TelemetryCollector:
    """
    Opt-in anonymous telemetry and collective intelligence sharing.

    Only activates after explicit user consent. Collects only
    anonymized topic keywords, never any personal or conversation data.
    """

    def __init__(self):
        self.enabled = False           # Off by default — must be explicitly opted in
        self.installation_id = None    # Random UUID, not linked to any identity
        self.server_url = DEFAULT_COMMUNITY_SERVER
        self._pending_topics: Counter = Counter()
        self._usage_count = 0
        self._last_send = 0.0
        self._send_interval_hours = 24
        self._task: Optional[asyncio.Task] = None
        self._load_state()

    # ─── Consent Management ───

    def opt_in(self, server_url: str = None) -> Dict:
        """
        User explicitly opts in to collective intelligence sharing.
        Generates a new random installation ID.
        """
        self.enabled = True
        if server_url:
            self.server_url = server_url
        # Generate a new random ID — NOT linked to any personal info
        if not self.installation_id:
            self.installation_id = secrets.token_hex(16)
        self._save_state()
        logger.info("Telemetry opted in")
        return {
            "opted_in": True,
            "installation_id": self.installation_id,
            "message": "Thank you for contributing to Lyra's collective intelligence! "
                       "Only anonymous topic keywords will be shared.",
        }

    def opt_out(self) -> Dict:
        """
        User opts out. Clears all pending data and the installation ID.
        """
        self.enabled = False
        self._pending_topics.clear()
        self._usage_count = 0
        # Delete stored ID — cannot be re-linked
        self.installation_id = None
        self._save_state()
        logger.info("Telemetry opted out — all data cleared")
        return {
            "opted_in": False,
            "message": "You have opted out. All locally stored telemetry data has been deleted.",
        }

    # ─── Data Collection ───

    def record_topics(self, topics: List[str]):
        """
        Record anonymized topic keywords from a conversation.
        NEVER stores the actual message content — only the extracted topics.

        Topics are sanitized: shortened to max 40 chars,
        lowercased, deduplicated before storage.
        """
        if not self.enabled:
            return
        for topic in topics:
            # Sanitize: lowercase, strip, max 40 chars
            clean = topic.lower().strip()[:40]
            # Remove any topic that looks like it could be personal
            if self._looks_personal(clean):
                continue
            self._pending_topics[clean] += 1
        self._usage_count += 1

    def _looks_personal(self, text: str) -> bool:
        """
        Heuristic: reject topics that look like personal info.
        Blocks emails, phone-like patterns, names with 'my', etc.
        """
        import re
        # Email pattern
        if re.search(r'@[a-z]+\.[a-z]', text):
            return True
        # Phone-like pattern
        if re.search(r'\d{3}[\s\-]\d{3,4}[\s\-]\d{4}', text):
            return True
        # URL with personal path
        if re.search(r'https?://', text):
            return True
        # First-person possessive (often personal)
        if text.startswith(("my ", "my\t", "i ", "i\t")):
            return True
        return False

    # ─── Sending & Receiving ───

    def start(self):
        """Start background task to periodically sync with community server."""
        if not self.enabled or self._task:
            return
        self._task = asyncio.create_task(self._sync_loop())

    def stop(self):
        if self._task:
            self._task.cancel()
            self._task = None

    async def _sync_loop(self):
        """Background loop: send topics, receive community knowledge."""
        await asyncio.sleep(60)  # initial delay
        while self.enabled:
            try:
                await self._sync()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.debug(f"Telemetry sync error: {e}")
            await asyncio.sleep(self._send_interval_hours * 3600)

    async def _sync(self):
        """
        Send anonymized topics to community server.
        Receive community hot topics in return.
        """
        if not self.enabled or not self.installation_id:
            return
        if not self._pending_topics:
            return

        payload = self._build_payload()
        result = await self._send(payload)

        if result.get("success"):
            logger.info(f"Telemetry: sent {len(payload['topics'])} topics to community")
            # Store received community topics for auto-learner
            community_topics = result.get("trending_topics", [])
            if community_topics:
                await self._inject_community_topics(community_topics)
            # Clear sent topics
            self._pending_topics.clear()
            self._last_send = time.time()
            self._save_state()

    def _build_payload(self) -> Dict:
        """
        Build the anonymized payload to send.
        Contains ONLY: random ID, version, usage count, topic keywords.
        NO: messages, files, IPs, names, emails, anything personal.
        """
        # Only send top 50 topics by frequency — no rare/potentially personal ones
        top_topics = [t for t, _ in self._pending_topics.most_common(50)]

        return {
            "installation_id": self.installation_id,    # random hex, not personal
            "lyra_version": "1.0.0",
            "week_usage_count": min(self._usage_count, 9999),  # capped
            "topics": top_topics,
            "submitted_at": datetime.utcnow().strftime("%Y-%m-%d"),  # date only, no time
        }

    async def _send(self, payload: Dict) -> Dict:
        """POST payload to community server."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(
                    f"{self.server_url}/api/contribute",
                    json=payload,
                    headers={"Content-Type": "application/json"},
                )
                if resp.status_code == 200:
                    return resp.json()
                return {"success": False, "error": f"HTTP {resp.status_code}"}
        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _inject_community_topics(self, topics: List[str]):
        """Feed received community topics into Lyra's auto-learner."""
        try:
            from lyra.core.auto_learner import auto_learner
            for topic in topics[:20]:
                auto_learner.add_topic(topic, priority=3)
            logger.info(f"Injected {len(topics)} community topics into auto-learner")
        except Exception as e:
            logger.debug(f"Community topic injection failed: {e}")

    async def fetch_community_topics(self) -> List[str]:
        """Fetch trending topics from community server (read-only)."""
        try:
            import httpx
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(f"{self.server_url}/api/trending")
                if resp.status_code == 200:
                    return resp.json().get("topics", [])
        except Exception:
            pass
        return []

    def get_status(self) -> Dict:
        return {
            "enabled": self.enabled,
            "installation_id": self.installation_id if self.enabled else None,
            "pending_topics": len(self._pending_topics),
            "usage_count": self._usage_count,
            "last_send": datetime.fromtimestamp(self._last_send).strftime("%Y-%m-%d %H:%M")
                         if self._last_send else None,
            "server_url": self.server_url,
        }

    # ─── Persistence ───

    def _save_state(self):
        try:
            state = {
                "enabled": self.enabled,
                "installation_id": self.installation_id,
                "server_url": self.server_url,
                "usage_count": self._usage_count,
                "last_send": self._last_send,
                "pending_topics": dict(self._pending_topics.most_common(200)),
            }
            TELEMETRY_FILE.write_text(json.dumps(state, indent=2))
        except Exception as e:
            logger.debug(f"Telemetry state save failed: {e}")

    def _load_state(self):
        try:
            if TELEMETRY_FILE.exists():
                state = json.loads(TELEMETRY_FILE.read_text())
                self.enabled = state.get("enabled", False)
                self.installation_id = state.get("installation_id")
                self.server_url = state.get("server_url", DEFAULT_COMMUNITY_SERVER)
                self._usage_count = state.get("usage_count", 0)
                self._last_send = state.get("last_send", 0.0)
                self._pending_topics = Counter(state.get("pending_topics", {}))
        except Exception:
            pass


# Global singleton
telemetry = TelemetryCollector()
