"""快照存储：发布事务、并发、配额、临时清理与文本校验。"""

import os
import threading

import pytest
from app.repository.store import ScanReport, SnapshotStore
from app.schemas.ports import IntegrationError

REPO = "https://github.com/acme/buf.git"


def stage(store: SnapshotStore, name: str = "a.c", content: str = "int a;\n"):
    staged = store.new_temp_dir()
    (staged / name).write_text(content, encoding="utf-8")
    return staged


def test_publish_is_idempotent_and_repairs_orphan_tree(tmp_path):
    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    store.publish(stage(store), ref, repo_url=REPO, commit="1" * 40)
    store.publish(stage(store, "b.c"), ref, repo_url=REPO, commit="1" * 40)

    assert store.exists(ref)
    assert (store.snapshots / ref / "a.c").is_file()
    assert not (store.snapshots / ref / "b.c").exists()

    orphan_ref = store.ref_for(REPO, "2" * 40)
    orphan = store.snapshots / orphan_ref
    orphan.mkdir(parents=True)
    (orphan / "stale.c").write_text("stale", encoding="utf-8")
    assert not store.exists(orphan_ref)

    store.publish(stage(store, "c.c"), orphan_ref, repo_url=REPO, commit="2" * 40)
    assert store.exists(orphan_ref)
    assert not (store.snapshots / orphan_ref / "stale.c").exists()
    assert (store.snapshots / orphan_ref / "c.c").is_file()


def test_concurrent_publication_of_one_ref_is_safe(tmp_path):
    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    failures: list[BaseException] = []

    def worker(name: str) -> None:
        try:
            store.publish(stage(store, name), ref, repo_url=REPO, commit="1" * 40)
        except BaseException as exc:  # noqa: BLE001 - 记录线程异常用于断言
            failures.append(exc)

    threads = [threading.Thread(target=worker, args=(f"f{index}.c",)) for index in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert store.exists(ref)
    assert len(list((store.snapshots / ref).glob("*.c"))) == 1


def test_cleanup_temp_removes_abandoned_staging_dirs(tmp_path):
    store = SnapshotStore(tmp_path / "storage")
    leftover = store.new_temp_dir()
    (leftover / "half.c").write_text("half", encoding="utf-8")

    store.cleanup_temp()

    assert not leftover.exists()


def test_storage_quota_preserves_previously_issued_snapshots(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_bytes=12)
    old = store.ref_for(REPO, "1" * 40)
    new = store.ref_for(REPO, "2" * 40)
    store.publish(stage(store, "a.c", "int aaaa;\n"), old, repo_url=REPO, commit="1" * 40)
    os.utime(store.refs / f"{old}.json", (1, 1))
    with pytest.raises(IntegrationError, match="配额"):
        store.publish(stage(store, "b.c", "int bbbb;\n"), new, repo_url=REPO, commit="2" * 40)

    assert not store.exists(new)
    assert store.exists(old)
    assert store.read_text(store.snapshot_dir(old) / "a.c") == "int aaaa;\n"


def test_concurrent_publications_respect_shared_quota(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_bytes=12)
    refs = [store.ref_for(REPO, str(index) * 40) for index in (1, 2)]
    outcomes: list[str] = []

    def worker(ref: str) -> None:
        try:
            store.publish(stage(store, "x.c", "int value;\n"), ref, repo_url=REPO, commit="1" * 40)
            outcomes.append("ok")
        except IntegrationError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=worker, args=(ref,)) for ref in refs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert sorted(outcomes) == ["ok", "storage_quota_exceeded"]
    assert len([ref for ref in refs if store.exists(ref)]) == 1


def test_mirror_quota_evicts_idle_mirror_only(tmp_path):
    from app.repository.gitclient import SubprocessGitClient

    root = tmp_path / "mirrors"
    root.mkdir()
    old = root / "old.git"
    fresh = root / "fresh.git"
    for path in (old, fresh):
        path.mkdir()
        (path / "pack").write_bytes(b"x" * 8)
    os.utime(old, (1, 1))

    client = SubprocessGitClient(root, max_total_bytes=12, min_idle_seconds=600)
    client._enforce_mirror_quota(keep=fresh)

    assert not old.exists()
    assert fresh.exists()


