"""
Lyra AI Platform — Owner Authentication
Copyright (C) 2026 Lyra Contributors
Licensed under the Lyra Community License v1.0.

Ensures only the designated owner can:
  - Issue commands to LYRA
  - Access sensitive settings
  - Override autonomous behavior
  - Access private data

First run: generates a unique owner key, saved encrypted to disk.
Subsequent runs: authenticate with the key before privileged operations.
"""
import hashlib
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent.parent / "data"
AUTH_FILE = DATA_DIR / ".owner_auth.json"


def _derive_key(passphrase: str, salt: bytes) -> str:
    """Derive a stable key from passphrase + salt via PBKDF2."""
    dk = hashlib.pbkdf2_hmac(
        "sha256",
        passphrase.encode("utf-8"),
        salt,
        iterations=100_000,
        dklen=32,
    )
    return dk.hex()


class OwnerAuth:
    """
    Single-owner authentication for LYRA.

    Usage:
      - First launch: `lyra --set-owner` creates the owner key
      - Runtime: check `owner_auth.is_authenticated(token)` for privileged ops
      - CLI: sessions generate short-lived tokens after owner passphrase
    """

    def __init__(self):
        self._auth_data: Optional[dict] = None
        self._active_tokens: dict = {}  # token -> expiry
        self.owner_name: str = ""
        self._load()

    def is_configured(self) -> bool:
        """Returns True if an owner has been set up."""
        return self._auth_data is not None and self._auth_data.get("key_hash") is not None

    def setup_owner(self, passphrase: str, name: str = "Owner") -> str:
        """
        One-time setup: register the owner with a passphrase.
        Returns the generated owner key for backup.
        """
        if self.is_configured():
            raise ValueError("Owner already configured. Use reset_owner() to change.")

        salt = secrets.token_bytes(32)
        key_hash = _derive_key(passphrase, salt)
        owner_id = secrets.token_hex(8)

        self._auth_data = {
            "owner_id": owner_id,
            "owner_name": name,
            "key_hash": key_hash,
            "salt": salt.hex(),
            "created_at": time.time(),
        }
        self.owner_name = name
        self._save()

        # Update self-awareness
        try:
            from lyra.core.self_awareness import self_awareness
            self_awareness.set_owner(name)
        except Exception:
            pass

        logger.info(f"Owner configured: {name} (ID: {owner_id})")
        return owner_id

    def authenticate(self, passphrase: str, ttl_seconds: int = 3600) -> Optional[str]:
        """
        Verify passphrase and return a short-lived session token.
        Returns None on failure.
        """
        if not self.is_configured():
            # No owner set — open access (first run)
            return self._mint_token(ttl_seconds)

        salt = bytes.fromhex(self._auth_data["salt"])
        key_hash = _derive_key(passphrase, salt)

        if secrets.compare_digest(key_hash, self._auth_data["key_hash"]):
            token = self._mint_token(ttl_seconds)
            logger.info(f"Owner authenticated: {self._auth_data['owner_name']}")
            return token

        logger.warning("Authentication failed: incorrect passphrase")
        return None

    def is_authenticated(self, token: Optional[str]) -> bool:
        """Check if a session token is valid and unexpired."""
        if not self.is_configured():
            return True  # No owner set — allow all (initial setup)
        if token is None:
            return False
        expiry = self._active_tokens.get(token)
        if expiry is None:
            return False
        if time.time() > expiry:
            del self._active_tokens[token]
            return False
        return True

    def revoke_token(self, token: str):
        self._active_tokens.pop(token, None)

    def revoke_all_tokens(self):
        self._active_tokens.clear()

    def reset_owner(self, current_passphrase: str, new_passphrase: str, new_name: str = "") -> bool:
        """Reset owner credentials after verifying current passphrase."""
        if not self.is_configured():
            return False

        salt = bytes.fromhex(self._auth_data["salt"])
        key_hash = _derive_key(current_passphrase, salt)

        if not secrets.compare_digest(key_hash, self._auth_data["key_hash"]):
            return False

        # Wipe and reconfigure
        self._auth_data = None
        self.setup_owner(new_passphrase, new_name or self.owner_name)
        return True

    def get_owner_name(self) -> str:
        if self._auth_data:
            return self._auth_data.get("owner_name", "")
        return ""

    def get_status(self) -> dict:
        return {
            "configured": self.is_configured(),
            "owner_name": self.get_owner_name(),
            "active_sessions": len(self._active_tokens),
            "created_at": self._auth_data.get("created_at", 0) if self._auth_data else 0,
        }

    def _mint_token(self, ttl: int) -> str:
        token = secrets.token_urlsafe(32)
        self._active_tokens[token] = time.time() + ttl
        # Prune expired tokens
        now = time.time()
        self._active_tokens = {
            t: exp for t, exp in self._active_tokens.items() if exp > now
        }
        return token

    def _save(self):
        try:
            AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(AUTH_FILE, "w") as f:
                json.dump(self._auth_data, f, indent=2)
            # Restrict file permissions
            os.chmod(AUTH_FILE, 0o600)
        except Exception as e:
            logger.error(f"Failed to save owner auth: {e}")

    def _load(self):
        try:
            if AUTH_FILE.exists():
                with open(AUTH_FILE) as f:
                    self._auth_data = json.load(f)
                self.owner_name = self._auth_data.get("owner_name", "")
                logger.info(f"Owner auth loaded: {self.owner_name}")
        except Exception as e:
            logger.debug(f"Owner auth load failed: {e}")
            self._auth_data = None


# Singleton
owner_auth = OwnerAuth()
