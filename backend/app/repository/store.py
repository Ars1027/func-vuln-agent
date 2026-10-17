"""快照引用登记、文件树边界校验与文本读取。

快照引用是内容无关的不透明标识；元数据放在快照目录之外，
因此模型可读的文件树里没有提交、标签、版本或 Git 元数据。
"""

import hashlib
import io
import json
import os
import re
import shutil
import threading
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from app.schemas.paths import normalize_snapshot_path
from app.schemas.ports import IntegrationError

SNAPSHOT_REF = re.compile(r"^snap-[0-9a-f]{16}$")
CODE_SUFFIXES = frozenset(
    {
        ".c",
        ".h",
        ".cc",
        ".cpp",
        ".cxx",
        ".hh",
        ".hpp",
        ".hxx",
        ".inl",
        ".ipp",
        ".inc",
        ".m",
        ".mm",
    }
)


@dataclass(frozen=True)
class FileEntry:
    path: str
    text: str


@dataclass
class ScanReport:
    """扫描范围的可核对记录：被排除的文件会进入 `oversized`/`binary`。"""

    scanned: int = 0
    oversized: list[str] = field(default_factory=list)
    binary: list[str] = field(default_factory=list)

    def note(self) -> str:
        parts = []
        if self.oversized:
            parts.append(f"skipped {len(self.oversized)} oversized file(s)")
        if self.binary:
            parts.append(f"skipped {len(self.binary)} non-text file(s)")
        return "; ".join(parts)