def test_mirror_quota_keeps_recently_used_mirrors(tmp_path):
    from app.repository.gitclient import SubprocessGitClient

    root = tmp_path / "mirrors"
    root.mkdir()
    first = root / "first.git"
    second = root / "second.git"
    for path in (first, second):
        path.mkdir()
        (path / "pack").write_bytes(b"x" * 8)

    client = SubprocessGitClient(root, max_total_bytes=12, min_idle_seconds=600)
    with pytest.raises(IntegrationError) as exhausted:
        client._enforce_mirror_quota(keep=first)
    assert exhausted.value.code == "storage_quota_exceeded"
    assert not first.exists() and second.exists()


def test_mirror_quota_does_not_evict_an_old_but_locked_mirror(tmp_path):
    from app.repository.gitclient import SubprocessGitClient

    client = SubprocessGitClient(tmp_path / "mirrors", max_total_bytes=12, min_idle_seconds=0)
    busy, current = client.mirror_root / "busy.git", client.mirror_root / "current.git"
    for path in (busy, current):
        path.mkdir(parents=True)
        (path / "pack").write_bytes(b"x" * 8)
    os.utime(busy, (1, 1))
    with client._lock_for(busy):
        with pytest.raises(IntegrationError) as failure:
            client._enforce_mirror_quota(keep=current)
    assert failure.value.code == "storage_quota_exceeded"
    assert busy.exists() and not current.exists()


def test_read_text_rejects_binary_and_invalid_utf8(tmp_path):
    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    staged = store.new_temp_dir()
    (staged / "binary.c").write_bytes(b"\x00\x01")
    (staged / "latin1.c").write_bytes(b"int caf\xe9;\n")
    store.publish(staged, ref, repo_url=REPO, commit="1" * 40)
    root = store.snapshots / ref

    for name in ("binary.c", "latin1.c"):
        with pytest.raises(IntegrationError) as failure:
            store.read_text(root / name)
        assert failure.value.code == "file_unreadable"


def test_concurrent_publications_that_fit_do_not_double_count(tmp_path, monkeypatch):
    from app.repository import store as store_module

    store = SnapshotStore(tmp_path / "storage", max_total_bytes=20, max_total_entries=6)
    first_visible = threading.Event()
    release_first = threading.Event()
    failures = []
    refs = [store.ref_for(REPO, str(index) * 40) for index in (1, 2)]
    original_replace = os.replace

    def replace(source, target):
        original_replace(source, target)
        if target == store.snapshots / refs[0]:
            first_visible.set()
            assert release_first.wait(5)

    monkeypatch.setattr(store_module.os, "replace", replace)

    def worker(ref):
        try:
            store.publish(stage(store, content="1234567890"), ref, repo_url=REPO, commit="1" * 40)
        except BaseException as exc:
            failures.append(exc)

    first = threading.Thread(target=worker, args=(refs[0],))
    second = threading.Thread(target=worker, args=(refs[1],))
    first.start()
    try:
        assert first_visible.wait(5)
        second.start()
        second.join(timeout=0.1)
    finally:
        release_first.set()
        first.join(timeout=5)
        if second.ident is not None:
            second.join(timeout=5)

    assert not first.is_alive() and not second.is_alive()
    assert failures == []
    assert all(store.exists(ref) for ref in refs)


def test_nul_beyond_prefix_is_rejected_by_both_text_paths(tmp_path):
    store = SnapshotStore(tmp_path / "storage")
    path = tmp_path / "binary.c"
    path.write_bytes(b"x" * 9000 + b"\n\x00binary\n")

    for read in (lambda: store.read_text(path), lambda: store.read_lines(path, 1, 1, max_lines=10)):
        with pytest.raises(IntegrationError) as failure:
            read()
        assert failure.value.code == "file_unreadable"


def test_extensionless_preview_uses_a_bounded_read(tmp_path, monkeypatch):
    from pathlib import Path

    from app.repository.store import _looks_like_source

    path = tmp_path / "header"
    path.write_bytes(b"#define VALUE 1\n" + b"x" * 100_000)

    def reject_full_read(_path):
        pytest.fail("source preview must not read the entire file")

    monkeypatch.setattr(Path, "read_bytes", reject_full_read)
    assert _looks_like_source(path)


