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
    [
        b"a\\b.c",
        b"../a.c",
        b"a//b.c",
        b"/abs.c",
        b"a/.git/config",
        b"\xff.c",
        b"x.c.",
        b"x.c ",
        b"dir./x.c",
        b"dir /x.c",
        b"x:y.c",
    ],
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


def make_repository(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "user.name", "synthetic")
    return repo


def test_abbreviated_non_tip_commit_is_found_by_bounded_deepening(tmp_path):
    repo = make_repository(tmp_path)
    commits = []
    for value in range(3):
        (repo / "a.c").write_text(f"int value = {value};\n", encoding="utf-8")
        commits.append(_commit(repo, str(value)))
    client = SubprocessGitClient(
        tmp_path / "mirrors", max_fetch_depth=3, allow_local_transport=True
    )
    handle = client.fetch(str(repo), commits[0][:10])
    assert client.resolve(handle, commits[0][:10]) == commits[0]


def test_abbreviation_outside_fetch_depth_is_not_declared_absent(tmp_path):
    repo = make_repository(tmp_path)
    (repo / "a.c").write_text("int first;\n", encoding="utf-8")
    first = _commit(repo, "first")
    (repo / "a.c").write_text("int second;\n", encoding="utf-8")
    _commit(repo, "second")
    client = SubprocessGitClient(
        tmp_path / "mirrors", max_fetch_depth=1, allow_local_transport=True
    )
    with pytest.raises(IntegrationError) as failure:
        client.fetch(str(repo), first[:10])
    assert failure.value.code == "commit_lookup_limited"
    handle = client.fetch(str(repo), first)
    assert client.resolve(handle, first) == first


def test_fetch_rolls_back_an_oversized_mirror(tmp_path):
    import random

    repo = make_repository(tmp_path)
    (repo / "large.bin").write_bytes(random.Random(42).randbytes(200_000))
    commit = _commit(repo, "large synthetic blob")
    client = SubprocessGitClient(
        tmp_path / "mirrors", max_total_bytes=64_000, allow_local_transport=True
    )
    with pytest.raises(IntegrationError) as failure:
        client.fetch(str(repo), commit)
    assert failure.value.code == "storage_quota_exceeded"
    assert client.local_mirror(str(repo)) is None
    assert list(client.mirror_root.iterdir()) == []


def test_tree_file_limit_stops_consuming_the_pipe(tmp_path, monkeypatch):
    import io
    from contextlib import contextmanager
    from types import SimpleNamespace

    records = b"".join(b"100644 blob " + b"1" * 40 + f"\tf{i}.c\0".encode() for i in range(10_000))
    stream = io.BytesIO(records)

    @contextmanager
    def fake_stream(*args, **kwargs):
        yield SimpleNamespace(stdout=stream, wait=lambda: 0)

    client = SubprocessGitClient(tmp_path / "mirrors", max_files=1)
    monkeypatch.setattr(client, "_stream_process", fake_stream)
    with pytest.raises(IntegrationError) as failure:
        client._tree_entries(tmp_path / "handle", "1" * 40)
    assert failure.value.code == "snapshot_too_large"
    assert stream.tell() <= 4096 < len(records)


@pytest.mark.parametrize("paths", [(b"a.c", b"A.c"), (b"dir/a.c", b"DIR/b.c")])
def test_export_rejects_case_aliases_before_overwriting(tmp_path, monkeypatch, paths):
    repo = make_repository(tmp_path)
    (repo / "a.c").write_text("int a;\n", encoding="utf-8")
    commit = _commit(repo, "source")
    client = SubprocessGitClient(tmp_path / "mirrors", allow_local_transport=True)
    handle = client.fetch(str(repo), commit)
    sha = _git(repo, "rev-parse", "HEAD:a.c")
    monkeypatch.setattr(client, "_tree_entries", lambda *a, **kw: [(sha, path) for path in paths])
    with pytest.raises(IntegrationError) as failure:
        client.export(handle, commit, tmp_path / "exported")
    assert failure.value.code == "snapshot_export_failed"
    assert (tmp_path / "exported" / paths[0].decode()).read_text(encoding="utf-8") == "int a;\n"


