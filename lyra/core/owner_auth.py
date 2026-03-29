"""
Lyra Owner Authentication
"""
import hashlib, json, logging, os, secrets, time
from pathlib import Path
from typing import Optional
logger = logging.getLogger(__name__)
DATA_DIR = Path(__file__).parent.parent.parent / 'data'
AUTH_FILE = DATA_DIR / '.owner_auth.json'
def _derive(pw, salt): return hashlib.pbkdf2_hmac('sha256', pw.encode(), salt, 100_000, 32).hex()
class OwnerAuth:
    def __init__(self): self._data = None; self._tokens = {}; self._load()
    def is_configured(self): return self._data is not None and self._data.get('key_hash')
    def setup_owner(self, pw, name='Owner'):
        if self.is_configured(): raise ValueError('Already configured')
        salt = secrets.token_bytes(32)
        self._data = {'owner_id': secrets.token_hex(8), 'owner_name': name, 'key_hash': _derive(pw, salt), 'salt': salt.hex(), 'created_at': time.time()}
        self._save(); return self._data['owner_id']
    def authenticate(self, pw, ttl=3600):
        if not self.is_configured(): return self._mint(ttl)
        salt = bytes.fromhex(self._data['salt'])
        if secrets.compare_digest(_derive(pw, salt), self._data['key_hash']): return self._mint(ttl)
        return None
    def is_authenticated(self, token):
        if not self.is_configured(): return True
        if not token: return False
        exp = self._tokens.get(token)
        if not exp: return False
        if time.time() > exp: del self._tokens[token]; return False
        return True
    def get_owner_name(self): return self._data.get('owner_name', '') if self._data else ''
    def get_status(self): return {'configured': self.is_configured(), 'owner_name': self.get_owner_name()}
    def _mint(self, ttl):
        t = secrets.token_urlsafe(32); self._tokens[t] = time.time() + ttl; return t
    def _save(self):
        AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(AUTH_FILE, 'w') as f: json.dump(self._data, f)
        os.chmod(AUTH_FILE, 0o600)
    def _load(self):
        try:
            if AUTH_FILE.exists():
                with open(AUTH_FILE) as f: self._data = json.load(f)
        except: self._data = None
owner_auth = OwnerAuth()
