"""快照引用登记、文件树边界校验与文本读取。

快照引用是内容无关的不透明标识；元数据放在快照目录之外，
因此模型可读的文件树里没有提交、标签、版本或 Git 元数据。
"""

import codecs
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
from stat import S_ISREG
from typing import NoReturn

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
        ".h++",
        ".c++",
        ".inl",
        ".ipp",
        ".tcc",
        ".tpp",
        ".ii",
        ".cu",
        ".cuh",
        ".ixx",
        ".cppm",
        ".mpp",
        ".inc",
        ".m",
        ".mm",
    }
)
# 无扩展名的 C/C++ 头文件（如 `include/foo`）按预处理指令识别。
_SOURCE_DIRECTIVE = re.compile(r"^\s*#\s*(?:include|define|pragma|ifndef|if)\b", re.M)


class _NonTextFile(IntegrationError):
    """已确认的非文本内容，可从源码扫描中主动排除；读取故障不属于此类。"""

    def __init__(self, message: str) -> None:
        super().__init__("file_unreadable", message)


def _raise_read_error(error: OSError) -> NoReturn:
    raise IntegrationError("file_unreadable", "无法读取该文件。") from error


def check_scan_cancelled(cancel_event: threading.Event | None) -> None:
    if cancel_event is not None and cancel_event.is_set():
        raise IntegrationError("repository_cancelled", "代码快照扫描已取消。")


@dataclass(frozen=True)
class FileEntry:
    path: str
    text: str
    size: int


@dataclass
class ScanReport:
    """扫描范围的可核对记录：被排除的文件会进入 `oversized`/`binary`/`excluded`。"""

    scanned: int = 0
    oversized: list[str] = field(default_factory=list)
    binary: list[str] = field(default_factory=list)
    excluded: int = 0

    def note(self) -> str:
        parts = []
        if self.oversized:
            parts.append(f"skipped {len(self.oversized)} oversized file(s)")
        if self.binary:
            parts.append(f"skipped {len(self.binary)} non-text file(s)")
        if self.excluded:
            parts.append(f"skipped {self.excluded} file(s) with other extensions")
        return "; ".join(parts)