@pytest.mark.parametrize("cancelled", [False, True])
def test_blocked_stream_reads_stop_the_process_tree(tmp_path, cancelled):
    import sys
    import threading
    import time

    class PythonProcessClient(SubprocessGitClient):
        @property
        def options(self):
            return ()

    client = PythonProcessClient(
        tmp_path / "mirrors", executable=sys.executable, timeout_seconds=5 if cancelled else 0.15
    )
    cancel = threading.Event()
    timer = threading.Timer(0.15, cancel.set)
    if cancelled:
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(IntegrationError) as failure:
            # 子进程继承 stdout；仅杀父进程会让 read 再等 10 秒。
            with client._stream_process(
                [
                    "-c",
                    (
                        "import subprocess, sys, time; "
                        "subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(10)']); "
                        "time.sleep(10)"
                    ),
                ],
                cancel_event=cancel,
            ) as process:
                process.stdout.read()
        assert failure.value.code == (
            "repository_cancelled" if cancelled else "repository_fetch_timeout"
        )
        assert time.monotonic() - started < 3
    finally:
        timer.cancel()


def test_running_fetch_checks_quota_before_reading_more_output(tmp_path, monkeypatch):
    mirror = tmp_path / "mirrors" / "working.git"
    mirror.mkdir(parents=True)
    client = SubprocessGitClient(mirror.parent, max_total_bytes=10)

    class GrowingProcess(_FakeProcess):
        def communicate(self, timeout=None):
            if self.returncode == -9:
                return "", ""
            (mirror / "pack").write_bytes(b"x" * 20)
            raise subprocess.TimeoutExpired(self.command, timeout)

    process = GrowingProcess([])
    monkeypatch.setattr("app.repository.gitclient.subprocess.Popen", lambda *a, **kw: process)
    monkeypatch.setattr(client, "_kill_process", lambda proc: setattr(proc, "returncode", -9))
    with pytest.raises(IntegrationError) as failure:
        client._execute(["fetch"], quota_path=mirror)
    assert failure.value.code == "storage_quota_exceeded"
    assert process.returncode == -9


def test_running_fetch_does_not_rescan_all_mirrors_on_every_poll(tmp_path, monkeypatch):
    clock = [0.0]
    checks = []
    polls = []
    client = SubprocessGitClient(tmp_path / "mirrors", timeout_seconds=10)

    class PollingProcess(_FakeProcess):
        def communicate(self, timeout=None):
            polls.append(clock[0])
            clock[0] += 0.2
            if len(polls) < 12:
                raise subprocess.TimeoutExpired(self.command, timeout)
            return "", ""

    monkeypatch.setattr("app.repository.gitclient.time.monotonic", lambda: clock[0])
    monkeypatch.setattr(
        "app.repository.gitclient.subprocess.Popen", lambda *a, **kw: PollingProcess([])
    )
    monkeypatch.setattr(client, "_enforce_mirror_quota", lambda **kwargs: checks.append(clock[0]))
    client._execute(["fetch"], quota_path=tmp_path / "mirrors" / "working.git")
    assert checks[0] == 0
    assert 2 <= len(checks) < len(polls) // 2
    assert all(later - earlier >= 1 for earlier, later in zip(checks, checks[1:]))


@pytest.mark.parametrize("failed_step", ["write", "flush", "header", "blob", "terminator"])
def test_export_pipe_errors_survive_stream_cleanup(tmp_path, monkeypatch, failed_step):
    import io
    from types import SimpleNamespace

    class Writer:
        closed = False

        def write(self, data):
            if failed_step == "write":
                raise BrokenPipeError("child exited")
            return len(data)

        def flush(self):
            if failed_step == "flush":
                raise BrokenPipeError("child exited")

        def close(self):
            self.closed = True
            raise BrokenPipeError("close flushes pending input")

    class Reader(io.BytesIO):
        def readline(self, *args):
            if failed_step == "header":
                raise OSError("closed header pipe")
            return super().readline(*args)

        def read(self, size=-1):
            if failed_step == "blob" or (failed_step == "terminator" and size == 1):
                raise OSError("closed data pipe")
            return super().read(size)

    writer = Writer()
    reader = Reader(b"1" * 40 + b" blob 3\nabc\n")
    process = SimpleNamespace(stdin=writer, stdout=reader, poll=lambda: 0, wait=lambda: 0)
    client = SubprocessGitClient(tmp_path / "mirrors")
    monkeypatch.setattr("app.repository.gitclient.subprocess.Popen", lambda *a, **kw: process)
    monkeypatch.setattr(client, "_tree_entries", lambda *a, **kw: [("1" * 40, b"a.c")])
    with pytest.raises(IntegrationError) as failure:
        client.export(tmp_path / "mirror.git", "1" * 40, tmp_path / "exported")
    assert failure.value.code == "snapshot_export_failed"
    assert writer.closed and reader.closed


