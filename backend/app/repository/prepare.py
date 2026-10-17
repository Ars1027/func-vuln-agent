"""#3 样本准备：按课程 `target` 或显式 `revision` 物化单版本快照。

版本选择只发生在这一层：`target=1` 取修复提交的父提交，`target=0` 取
修复提交；Web 传入的 `revision` 直接决定选版。返回的 `DetectionInput`
只保留 `idx/func/snapshot_ref`，不携带标签、提交、diff 或另一版本。
"""

import asyncio
import logging
import shutil
from collections.abc import Iterable

from app.diagnostics import log_failure
from app.repository.gitclient import GitClient
from app.repository.store import SnapshotStore
from app.repository.tools import RepositoryTools
from app.repository.urls import (
    DEFAULT_ALLOWED_HOSTS,
    CommitTarget,
    Resolver,
    parse_commit_url,
    verify_public_host,
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
    ) -> None:
        self.store = store
        self.git = git
        self.tools = tools
        self.allowed_hosts = tuple(allowed_hosts)
        self.resolver = resolver
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
        await asyncio.to_thread(verify_public_host, target.host, self.resolver)
        snapshot_ref = await self._snapshot_ref(target, revision)
        # 函数与快照一致性：定位失败即准备失败，不把不一致的样本交给 Agent。
        await self.tools.locate_function(snapshot_ref, func)
        return DetectionInput(idx=idx, func=func, snapshot_ref=snapshot_ref)

    async def _snapshot_ref(self, target: CommitTarget, revision: str) -> str:
        key = f"{target.repo_url}#{revision}"
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            try:
                return await asyncio.to_thread(self._ensure_snapshot, target, revision)
            except IntegrationError:
                raise
            except Exception as exc:
                log_failure(logger, "snapshot_preparation", exc)
                raise IntegrationError("snapshot_prepare_failed", "准备代码快照失败。") from exc

    def _ensure_snapshot(self, target: CommitTarget, revision: str) -> str:
        handle = self.git.fetch(target.repo_url, target.commit)
        fixed_commit = self.git.resolve(handle, target.commit)
        selected = fixed_commit
        if revision == "parent":
            parents = self.git.parents(handle, fixed_commit)
            if not parents:
                raise IntegrationError(
                    "parent_unavailable", "该修复提交没有父提交，无法获取修复前版本。"
                )
            if len(parents) > 1:
                raise IntegrationError(
                    "multi_parent_commit", "该修复提交有多个父提交，无法确定修复前版本。"
                )
            selected = parents[0]
            self.git.ensure(handle, selected)
        snapshot_ref = self.store.ref_for(target.repo_url, selected)
        if self.store.exists(snapshot_ref):
            return snapshot_ref
        self._materialize(handle, snapshot_ref, selected, target)
        return snapshot_ref

    def _materialize(
        self,
        handle: object,
        snapshot_ref: str,
        commit: str,
        target: CommitTarget,
    ) -> None:
        staged = self.store.new_temp_dir()
        try:
            count = self.git.export(handle, commit, staged)
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
