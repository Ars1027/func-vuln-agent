"""#3 样本准备：按课程 `target` 或显式 `revision` 物化单版本快照。

版本选择只发生在这一层：`target=1` 取修复提交的父提交，`target=0` 取
修复提交；Web 传入的 `revision` 直接决定选版。返回的 `DetectionInput`
只保留 `idx/func/snapshot_ref`，不携带标签、提交、diff 或另一版本。

已缓存的快照只使用本地镜像与文件树，不要求 DNS；只有确实需要联网拉取
时才校验主机，并把校验得到的公网地址固定给 Git。
"""

import asyncio
import logging
import shutil
import threading
from collections.abc import Iterable

from app.diagnostics import log_failure
from app.repository.gitclient import GitClient
from app.repository.store import SnapshotStore
from app.repository.tools import RepositoryTools
from app.repository.urls import (
    DEFAULT_ALLOWED_HOSTS,
    DEFAULT_DNS_TIMEOUT_SECONDS,
    CommitTarget,
    Resolver,
    parse_commit_url,
    verify_public_host_async,
)
from app.schemas.models import CourseSample, DetectionInput, SnapshotRequest
from app.schemas.ports import IntegrationError

logger = logging.getLogger(__name__)


class RepositoryPreparation:
    def __init__(
        self,
        store: SnapshotStore,
        git: GitClient,
        tools: RepositoryTools,
        *,
        allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS,
        resolver: Resolver | None = None,
        dns_timeout_seconds: float = DEFAULT_DNS_TIMEOUT_SECONDS,
    ) -> None:
        self.store = store
        self.git = git
        self.tools = tools
        self.allowed_hosts = tuple(allowed_hosts)
        self.resolver = resolver
        self.dns_timeout_seconds = dns_timeout_seconds
        self._locks: dict[str, asyncio.Lock] = {}

    async def prepare_course(self, sample: CourseSample) -> DetectionInput:
        revision = "parent" if sample.target == 1 else "commit"
        return await self._prepare(
            idx=sample.idx,
            func=sample.func,
            commit_url=sample.commit_url,
            revision=revision,
        )

    async def prepare_snapshot(self, request: SnapshotRequest) -> DetectionInput:
        return await self._prepare(
            idx=request.idx,
            func=request.func,
            commit_url=request.commit_url,
            revision=request.revision,
        )

    async def _prepare(
        self,
        *,
        idx: int | str,
        func: str,
        commit_url: str,
        revision: str,
    ) -> DetectionInput:
        target = parse_commit_url(commit_url, self.allowed_hosts)
        cancel = threading.Event()
        try:
            snapshot_ref = await self._snapshot_ref(target, revision, cancel)
            # 函数与快照一致性：定位失败即准备失败，不把不一致的样本交给 Agent。
            await self.tools.locate_function(snapshot_ref, func)
        except asyncio.CancelledError:
            cancel.set()
            raise
        return DetectionInput(idx=idx, func=func, snapshot_ref=snapshot_ref)

    async def _snapshot_ref(
        self,
        target: CommitTarget,
        revision: str,
        cancel: threading.Event,
    ) -> str:
        key = f"{target.repo_url}#{revision}"
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                cached = await asyncio.to_thread(self._local_snapshot, target, revision)
                if cached is not None:
                    return cached
                addresses = await verify_public_host_async(
                    target.host, self.resolver, timeout_seconds=self.dns_timeout_seconds
                )
                return await asyncio.to_thread(
                    self._network_snapshot, target, revision, addresses, cancel
                )
            except IntegrationError:
                raise
            except Exception as exc:
                log_failure(logger, "snapshot_preparation", exc)
                raise IntegrationError("snapshot_prepare_failed", "准备代码快照失败。") from exc

    def _local_snapshot(self, target: CommitTarget, revision: str) -> str | None:
        """只用本地镜像与已发布快照；缺少对象时返回 None 交给联网路径。"""
        if revision == "commit" and len(target.commit) == 40:
            snapshot_ref = self.store.ref_for(target.repo_url, target.commit)
            if self.store.exists(snapshot_ref):
                return snapshot_ref
        handle = self.git.local_mirror(target.repo_url)
        if handle is None:
            return None
        try:
            fixed = self.git.resolve(handle, target.commit)
        except IntegrationError:
            return None
        selected = self._select_commit(handle, fixed, revision)
        if selected is None:
            return None
        snapshot_ref = self.store.ref_for(target.repo_url, selected)
        if self.store.exists(snapshot_ref):
            return snapshot_ref
        if not self.git.has_commit(handle, selected):
            return None
        self._publish(handle, snapshot_ref, selected, target)
        return snapshot_ref

    def _select_commit(self, handle: object, fixed: str, revision: str) -> str | None:
        if revision == "commit":
            return fixed
        parents = self.git.parents(handle, fixed)
        if not parents:
            raise IntegrationError(
                "parent_unavailable", "该修复提交没有父提交，无法获取修复前版本。"
            )
        if len(parents) > 1:
            raise IntegrationError(
                "multi_parent_commit", "该修复提交有多个父提交，无法确定修复前版本。"
            )
        return parents[0]

    def _network_snapshot(
        self,
        target: CommitTarget,
        revision: str,
        addresses: list[str],
        cancel: threading.Event,
    ) -> str:
        options = self.git.pinned_options(target.host, addresses)
        handle = self.git.fetch(
            target.repo_url, target.commit, options=options, cancel_event=cancel
        )
        fixed = self.git.resolve(handle, target.commit)
        selected = self._select_commit(handle, fixed, revision)
        if selected is None:  # pragma: no cover - 防御性分支，_select_commit 不会返回 None
            raise IntegrationError("snapshot_prepare_failed", "无法确定快照版本。")
        self.git.ensure(handle, selected, options=options, cancel_event=cancel)
        snapshot_ref = self.store.ref_for(target.repo_url, selected)
        if self.store.exists(snapshot_ref):
            return snapshot_ref
        self._publish(handle, snapshot_ref, selected, target, cancel=cancel)
        return snapshot_ref

    def _publish(
        self,
        handle: object,
        snapshot_ref: str,
        commit: str,
        target: CommitTarget,
        *,
        cancel: threading.Event | None = None,
    ) -> None:
        staged = self.store.new_temp_dir()
        try:
            count = self.git.export(handle, commit, staged, cancel_event=cancel)
            if count <= 0:
                raise IntegrationError("empty_snapshot", "指定版本的快照不包含可读取文件。")
            self.store.publish(staged, snapshot_ref, repo_url=target.repo_url, commit=commit)
        except IntegrationError:
            raise
        except OSError as exc:
            logger.warning("snapshot materialization failed: %s", type(exc).__name__)
            raise IntegrationError("snapshot_write_failed", "保存快照失败。") from exc
        finally:
            if staged.exists():
                shutil.rmtree(staged, ignore_errors=True)