class SnapshotStore:
    """`storage/` 下的快照存储：`snapshots/<ref>/` 为文件树，`refs/<ref>.json` 为元数据。"""

    def __init__(self, root: str | Path, *, max_total_bytes: int | None = 2 * 1024**3) -> None:
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.refs = self.root / "refs"
        self.temp = self.root / "tmp"
        self.max_total_bytes = max_total_bytes
        self._publish_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

    def ref_for(self, repo_url: str, commit: str) -> str:
        digest = hashlib.sha256(f"{repo_url}\n{commit}".encode()).hexdigest()[:16]
        return f"snap-{digest}"

    def exists(self, snapshot_ref: str) -> bool:
        if not SNAPSHOT_REF.match(snapshot_ref):
            return False
        return (self.snapshots / snapshot_ref).is_dir() and (
            self.refs / f"{snapshot_ref}.json"
        ).is_file()

    def snapshot_dir(self, snapshot_ref: str) -> Path:
        if not SNAPSHOT_REF.match(snapshot_ref):
            raise IntegrationError("snapshot_not_found", "快照引用无效或不属于当前服务。")
        if not self.exists(snapshot_ref):
            raise IntegrationError("snapshot_not_found", "快照引用无效或不属于当前服务。")
        return self.snapshots / snapshot_ref

    def metadata(self, snapshot_ref: str) -> dict:
        self.snapshot_dir(snapshot_ref)
        return json.loads((self.refs / f"{snapshot_ref}.json").read_text(encoding="utf-8"))

    def new_temp_dir(self) -> Path:
        self.temp.mkdir(parents=True, exist_ok=True)
        path = self.temp / uuid.uuid4().hex
        path.mkdir()
        return path

    def cleanup_temp(self) -> None:
        """进程启动时回收上次中断遗留的暂存目录（未发布的暂存内容不可用）。"""
        if not self.temp.is_dir():
            return
        for path in self.temp.iterdir():
            try:
                if path.is_dir():
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    path.unlink(missing_ok=True)
            except OSError:
                continue

    def publish(self, staged: Path, snapshot_ref: str, *, repo_url: str, commit: str) -> None:
        """按引用串行发布文件树；元数据先写，重试可修复孤儿目录。"""
        with self._publish_lock(snapshot_ref):
            if self.exists(snapshot_ref):
                shutil.rmtree(staged, ignore_errors=True)
                return
            destination = self.snapshots / snapshot_ref
            destination.parent.mkdir(parents=True, exist_ok=True)
            # 只有元数据存在时该目录才可用，因此无元数据的目录是上次中断的残留。
            if destination.exists():
                shutil.rmtree(destination, ignore_errors=True)
            self._write_metadata(snapshot_ref, repo_url, commit)
            try:
                os.replace(staged, destination)
            except OSError as exc:
                raise IntegrationError("snapshot_write_failed", "保存快照失败。") from exc
            self._enforce_quota(keep=snapshot_ref)

    def _publish_lock(self, snapshot_ref: str) -> threading.Lock:
        with self._locks_guard:
            return self._publish_locks.setdefault(snapshot_ref, threading.Lock())

    def _write_metadata(self, snapshot_ref: str, repo_url: str, commit: str) -> None:
        self.refs.mkdir(parents=True, exist_ok=True)
        metadata = {"snapshot_ref": snapshot_ref, "repo_url": repo_url, "commit": commit}
        temporary = self.refs / f".{snapshot_ref}.{uuid.uuid4().hex}.json"
        try:
            temporary.write_text(json.dumps(metadata), encoding="utf-8")
            os.replace(temporary, self.refs / f"{snapshot_ref}.json")
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise IntegrationError("snapshot_write_failed", "保存快照失败。") from exc

    def _enforce_quota(self, *, keep: str) -> None:
        if self.max_total_bytes is None or not self.refs.is_dir():
            return
        entries = sorted(
            (path for path in self.refs.glob("snap-*.json")),
            key=lambda path: path.stat().st_mtime,
        )
        total = sum(_directory_size(self.snapshots / path.stem) for path in entries)
        for ref_file in entries:
            if total <= self.max_total_bytes:
                break
            snapshot_ref = ref_file.stem
            if snapshot_ref == keep:
                continue
            tree = self.snapshots / snapshot_ref
            size = _directory_size(tree)
            shutil.rmtree(tree, ignore_errors=True)
            ref_file.unlink(missing_ok=True)
            total -= size
        if total > self.max_total_bytes:
            raise IntegrationError("storage_quota_exceeded", "快照存储配额已用尽。")

    def resolve_file(self, snapshot_ref: str, path: str) -> tuple[str, Path]:
        """返回规范化相对路径与磁盘路径；解析符号链接后仍须位于快照内。"""
        try:
            relative = normalize_snapshot_path(path)
        except ValueError as exc:
            raise IntegrationError("invalid_path", "路径必须是快照内的相对路径。") from exc
        root = self.snapshot_dir(snapshot_ref).resolve()
        candidate = (root / relative).resolve()
        if not candidate.is_relative_to(root):
            raise IntegrationError("path_escape", "路径超出当前快照范围。")
        if not candidate.is_file():
            raise IntegrationError("file_not_found", "当前快照中不存在该文件。")
        return relative, candidate

    def read_text(self, path: Path) -> str:
        raw = self._read_bytes(path)
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise IntegrationError("file_unreadable", "该文件不是 UTF-8 文本。") from exc

    def _read_bytes(self, path: Path) -> bytes:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
        if b"\x00" in raw[:8192]:
            raise IntegrationError("file_unreadable", "该文件不是文本文件。")
        return raw

    def read_lines(
        self,
        path: Path,
        start_line: int,
        end_line: int,
        *,
        max_lines: int,
    ) -> tuple[list[str], int, bool]:
        """只读取请求的行区间；返回 (行内容, 实际结束行, 是否提前遇到文件末尾)。"""
        try:
            raw = path.open("rb")
        except OSError as exc:
            raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
        with raw:
            try:
                head = raw.read(8192)
            except OSError as exc:
                raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
            if b"\x00" in head:
                raise IntegrationError("file_unreadable", "该文件不是文本文件。")
            raw.seek(0)
            stream = io.TextIOWrapper(raw, encoding="utf-8")
            try:
                for _ in range(start_line - 1):
                    if not stream.readline():
                        raise IntegrationError("line_out_of_range", "起始行超出文件末尾。")
                wanted = end_line - start_line + 1
                lines: list[str] = []
                for _ in range(min(wanted, max_lines + 1)):
                    line = stream.readline()
                    if not line:
                        break
                    lines.append(line.rstrip("\r\n"))
            except UnicodeDecodeError as exc:
                raise IntegrationError("file_unreadable", "该文件不是 UTF-8 文本。") from exc
        if not lines:
            raise IntegrationError("line_out_of_range", "起始行超出文件末尾。")
        if len(lines) > max_lines:
            raise IntegrationError("range_too_large", f"单次读取最多 {max_lines} 行，请缩小区间。")
        return lines, start_line + len(lines) - 1, len(lines) < end_line - start_line + 1

    def iter_files(
        self,
        snapshot_ref: str,
        *,
        suffixes: frozenset[str] = CODE_SUFFIXES,
        max_bytes: int = 2 * 1024 * 1024,
        report: ScanReport | None = None,
    ) -> Iterator[FileEntry]:
        """遍历快照内的文本源码；跳过 `.git`，并把超限/非文本文件记入报告。"""
        root = self.snapshot_dir(snapshot_ref).resolve()
        for directory, subdirectories, filenames in os.walk(root):
            subdirectories[:] = sorted(
                name
                for name in subdirectories
                if name.casefold() != ".git" and not (Path(directory) / name).is_symlink()
            )
            for filename in sorted(filenames):
                if filename.casefold() == ".git":
                    continue
                path = Path(directory) / filename
                if path.suffix.lower() not in suffixes:
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if not path.is_file() or path.is_symlink():
                    continue
                if stat.st_size > max_bytes:
                    if report is not None:
                        report.oversized.append(relative)
                    continue
                try:
                    text = self.read_text(path)
                except IntegrationError:
                    if report is not None:
                        report.binary.append(relative)
                    continue
                if report is not None:
                    report.scanned += 1
                yield FileEntry(path=relative, text=text)

    def source_files(
        self, snapshot_ref: str, *, max_bytes: int = 2 * 1024 * 1024
    ) -> list[FileEntry]:
        return list(self.iter_files(snapshot_ref, max_bytes=max_bytes))


def _directory_size(path: Path) -> int:
    total = 0
    for file in path.rglob("*"):
        try:
            if file.is_file():
                total += file.stat().st_size
        except OSError:
            continue
    return total
