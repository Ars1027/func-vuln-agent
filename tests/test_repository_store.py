"""快照存储：发布事务、并发、配额、临时清理与文本校验。"""

import os
import threading

import pytest
from app.repository.store import SnapshotStore
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

    store = SnapshotStore(tmp_path / "storage", max_total_bytes=20)
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
    original_stat = Path.stat

    def stop_after_first_file(path, *args, **kwargs):
        result = original_stat(path, *args, **kwargs)
        if path.suffix == ".txt":
            visited.add(path.name)
            cancel.set()
        return result

    monkeypatch.setattr(Path, "stat", stop_after_first_file)
    with pytest.raises(IntegrationError) as failure:
        list(store.iter_files(ref, cancel_event=cancel))
    assert failure.value.code == "repository_cancelled"
    assert visited == {"a.txt"}
