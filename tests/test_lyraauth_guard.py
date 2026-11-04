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
