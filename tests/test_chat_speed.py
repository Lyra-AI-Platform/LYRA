"""What keeps the first word of a reply quick."""
import pytest

from lyra.core import chat_speed as C


@pytest.mark.parametrize("message,quick", [("hi", True), ("Hello there", True), ("thanks!", True), ("good morning", True),
                                           ("yes please do it", True), ("hi, what moved Nvidia today and why?", False),
                                           ("explain tariffs", False), ("", False)])
def test_quick_messages(message, quick):
    assert C.is_quick(message) is quick


def test_looked_up_is_only_what_was_added():
    assert C.looked_up("base\n\nextra", "base") == "extra"
    assert C.looked_up("base", "base") == ""
    assert C.looked_up("other", "base") == ""


def test_context_goes_on_the_newest_question_only():
    turns = [{"role": "user", "content": "one"}, {"role": "assistant", "content": "two"}, {"role": "user", "content": "three"}]
    out = C.with_context(turns, "facts")
    assert out[:2] == turns[:2], "earlier turns stay identical so the model can reuse them"
    assert "facts" in out[2]["content"] and out[2]["content"].endswith("Question: three")
    assert turns[2]["content"] == "three"


def test_long_context_is_cut():
    out = C.with_context([{"role": "user", "content": "q"}], "x" * 10000)
    assert len(out[0]["content"]) < C.CONTEXT_CHARS + 100


def test_nothing_to_add():
    turns = [{"role": "user", "content": "q"}]
    assert C.with_context(turns, "") == turns
