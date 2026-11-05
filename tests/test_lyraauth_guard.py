"""LyraAuth checks that run without the database: site origins and siteverify bodies."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location(
    "lyraauth_guard", Path(__file__).parent.parent / "lyra" / "authenticator" / "guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


@pytest.mark.parametrize("domain,origin,referer,allowed", [
    ("example.com", "https://example.com", None, True),
    ("example.com", "https://www.example.com", None, True),
    ("www.example.com", "https://example.com", None, True),
    ("example.com", "https://shop.example.com", None, True),
    ("example.com", None, "https://example.com/contact", True),
    ("example.com", "http://localhost:3000", None, True),
    ("", "https://anything.test", None, True),
    ("example.com", "https://evil.test", None, False),
    ("example.com", "https://notexample.com", None, False),
    ("example.com", "https://example.com.evil.test", None, False),
    ("example.com", "null", None, False),
    ("example.com", None, None, False),
])
def test_origin_allowed(domain, origin, referer, allowed):
    assert guard.origin_allowed(domain, origin, referer) is allowed


@pytest.mark.parametrize("body,content_type,expected", [
    (b'{"secret_key":"s","token":"t"}', "application/json", ("s", "t")),
    (b'{"secret":"s","response":"t"}', "application/json", ("s", "t")),
    (b"secret_key=s&token=t", "application/x-www-form-urlencoded", ("s", "t")),
    (b"secret=s&response=t", "application/x-www-form-urlencoded; charset=utf-8", ("s", "t")),
    (b"", "application/json", ("", "")),
    (b"not json", "application/json", ("", "")),
    (b"[1,2]", "application/json", ("", "")),
    (b'{"secret_key":1,"token":{}}', "application/json", ("", "")),
])
def test_parse_siteverify(body, content_type, expected):
    assert guard.parse_siteverify(body, content_type) == expected


def test_secret_keys_are_hashed_and_compared():
    stored = guard.hash_secret("lyra_secret_abc")
    assert stored.startswith("sha256:") and "abc" not in stored
    assert guard.is_hashed(stored) and not guard.is_hashed("lyra_secret_abc")
    assert guard.secret_matches(stored, "lyra_secret_abc")
    assert not guard.secret_matches(stored, "lyra_secret_abd")


@pytest.mark.parametrize("origin,referer,host", [
    ("https://shop.example.com", None, "shop.example.com"),
    (None, "https://a.example/page", "a.example"),
    ("null", "https://a.example/", "a.example"),
    (None, None, ""),
])
def test_the_host_a_challenge_was_solved_on(origin, referer, host):
    assert guard.solved_on(origin, referer) == host