@pytest.mark.parametrize("code", ["snapshot_export_failed", "repository_cancelled"])
def test_real_exited_process_pipe_close_preserves_primary_error(tmp_path, code):
    import sys

    class PythonProcessClient(SubprocessGitClient):
        @property
        def options(self):
            return ()

    client = PythonProcessClient(tmp_path / "mirrors", executable=sys.executable)
    expected = IntegrationError(code, "synthetic primary failure")
    with pytest.raises(IntegrationError) as failure:
        with client._stream_process(["-c", "pass"]) as process:
            process.wait(timeout=2)
            process.stdin.write(b"x")  # 保留待刷新的输入，close 将遇到已退出的子进程。
            raise expected
    assert failure.value is expected
    assert process.stdin.closed and process.stdout.closed


@pytest.mark.parametrize(
    "response",
    [
        b"1" * 40 + b" blob -1\n",
        b"1" * 40 + b" blob invalid\n",
        b"1" * 40 + b" blob 3\nab",
        b"1" * 40 + b" blob 3\nabc",
    ],
)
def test_export_rejects_invalid_or_truncated_blob_responses(tmp_path, monkeypatch, response):
    import io
    from contextlib import contextmanager
    from types import SimpleNamespace

    client = SubprocessGitClient(tmp_path / "mirrors")

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(stdin=io.BytesIO(), stdout=io.BytesIO(response))

    monkeypatch.setattr(client, "_stream_process", stream)
    monkeypatch.setattr(client, "_tree_entries", lambda *a, **kw: [("1" * 40, b"a.c")])
    with pytest.raises(IntegrationError) as failure:
        client.export(tmp_path / "mirror.git", "1" * 40, tmp_path / "exported")
    assert failure.value.code == "snapshot_export_failed"


@pytest.mark.parametrize("object_id", [b"\xff" * 40, b"1" * 39, b"z" * 40])
def test_tree_rejects_invalid_object_ids_as_export_failures(tmp_path, monkeypatch, object_id):
    import io
    from contextlib import contextmanager
    from types import SimpleNamespace

    client = SubprocessGitClient(tmp_path / "mirrors")

    @contextmanager
    def stream(*args, **kwargs):
        yield SimpleNamespace(
            stdout=io.BytesIO(b"100644 blob " + object_id + b"\ta.c\0"), wait=lambda: 0
        )

    monkeypatch.setattr(client, "_stream_process", stream)
    with pytest.raises(IntegrationError) as failure:
        client._tree_entries(tmp_path / "mirror.git", "1" * 40)
    assert failure.value.code == "snapshot_export_failed"


@pytest.mark.parametrize("error", [OSError("closed tree pipe"), ValueError("closed stream")])
def test_tree_pipe_read_errors_are_export_failures(tmp_path, monkeypatch, error):
    import io
    from types import SimpleNamespace

    class Reader(io.BytesIO):
        def read1(self, size=-1):
            raise error

    reader = Reader()
    writer = io.BytesIO()
    process = SimpleNamespace(stdin=writer, stdout=reader, poll=lambda: 0, wait=lambda: 0)
    client = SubprocessGitClient(tmp_path / "mirrors")
    monkeypatch.setattr("app.repository.gitclient.subprocess.Popen", lambda *a, **kw: process)
    with pytest.raises(IntegrationError) as failure:
        client.export(tmp_path / "mirror.git", "1" * 40, tmp_path / "exported")
    assert failure.value.code == "snapshot_export_failed"
    assert writer.closed and reader.closed


@pytest.mark.parametrize("message", ["parent directory fix", "parent " + "f" * 40])
def test_parent_lines_in_commit_messages_do_not_affect_parent_selection(tmp_path, message):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "synthetic@example.invalid")
    _git(repo, "config", "user.name", "synthetic")
    (repo / "a.c").write_text("int value = 1;\n", encoding="utf-8")
    first = _commit(repo, message)
    (repo / "a.c").write_text("int value = 2;\n", encoding="utf-8")
    second = _commit(repo, message)
    client = SubprocessGitClient(tmp_path / "mirrors")
    assert client.parents(repo, first) == []
    assert client.parents(repo, second) == [first]


def test_invalid_parent_in_commit_header_still_fails(tmp_path, monkeypatch):
    client = SubprocessGitClient(tmp_path / "mirrors")
    monkeypatch.setattr(
        client, "_run", lambda *args, **kwargs: "tree " + "1" * 40 + "\nparent invalid\n\nmessage"
    )
    with pytest.raises(IntegrationError) as failure:
        client.parents(tmp_path / "repo", "2" * 40)
    assert failure.value.code == "commit_not_found"