def test_oversized_extensionless_files_are_skipped_before_preview(tmp_path, monkeypatch):
    from app.repository import store as store_module

    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    store.publish(
        stage(store, name="header", content="#define VALUE 1\n"),
        ref,
        repo_url=REPO,
        commit="1" * 40,
    )
    monkeypatch.setattr(store_module, "_looks_like_source", lambda _path: pytest.fail("oversized"))
    assert list(store.iter_files(ref, max_bytes=4)) == []


def test_scan_checks_cancellation_while_skipping_non_source_files(tmp_path, monkeypatch):
    from pathlib import Path

    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    staged = stage(store, name="a.txt")
    (staged / "b.txt").write_text("not source", encoding="utf-8")
    store.publish(staged, ref, repo_url=REPO, commit="1" * 40)
    cancel = threading.Event()
    visited = set()
    original_stat = Path.lstat

    def stop_after_first_file(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path.suffix == ".txt":
            visited.add(path.name)
            cancel.set()
        return result

    monkeypatch.setattr(Path, "lstat", stop_after_first_file)
    with pytest.raises(IntegrationError) as failure:
        list(store.iter_files(ref, cancel_event=cancel))
    assert failure.value.code == "repository_cancelled"
    assert visited == {"a.txt"}


@pytest.mark.parametrize("byte_limit", [None, 1000])
def test_empty_files_consume_global_entry_quota_after_restart(tmp_path, byte_limit):
    root = tmp_path / "storage"
    store = SnapshotStore(root, max_total_bytes=byte_limit, max_total_entries=5)
    old, new = (store.ref_for(REPO, str(index) * 40) for index in (1, 2))
    staged = store.new_temp_dir()
    for index in range(3):
        (staged / f"{index}.c").touch()
    store.publish(staged, old, repo_url=REPO, commit="1" * 40)

    restarted = SnapshotStore(root, max_total_bytes=byte_limit, max_total_entries=5)
    assert restarted.exists(old)
    with pytest.raises(IntegrationError) as failure:
        restarted.publish(stage(restarted, content=""), new, repo_url=REPO, commit="2" * 40)
    assert failure.value.code == "storage_quota_exceeded"
    assert not restarted.exists(new)
    assert not (restarted.refs / f"{new}.json").exists()
    # 已发布引用重试不再消耗条目；旧引用继续可读。
    restarted.publish(stage(restarted, content=""), old, repo_url=REPO, commit="1" * 40)
    assert len(list(restarted.snapshot_dir(old).glob("*.c"))) == 3


def test_nested_directories_consume_entry_quota(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_entries=4)
    staged = store.new_temp_dir()
    nested = staged / "a" / "b"
    nested.mkdir(parents=True)
    (nested / "empty.c").touch()
    ref = store.ref_for(REPO, "1" * 40)
    # 根目录 + 两层目录 + 空文件 + 元数据，共 5 个条目。
    with pytest.raises(IntegrationError) as failure:
        store.publish(staged, ref, repo_url=REPO, commit="1" * 40)
    assert failure.value.code == "storage_quota_exceeded"
    assert not store.exists(ref)


def test_orphan_trees_consume_quota_and_can_be_repaired(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_entries=4)
    orphan_ref, new_ref = (store.ref_for(REPO, str(index) * 40) for index in (1, 2))
    orphan = store.snapshots / orphan_ref
    orphan.mkdir(parents=True)
    (orphan / "empty.c").touch()
    with pytest.raises(IntegrationError) as failure:
        store.publish(stage(store, content=""), new_ref, repo_url=REPO, commit="2" * 40)
    assert failure.value.code == "storage_quota_exceeded"
    assert not store.exists(new_ref)

    store.publish(stage(store, "fresh.c", ""), orphan_ref, repo_url=REPO, commit="1" * 40)
    assert store.exists(orphan_ref)
    assert not (orphan / "empty.c").exists()
    assert (orphan / "fresh.c").is_file()


def test_orphan_metadata_consumes_quota_without_double_counting_repair(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_entries=3)
    orphan_ref, new_ref = (store.ref_for(REPO, str(index) * 40) for index in (1, 2))
    store._write_metadata(orphan_ref, REPO, "1" * 40)
    with pytest.raises(IntegrationError) as failure:
        store.publish(stage(store, content=""), new_ref, repo_url=REPO, commit="2" * 40)
    assert failure.value.code == "storage_quota_exceeded"

    store.publish(stage(store, content=""), orphan_ref, repo_url=REPO, commit="1" * 40)
    assert store.exists(orphan_ref)


def test_concurrent_empty_snapshots_respect_global_entry_quota(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_bytes=None, max_total_entries=3)
    refs = [store.ref_for(REPO, str(index) * 40) for index in (1, 2)]
    ready = threading.Barrier(2)
    outcomes = []

    def publish(ref):
        staged = stage(store, content="")
        ready.wait(timeout=5)
        try:
            store.publish(staged, ref, repo_url=REPO, commit="1" * 40)
            outcomes.append("ok")
        except IntegrationError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=publish, args=(ref,)) for ref in refs]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=5)
    assert all(not thread.is_alive() for thread in threads)
    assert sorted(outcomes) == ["ok", "storage_quota_exceeded"]
    assert sum(store.exists(ref) for ref in refs) == 1


