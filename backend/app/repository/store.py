"""快照引用登记、文件树边界校验与文本读取。

快照引用是内容无关的不透明标识；元数据放在快照目录之外，
因此模型可读的文件树里没有提交、标签、版本或 Git 元数据。
"""

import hashlib
import json
import os
import re
import shutil
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
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


class SnapshotStore:
    """`storage/` 下的快照存储：`snapshots/<ref>/` 为文件树，`refs/<ref>.json` 为元数据。"""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.snapshots = self.root / "snapshots"
        self.refs = self.root / "refs"
        self.temp = self.root / "tmp"

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

    def publish(self, staged: Path, snapshot_ref: str, *, repo_url: str, commit: str) -> None:
        """原子发布已物化的文件树，并登记不透明引用。"""
        destination = self.snapshots / snapshot_ref
        destination.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(staged, destination)
        except OSError as exc:
            if self.exists(snapshot_ref):
                shutil.rmtree(staged, ignore_errors=True)
                return
            raise IntegrationError("snapshot_write_failed", "保存快照失败。") from exc
        self.refs.mkdir(parents=True, exist_ok=True)
        metadata = {"snapshot_ref": snapshot_ref, "repo_url": repo_url, "commit": commit}
        temporary = self.refs / f".{snapshot_ref}.{uuid.uuid4().hex}.json"
        temporary.write_text(json.dumps(metadata), encoding="utf-8")
        os.replace(temporary, self.refs / f"{snapshot_ref}.json")

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
        try:
            raw = path.read_bytes()
        except OSError as exc:
            raise IntegrationError("file_unreadable", "无法读取该文件。") from exc
        if b"\x00" in raw[:8192]:
            raise IntegrationError("file_unreadable", "该文件不是文本文件。")
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError:
            return raw.decode("latin-1")

    def iter_files(
        self,
        snapshot_ref: str,
        *,
        suffixes: frozenset[str] = CODE_SUFFIXES,
        max_bytes: int = 2 * 1024 * 1024,
    ) -> Iterator[FileEntry]:
        """按稳定顺序遍历快照内的文本文件，跳过 Git 目录、大文件与二进制文件。"""
        root = self.snapshot_dir(snapshot_ref).resolve()
        for directory, subdirectories, filenames in os.walk(root):
            subdirectories[:] = sorted(name for name in subdirectories if not name.startswith("."))
            for filename in sorted(filenames):
                if filename.startswith("."):
                    continue
                path = Path(directory) / filename
                if path.suffix.lower() not in suffixes:
                    continue
                try:
                    stat = path.stat()
                except OSError:
                    continue
                if not path.is_file() or stat.st_size > max_bytes:
                    continue
                relative = path.relative_to(root).as_posix()
                try:
                    text = self.read_text(path)
                except IntegrationError:
                    continue
                yield FileEntry(path=relative, text=text)

    def source_files(
        self, snapshot_ref: str, *, max_bytes: int = 2 * 1024 * 1024
    ) -> list[FileEntry]:
        return list(self.iter_files(snapshot_ref, suffixes=CODE_SUFFIXES, max_bytes=max_bytes))
