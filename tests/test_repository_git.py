"""真实 Git 集成：本地临时仓库验证拉取、父提交、导出与缓存。

无系统 Git 时跳过；快照仍不包含 `.git`，也不保留历史。
"""

import shutil
import subprocess

import pytest
from app.repository.gitclient import SubprocessGitClient
from app.schemas.ports import IntegrationError

GIT = shutil.which("git")
pytestmark = pytest.mark.skipif(GIT is None, reason="需要系统 Git 才能验证真实拉取")


def _git(repo, *args) -> str:
    completed = subprocess.run(
        [GIT, *args], cwd=repo, check=True, capture_output=True, text=True, encoding="utf-8"
    )
    return completed.stdout.strip()


def _commit(repo, message: str) -> str:
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", message)
    return _git(repo, "rev-parse", "HEAD")


def test_fetch_parent_export_and_cache(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "user.name", "synthetic")
    (repo / "src").mkdir()
    (repo / "src" / "a.c").write_text("int value = 1;\n", encoding="utf-8")
    first = _commit(repo, "first")
    (repo / "src" / "a.c").write_text("int value = 2;\n", encoding="utf-8")
    second = _commit(repo, "second")

    client = SubprocessGitClient(tmp_path / "mirrors", allow_local_transport=True)
    handle = client.fetch(str(repo), second)
    assert client.resolve(handle, second[:10]) == second
    assert client.parents(handle, second) == [first]

    client.ensure(handle, first)
    destination = tmp_path / "exported"
    assert client.export(handle, first, destination) == 1
    assert (destination / "src" / "a.c").read_text(encoding="utf-8") == "int value = 1;\n"
    assert not (destination / ".git").exists()
    assert sorted(path.name for path in destination.rglob("*") if path.is_file()) == ["a.c"]

    assert client.fetch(str(repo), second) == handle
    assert len(list((tmp_path / "mirrors").iterdir())) == 1


def test_missing_repository_and_commit_are_reported(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "user.name", "synthetic")
    (repo / "a.c").write_text("int value = 1;\n", encoding="utf-8")
    _commit(repo, "only")

    client = SubprocessGitClient(tmp_path / "mirrors", allow_local_transport=True)
    with pytest.raises(IntegrationError) as missing_repo:
        client.fetch(str(tmp_path / "absent"), "a" * 40)
    assert missing_repo.value.code == "repository_fetch_failed"

    with pytest.raises(IntegrationError) as missing_commit:
        client.fetch(str(repo), "a" * 40)
    assert missing_commit.value.code == "commit_not_found"


def test_export_does_not_apply_archive_attributes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "user.name", "synthetic")
    (repo / ".gitattributes").write_text("*.c export-ignore\n", encoding="utf-8")
    (repo / "a.c").write_text("int value = 1;\n", encoding="utf-8")
    commit = _commit(repo, "attributes")

    client = SubprocessGitClient(tmp_path / "mirrors", allow_local_transport=True)
    handle = client.fetch(str(repo), commit)
    destination = tmp_path / "exported"
    assert client.export(handle, commit, destination) == 2
    assert (destination / "a.c").read_text(encoding="utf-8") == "int value = 1;\n"


class _FakeProcess:
    def __init__(self, command, **kwargs):
        self.command = command
        self.returncode = 0

    def communicate(self, timeout=None):
        return "", ""

    def kill(self):
        pass

    def poll(self):
        return 0

    def wait(self):
        return 0


def test_git_subprocess_uses_security_options_and_scrubbed_env(tmp_path, monkeypatch):
    captured = {}

    def fake_popen(command, **kwargs):
        captured["command"] = command
        captured["env"] = kwargs["env"]
        return _FakeProcess(command, **kwargs)

    monkeypatch.setattr("app.repository.gitclient.subprocess.Popen", fake_popen)
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "url.https://evil.test.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "https://github.com")

    client = SubprocessGitClient(tmp_path / "mirrors")
    client._execute(["version"])

    command = captured["command"]
    for option in (
        "http.followRedirects=false",
        "protocol.allow=never",
        "protocol.https.allow=always",
        "credential.helper=",
    ):
        assert option in command
    env = captured["env"]
    assert "GIT_CONFIG_COUNT" not in env
    assert "GIT_CONFIG_KEY_0" not in env
    assert "GIT_CONFIG_VALUE_0" not in env
    assert env["GIT_CONFIG_NOSYSTEM"] == "1"


@pytest.mark.parametrize(
    "raw",
    [b"a\\b.c", b"../a.c", b"a//b.c", b"/abs.c", b"a/.git/config", b"\xff.c"],
)
def test_export_rejects_ambiguous_paths(raw):
    from app.repository.gitclient import _relative_path

    with pytest.raises(IntegrationError):
        _relative_path(raw)


def test_transport_is_hardened_against_redirects_and_non_https(tmp_path):
    client = SubprocessGitClient(tmp_path / "mirrors")
    assert "http.followRedirects=false" in client.options
    assert "protocol.allow=never" in client.options
    assert "protocol.https.allow=always" in client.options
    assert "credential.helper=" in client.options
    assert "protocol.file.allow=always" not in client.options
