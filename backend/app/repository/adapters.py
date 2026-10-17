"""#3/#4 的默认装配：准备层 + 仓库证据工具共用同一份本地快照存储。"""

from collections.abc import Iterable
from pathlib import Path

from app.repository.gitclient import GitClient, SubprocessGitClient
from app.repository.prepare import RepositoryPreparation
from app.repository.store import SnapshotStore
from app.repository.tools import RepositoryTools
from app.repository.urls import DEFAULT_ALLOWED_HOSTS, Resolver
from app.schemas.models import (
    CodeLocation,
    CourseSample,
    DetectionInput,
    RepositoryResult,
    SnapshotRequest,
)


class RepositoryAdapters:
    """同时实现 `Preparation` 与 `Repository` 协议的生产适配器。"""

    def __init__(
        self,
        storage_dir: str | Path,
        *,
        allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS,
        git: GitClient | None = None,
        resolver: Resolver | None = None,
        search_limit: int = 20,
        symbol_limit: int = 20,
        max_read_lines: int = 400,
        max_file_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.store = SnapshotStore(storage_dir)
        self.git = git or SubprocessGitClient(self.store.root / "git")
        self.tools = RepositoryTools(
            self.store,
            search_limit=search_limit,
            symbol_limit=symbol_limit,
            max_read_lines=max_read_lines,
            max_file_bytes=max_file_bytes,
        )
        self.preparation = RepositoryPreparation(
            self.store,
            self.git,
            self.tools,
            allowed_hosts=allowed_hosts,
            resolver=resolver,
        )

    async def prepare_course(self, sample: CourseSample) -> DetectionInput:
        return await self.preparation.prepare_course(sample)

    async def prepare_snapshot(self, request: SnapshotRequest) -> DetectionInput:
        return await self.preparation.prepare_snapshot(request)

    async def locate_function(self, snapshot_ref: str, func: str) -> CodeLocation:
        return await self.tools.locate_function(snapshot_ref, func)

    async def search_code(self, snapshot_ref: str, query: str) -> RepositoryResult:
        return await self.tools.search_code(snapshot_ref, query)

    async def read_file(
        self,
        snapshot_ref: str,
        path: str,
        start_line: int,
        end_line: int,
    ) -> RepositoryResult:
        return await self.tools.read_file(snapshot_ref, path, start_line, end_line)

    async def find_symbol(self, snapshot_ref: str, symbol: str) -> RepositoryResult:
        return await self.tools.find_symbol(snapshot_ref, symbol)
