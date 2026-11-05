"""Chats survive a restart: a second process sees what the first wrote."""
from lyra.api.chat_history import ChatDB, Conversations, Owners


def test_history_and_owners_survive_a_restart(tmp_path):
    db = ChatDB(tmp_path / "chat.db")
    conversations, owners = Conversations(db), Owners(db)
    conversations["c1"] = []
    conversations["c1"].append({"role": "user", "content": "hello"})
    conversations["c1"].append({"role": "assistant", "content": "hi"})
    owners.setdefault("c1", 7)

    restarted = ChatDB(tmp_path / "chat.db")
    assert [m["content"] for m in Conversations(restarted)["c1"]] == ["hello", "hi"]
    assert Owners(restarted)["c1"] == 7


def test_appending_after_a_restart_keeps_saving(tmp_path):
    db = ChatDB(tmp_path / "chat.db")
    conversations = Conversations(db)
    conversations["c1"] = [{"role": "user", "content": "one"}]
    again = Conversations(ChatDB(tmp_path / "chat.db"))
    again["c1"].append({"role": "user", "content": "two"})
    assert len(Conversations(ChatDB(tmp_path / "chat.db"))["c1"]) == 2


def test_deleting_a_chat_removes_it_from_disk(tmp_path):
    db = ChatDB(tmp_path / "chat.db")
    conversations, owners = Conversations(db), Owners(db)
    conversations["c1"] = [{"role": "user", "content": "secret"}]
    owners["c1"] = 7
    conversations.pop("c1", None)
    assert "c1" not in Conversations(db)
    assert "c1" not in Owners(db)


def test_setdefault_never_changes_an_owner(tmp_path):
    owners = Owners(ChatDB(tmp_path / "chat.db"))
    owners.setdefault("c1", 7)
    assert owners.setdefault("c1", 8) == 7
