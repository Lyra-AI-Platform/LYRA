"""LyraAuth bot defences: proof of work, server-side timing, graded answers and back-off."""
import time

import pytest

from lyra.authenticator import shield
from lyra.authenticator.engine import ChallengeEngine, ChallengeResponse


# ── Proof of work ─────────────────────────────────────────────────────────────

def test_pow_round_trip():
    salt = shield.new_salt()
    n = shield.solve_pow(salt, 10)
    assert n is not None and shield.pow_ok(salt, n, 10)
    assert not shield.pow_ok(salt + "x", n, 30)


@pytest.mark.parametrize("nonce", [None, "abc", -1, 2 ** 41])
def test_pow_rejects_junk(nonce):
    assert not shield.pow_ok("salt", nonce, 8)


def test_leading_zero_bits():
    assert shield.leading_zero_bits(bytes([0, 0, 0x10])) == 19
    assert shield.leading_zero_bits(bytes([0x80])) == 0
    assert shield.leading_zero_bits(bytes([0x01])) == 7


# ── Back-off ──────────────────────────────────────────────────────────────────

def test_difficulty_rises_with_failures_and_caps():
    assert shield.difficulty_for(0) == shield.POW_BASE_BITS
    assert shield.difficulty_for(3) == shield.POW_BASE_BITS + 3
    assert shield.difficulty_for(500) == shield.POW_MAX_BITS


def test_failures_expire():
    log = shield.FailureLog(window_s=10)
    log.record("1.2.3.4", now=100)
    log.record("1.2.3.4", now=105)
    assert log.count("1.2.3.4", now=106) == 2
    assert log.count("1.2.3.4", now=112) == 1
    assert log.count("1.2.3.4", now=200) == 0


# ── Scoring ───────────────────────────────────────────────────────────────────

def _score(**kw):
    base = dict(correct=True, graded=True, pow_passed=True, issued_at=100.0, now=104.0, claimed_ms=4000, signals={"interacted": True})
    base.update(kw)
    return shield.score(**base)


def test_person_passes():
    value, reason = _score()
    assert reason == "" and value >= 0.9


@pytest.mark.parametrize("change,reason", [
    (dict(pow_passed=False), "proof-of-work"),
    (dict(now=100.5), "too-fast"),
    (dict(graded=False), "ungraded"),
    (dict(correct=False), "wrong-answer"),
    (dict(signals={"webdriver": True, "interacted": False}), "low-score"),
])
def test_bots_fail(change, reason):
    assert _score(**change)[1] == reason


def test_forged_browser_timing_costs_score():
    honest, _ = _score()
    forged, _ = _score(claimed_ms=60_000)
    assert forged < honest


# ── The engine end to end ─────────────────────────────────────────────────────

def _answer(engine, c, answer=None, nonce="solve", wait=2.0, signals=None, claimed_ms=None):
    c.created_at -= wait          # pretend the person took `wait` seconds
    if nonce == "solve":
        nonce = shield.solve_pow(c.pow_salt, c.pow_bits)
    resp = ChallengeResponse(challenge_id=c.id, session_id="s", answer=c.correct_answer if answer is None else answer,
                             answer_time_ms=claimed_ms if claimed_ms is not None else int(wait * 1000), site_key="",
                             pow_nonce=nonce, signals=signals or {"interacted": True}, client_key="9.9.9.9")
    return engine.verify_response(resp), resp


@pytest.fixture
def engine(monkeypatch):
    monkeypatch.setattr(shield, "POW_BASE_BITS", 8)
    monkeypatch.setattr(shield, "POW_MAX_BITS", 12)
    e = ChallengeEngine()
    e._store_training_record = lambda *a, **k: None
    return e


def test_only_graded_challenges_are_served(engine):
    for _ in range(200):
        c = engine.generate_challenge(client_key="1.1.1.1")
        assert c.correct_answer is not None and c.pow_salt and c.pow_bits == 8


def test_person_gets_a_token_once(engine):
    c = engine.generate_challenge(client_key="9.9.9.9")
    (ok, value, token), _ = _answer(engine, c)
    assert ok and token and value >= 0.6
    (ok2, _, _), resp = _answer(engine, c)          # replay
    assert not ok2 and resp.reason == "unknown-challenge"


@pytest.mark.parametrize("kwargs,reason", [
    (dict(nonce=None), "proof-of-work"),
    (dict(nonce=12345), "proof-of-work"),
    (dict(wait=0.2), "too-fast"),
    (dict(answer="something not offered"), "not-an-option"),
    (dict(signals={"webdriver": True, "interacted": False, "headless": True}), "low-score"),
])
def test_bot_attempts_fail(engine, kwargs, reason):
    c = engine.generate_challenge(client_key="9.9.9.9")
    if kwargs.get("answer") == "something not offered" and not c.options:
        pytest.skip("free-text challenge")
    (ok, _, token), resp = _answer(engine, c, **kwargs)
    assert not ok and not token and resp.reason == reason


def test_wrong_answer_fails(engine):
    c = engine.generate_challenge(client_key="9.9.9.9")
    wrong = next((o for o in c.options if o.strip() != c.correct_answer.strip()), None)
    if wrong is None:
        pytest.skip("no wrong option")
    (ok, _, _), resp = _answer(engine, c, answer=wrong)
    assert not ok and resp.reason == "wrong-answer"


def test_failures_make_the_next_puzzle_harder_and_success_resets(engine):
    for _ in range(3):
        c = engine.generate_challenge(client_key="9.9.9.9")
        _answer(engine, c, nonce=None)
    harder = engine.generate_challenge(client_key="9.9.9.9")
    assert harder.pow_bits == 11
    (ok, _, _), _ = _answer(engine, harder)
    assert ok
    assert engine.generate_challenge(client_key="9.9.9.9").pow_bits == 8


# ── Old cached widgets (before 1.3.0) ─────────────────────────────────────────

def test_old_widget_passes_only_until_the_cutoff():
    before = shield.LEGACY_UNTIL - 3600
    after = shield.LEGACY_UNTIL + 1
    ok, reason = shield.score(correct=True, graded=True, pow_passed=False, issued_at=before - 4, now=before,
                              claimed_ms=4000, signals={"legacy_widget": True})
    assert reason == "" and 0.6 <= ok < 0.9
    _, reason = shield.score(correct=True, graded=True, pow_passed=False, issued_at=after - 4, now=after,
                             claimed_ms=4000, signals={"legacy_widget": True})
    assert reason == "proof-of-work"


def test_new_widget_without_proof_of_work_is_never_legacy(engine):
    c = engine.generate_challenge(client_key="9.9.9.9")
    (ok, _, _), resp = _answer(engine, c, nonce=None, signals={"interacted": True})
    assert not ok and resp.reason == "proof-of-work"