def test_read_lines_checks_cancellation_during_binary_scan(tmp_path):
    store = SnapshotStore(tmp_path / "storage")
    path = tmp_path / "long.c"
    path.write_bytes(b"x" * 30_000)

    class CancelDuringRead(threading.Event):
        checks = 0

        def is_set(self):
            self.checks += 1
            if self.checks == 3:
                self.set()
            return super().is_set()

    with pytest.raises(IntegrationError) as failure:
        store.read_lines(path, 1, 1, max_lines=10, cancel_event=CancelDuringRead())
    assert failure.value.code == "repository_cancelled"


def test_cancelled_quota_scan_cannot_publish_a_snapshot(tmp_path, monkeypatch):
    from pathlib import Path

    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    staged = stage(store)
    cancel = threading.Event()
    original_stat = Path.stat

    def cancel_after_file_stat(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path == staged / "a.c":
            cancel.set()
        return result

    monkeypatch.setattr(Path, "stat", cancel_after_file_stat)
    with pytest.raises(IntegrationError) as failure:
        store.publish(staged, ref, repo_url=REPO, commit="1" * 40, cancel_event=cancel)
    assert failure.value.code == "repository_cancelled"
    assert not store.exists(ref)
    assert not (store.refs / f"{ref}.json").exists()


@pytest.mark.parametrize("failed_step", ["read", "stat", "preview", "walk"])
def test_scan_io_errors_are_execution_failures(tmp_path, monkeypatch, failed_step):
    from pathlib import Path

    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    store.publish(stage(store, "header", "#define VALUE 1\n"), ref, repo_url=REPO, commit="1" * 40)
    root = store.snapshot_dir(ref)
    source = root / "header"

    def fail_path_operation(original):
        def operation(path, *args, **kwargs):
            if path == source:
                raise PermissionError("synthetic unreadable source")
            return original(path, *args, **kwargs)

        return operation

    if failed_step == "stat":
        for name in ("stat", "lstat"):
            monkeypatch.setattr(Path, name, fail_path_operation(getattr(Path, name)))
    elif failed_step == "walk":
        original_scandir = os.scandir

        def scandir(path):
            if Path(path) == root:
                raise PermissionError("synthetic unreadable directory")
            return original_scandir(path)

        monkeypatch.setattr(os, "scandir", scandir)
    else:
        name = "read_bytes" if failed_step == "read" else "open"
        monkeypatch.setattr(Path, name, fail_path_operation(getattr(Path, name)))
    with pytest.raises(IntegrationError) as failure:
        list(store.iter_files(ref))
    assert failure.value.code == "file_unreadable"
    assert isinstance(failure.value.__cause__, PermissionError)


@pytest.mark.parametrize("content", [b"int f;\x00binary", b"int caf\xff;"])
def test_scan_still_reports_confirmed_non_text_files(tmp_path, content):
    store = SnapshotStore(tmp_path / "storage")
    ref = store.ref_for(REPO, "1" * 40)
    staged = store.new_temp_dir()
    (staged / "a.c").write_bytes(content)
    store.publish(staged, ref, repo_url=REPO, commit="1" * 40)
    report = ScanReport()
    assert list(store.iter_files(ref, report=report)) == []
    assert report.binary == ["a.c"]
    assert report.scanned == 0
