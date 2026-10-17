"""#4 代码证据工具：搜索、按行读取与符号定义/调用查询。

所有工具只接受准备层发放的不透明 `snapshot_ref`，不接收提交、标签
或版本参数。`RepositoryResult.matches` 为空表示“未找到”，读取失败、
路径越界等执行问题抛 `IntegrationError`，两者不互相替代。
"""

import asyncio

from app.repository.locate import find_symbol, locate_function, search_code
from app.repository.store import SnapshotStore
from app.schemas.models import CodeLocation, RepositoryResult
from app.schemas.ports import IntegrationError


class RepositoryTools:
    def __init__(
        self,
        store: SnapshotStore,
        *,
        search_limit: int = 20,
        symbol_limit: int = 20,
        max_read_lines: int = 400,
        max_file_bytes: int = 2 * 1024 * 1024,
    ) -> None:
        self.store = store
        self.search_limit = search_limit
        self.symbol_limit = symbol_limit
        self.max_read_lines = max_read_lines
        self.max_file_bytes = max_file_bytes

    async def locate_function(self, snapshot_ref: str, func: str) -> CodeLocation:
        return await asyncio.to_thread(self._locate_function, snapshot_ref, func)

    async def search_code(self, snapshot_ref: str, query: str) -> RepositoryResult:
        return await asyncio.to_thread(self._search_code, snapshot_ref, query)

    async def read_file(
        self,
        snapshot_ref: str,
        path: str,
        start_line: int,
        end_line: int,
    ) -> RepositoryResult:
        return await asyncio.to_thread(self._read_file, snapshot_ref, path, start_line, end_line)

    async def find_symbol(self, snapshot_ref: str, symbol: str) -> RepositoryResult:
        return await asyncio.to_thread(self._find_symbol, snapshot_ref, symbol)

    def _locate_function(self, snapshot_ref: str, func: str) -> CodeLocation:
        self.store.snapshot_dir(snapshot_ref)
        return locate_function(self.store, snapshot_ref, func)

    def _search_code(self, snapshot_ref: str, query: str) -> RepositoryResult:
        self.store.snapshot_dir(snapshot_ref)
        return search_code(
            self.store,
            snapshot_ref,
            query,
            limit=self.search_limit,
            max_file_bytes=self.max_file_bytes,
        )

    def _find_symbol(self, snapshot_ref: str, symbol: str) -> RepositoryResult:
        self.store.snapshot_dir(snapshot_ref)
        return find_symbol(
            self.store,
            snapshot_ref,
            symbol,
            limit=self.symbol_limit,
            max_file_bytes=self.max_file_bytes,
        )

    def _read_file(
        self,
        snapshot_ref: str,
        path: str,
        start_line: int,
        end_line: int,
    ) -> RepositoryResult:
        if (
            not isinstance(path, str)
            or not path
            or type(start_line) is not int
            or type(end_line) is not int
            or start_line < 1
            or end_line < start_line
        ):
            raise IntegrationError("invalid_line_range", "读取区间必须是从 1 起始的递增行号。")
        relative, target = self.store.resolve_file(snapshot_ref, path)
        text = self.store.read_text(target)
        lines = text.splitlines()
        if not lines:
            raise IntegrationError("line_out_of_range", "该文件没有可读取的文本行。")
        if start_line > len(lines):
            raise IntegrationError("line_out_of_range", "起始行超出文件末尾。")
        actual_end = min(end_line, len(lines))
        if actual_end - start_line + 1 > self.max_read_lines:
            raise IntegrationError(
                "range_too_large",
                f"单次读取最多 {self.max_read_lines} 行，请缩小区间。",
            )
        content = "\n".join(lines[start_line - 1 : actual_end])
        scope = f"lines {start_line}-{actual_end} of {len(lines)} in {relative}"
        if actual_end != end_line:
            scope += f"; requested end_line {end_line} clamped to {len(lines)}"
        return RepositoryResult(
            matches=[
                CodeLocation(
                    snapshot_ref=snapshot_ref,
                    path=relative,
                    start_line=start_line,
                    end_line=actual_end,
                    content=content,
                )
            ],
            scope=scope,
        )
