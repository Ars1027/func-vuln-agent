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


def test_storage_quota_evicts_oldest_snapshot(tmp_path):
    store = SnapshotStore(tmp_path / "storage", max_total_bytes=12)
    old = store.ref_for(REPO, "1" * 40)
    new = store.ref_for(REPO, "2" * 40)
    store.publish(stage(store, "a.c", "int aaaa;\n"), old, repo_url=REPO, commit="1" * 40)
    os.utime(store.refs / f"{old}.json", (1, 1))
    store.publish(stage(store, "b.c", "int bbbb;\n"), new, repo_url=REPO, commit="2" * 40)

    assert store.exists(new)
    assert not store.exists(old)


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