class SnapshotStore:
    """`storage/` 下的快照存储：`snapshots/<ref>/` 为文件树，`refs/<ref>.json` 为元数据。"""

    def __init__(
        self,
        root: str | Path,
        *,
        max_total_bytes: int | None = 2 * 1024**3,
        max_total_entries: int | None = 200_000,
    ) -> None:
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.refs = self.root / "refs"
        self.temp = self.root / "tmp"
        self.max_total_bytes = max_total_bytes
        self.max_total_entries = max_total_entries
        self._publish_locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        # 引用没有到期/释放协议，已发布快照可能仍被排队或运行中的任务使用。
        # 配额不足时拒绝新发布，不通过删除已发放的证据来腾出空间。
        self._quota_lock = threading.Lock()

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

    def publish(
        self,
        staged: Path,
        snapshot_ref: str,
        *,
        repo_url: str,
        commit: str,
        cancel_event: threading.Event | None = None,
    ) -> None:
        """按引用串行发布文件树；元数据先写，重试可修复孤儿目录。"""
        with self._publish_lock(snapshot_ref):
            check_scan_cancelled(cancel_event)
            if self.exists(snapshot_ref):
                shutil.rmtree(staged, ignore_errors=True)
                return
            destination = self.snapshots / snapshot_ref
            destination.parent.mkdir(parents=True, exist_ok=True)
            size, entries = _directory_usage(staged, cancel_event=cancel_event)
            # 配额检查、登记和可见性切换共用一把锁，不重复统计在途预留。
            with self._quota_lock:
                check_scan_cancelled(cancel_event)
                # 无元数据的目录是中断残留；清理也与其他发布的配额扫描串行。
                if destination.exists():
                    shutil.rmtree(destination)
                (self.refs / f"{snapshot_ref}.json").unlink(missing_ok=True)
                used_bytes, used_entries = self._snapshot_usage(cancel_event=cancel_event)
                if (
                    self.max_total_bytes is not None and used_bytes + size > self.max_total_bytes
                ) or (
                    self.max_total_entries is not None
                    and used_entries + entries + 1 > self.max_total_entries
                ):
                    raise IntegrationError("storage_quota_exceeded", "快照存储配额已用尽。")
                self._write_metadata(snapshot_ref, repo_url, commit)
                try:
                    os.replace(staged, destination)
                except OSError as exc:
                    (self.refs / f"{snapshot_ref}.json").unlink(missing_ok=True)
                    raise IntegrationError("snapshot_write_failed", "保存快照失败。") from exc

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

    def _snapshot_usage(self, *, cancel_event: threading.Event | None = None) -> tuple[int, int]:
        """扫描落盘状态，包含孤儿树；元数据占用条目，源码计逻辑字节。"""
        size, tree_entries = _directory_usage(self.snapshots, cancel_event=cancel_event)
        _, ref_entries = _directory_usage(self.refs, cancel_event=cancel_event)
        # 两个固定容器目录不计入每份快照的条目配额。
        return size, max(0, tree_entries - 1) + max(0, ref_entries - 1)

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
            return raw.decode("utf-8").replace("\r\n", "\n")
        except UnicodeDecodeError as exc:
            raise _NonTextFile("该文件不是 UTF-8 文本。") from exc

    def _read_bytes(self, path: Path) -> bytes:
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
        if b"\x00" in raw:
            raise _NonTextFile("该文件不是文本文件。")
        return raw

    def read_lines(
        self,
        path: Path,
        start_line: int,
        end_line: int,
        *,
        max_lines: int,
        max_bytes: int = 2 * 1024 * 1024,
        cancel_event: threading.Event | None = None,
    ) -> tuple[list[str], int, bool]:
        """只读取请求的行区间；返回 (行内容, 实际结束行, 是否提前遇到文件末尾)。"""
        check_scan_cancelled(cancel_event)
        try:
            if path.stat().st_size > max_bytes:
                raise IntegrationError("file_too_large", f"单文件读取上限为 {max_bytes} 字节。")
            raw = path.open("rb")
        except OSError as exc:
            raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
        with raw:
            try:
                while chunk := raw.read(8192):
                    check_scan_cancelled(cancel_event)
                    if b"\x00" in chunk:
                        raise _NonTextFile("该文件不是文本文件。")
            except OSError as exc:
                raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
            raw.seek(0)
            stream = io.TextIOWrapper(raw, encoding="utf-8", newline="\n")
            try:
                for _ in range(start_line - 1):
                    check_scan_cancelled(cancel_event)
                    if not stream.readline():
                        raise IntegrationError("line_out_of_range", "起始行超出文件末尾。")
                wanted = end_line - start_line + 1
                lines: list[str] = []
                for _ in range(min(wanted, max_lines + 1)):
                    check_scan_cancelled(cancel_event)
                    line = stream.readline()
                    if not line:
                        break
                    lines.append(line.removesuffix("\r\n").removesuffix("\n"))
            except UnicodeDecodeError as exc:
                raise _NonTextFile("该文件不是 UTF-8 文本。") from exc
        check_scan_cancelled(cancel_event)
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
        cancel_event: threading.Event | None = None,
    ) -> Iterator[FileEntry]:
        """遍历快照内的文本源码；跳过 `.git`，并把超限/非文本文件记入报告。"""
        check_scan_cancelled(cancel_event)
        root = self.snapshot_dir(snapshot_ref).resolve()
        for directory, subdirectories, filenames in os.walk(root, onerror=_raise_read_error):
            check_scan_cancelled(cancel_event)
            subdirectories[:] = sorted(
                name
                for name in subdirectories
                if name.casefold() != ".git" and not (Path(directory) / name).is_symlink()
            )
            for filename in sorted(filenames):
                check_scan_cancelled(cancel_event)
                if filename.casefold() == ".git":
                    continue
                path = Path(directory) / filename
                relative = path.relative_to(root).as_posix()
                try:
                    stat = path.lstat()
                except OSError as exc:
                    _raise_read_error(exc)
                if not S_ISREG(stat.st_mode):
                    continue
                if stat.st_size > max_bytes:
                    if report is not None:
                        report.oversized.append(relative)
                    continue
                suffix = path.suffix.lower()
                if suffix not in suffixes and not (suffix == "" and _looks_like_source(path)):
                    if report is not None:
                        report.excluded += 1
                    continue
                try:
                    text = self.read_text(path)
                except _NonTextFile:
                    if report is not None:
                        report.binary.append(relative)
                    continue
                if report is not None:
                    report.scanned += 1
                check_scan_cancelled(cancel_event)
                yield FileEntry(path=relative, text=text, size=stat.st_size)

    def source_files(
        self, snapshot_ref: str, *, max_bytes: int = 2 * 1024 * 1024
    ) -> list[FileEntry]:
        return list(self.iter_files(snapshot_ref, max_bytes=max_bytes))


def _looks_like_source(path: Path, preview_bytes: int = 4096) -> bool:
    """无扩展名文件是否像 C/C++ 头文件（含预处理指令）。"""
    try:
        with path.open("rb") as stream:
            head = stream.read(preview_bytes)
    except OSError as exc:
        _raise_read_error(exc)
    if b"\x00" in head:
        return False
    try:
        decoder = codecs.getincrementaldecoder("utf-8")()
        text = decoder.decode(head, final=len(head) < preview_bytes)
    except UnicodeDecodeError:
        return False
    return bool(_SOURCE_DIRECTIVE.search(text))


def _directory_usage(path: Path, *, cancel_event: threading.Event | None = None) -> tuple[int, int]:
    """返回逻辑字节与文件系统条目数，空文件、目录和根目录也占条目。"""
    check_scan_cancelled(cancel_event)
    if not path.exists():
        return 0, 0
    total = 0
    entries = 1
    for file in path.rglob("*"):
        check_scan_cancelled(cancel_event)
        file_stat = file.stat()
        entries += 1
        if S_ISREG(file_stat.st_mode):
            total += file_stat.st_size
    check_scan_cancelled(cancel_event)
    return total, entries
