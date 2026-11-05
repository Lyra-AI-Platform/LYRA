from lyra.api.version import read_git_head


def test_reads_a_branch_head(tmp_path):
    git = tmp_path / ".git"
    (git / "refs/heads").mkdir(parents=True)
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "refs/heads/main").write_text("abc123\n")
    assert read_git_head(tmp_path) == "abc123"


def test_reads_a_packed_ref(tmp_path):
    git = tmp_path / ".git"
    git.mkdir()
    (git / "HEAD").write_text("ref: refs/heads/main\n")
    (git / "packed-refs").write_text("# pack-refs\ndef456 refs/heads/main\n")
    assert read_git_head(tmp_path) == "def456"


def test_no_repository(tmp_path):
    assert read_git_head(tmp_path) is None
