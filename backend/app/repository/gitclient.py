"""只读 Git 镜像缓存：拉取指定提交并导出为不含 `.git` 的文件树。

不 checkout 工作区、不导出历史，也不在快照目录内保留 Git 元数据。
所有命令禁用协议跳转与 HTTP 重定向，只允许 https 传输；准备层解析出的
公网地址通过 `http.curloptResolve` 固定给 Git，避免二次解析造成重绑定。
"""

import hashlib
import logging
import os
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from app.schemas.ports import IntegrationError

logger = logging.getLogger(__name__)

# 只读操作需要的安全选项：禁止重定向、禁止非 https 传输、不执行凭据助手与钩子。
_SAFE_OPTIONS = (
    "-c",
    "http.followRedirects=false",
    "-c",
    "protocol.allow=never",
    "-c",
    "protocol.https.allow=always",
    "-c",
    "credential.helper=",
    "-c",
    "core.askPass=",
    "-c",
    "core.hooksPath=",
    "-c",
    "advice.detachedHead=false",
)
_SCRUBBED_ENV = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_INDEX_FILE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_ASKPASS",
    "GIT_CONFIG",
    "GIT_CONFIG_GLOBAL",
    "GIT_CONFIG_SYSTEM",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_COUNT",
    "GIT_CONFIG_PARAMETERS",
)
_SCRUBBED_ENV_PREFIXES = ("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")
_VERSION = re.compile(r"(\d+)\.(\d+)")
_MIN_PINNED_GIT = (2, 31)


class GitClient(Protocol):
    """准备层依赖的最小 Git 能力；`handle` 为后端自有句柄。"""

    def local_mirror(self, repo_url: str) -> Any | None: ...

    def has_commit(self, handle: Any, commit: str) -> bool: ...

    def pinned_options(self, host: str, addresses: list[str]) -> tuple[str, ...]: ...

    def fetch(
        self,
        repo_url: str,
        commit: str,
        *,
        options: tuple[str, ...] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Any: ...

    def resolve(self, handle: Any, commit: str) -> str: ...

    def parents(self, handle: Any, commit: str) -> list[str]: ...

    def ensure(
        self,
        handle: Any,
        commit: str,
        *,
        options: tuple[str, ...] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None: ...

    def export(
        self,
        handle: Any,
        commit: str,
        destination: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> int: ...


@dataclass(frozen=True)
class _CommandResult:
    """子进程执行结果，避免依赖 `CompletedProcess` 构造函数。"""

    args: list[str]
    returncode: int
    stdout: str | bytes
    stderr: str | bytes


class _GitFailure(IntegrationError):
    """保留 stderr 供同一次操作内部诊断。"""

    def __init__(self, code: str, message: str, stderr: str = "") -> None:
        super().__init__(code, message)
        self.stderr = stderr


class SubprocessGitClient:
    """基于系统 `git` 的镜像缓存，一次物化一个提交。"""

    def __init__(
        self,
        mirror_root: str | Path,
        *,
        executable: str | None = None,
        timeout_seconds: float = 300,
        max_fetch_depth: int = 200,
        max_files: int = 200_000,
        max_bytes: int = 256 * 1024 * 1024,
        max_total_bytes: int | None = 2 * 1024 * 1024 * 1024,
        allow_local_transport: bool = False,
    ) -> None:
        self.mirror_root = Path(mirror_root)
        self._executable = executable
        self.timeout_seconds = timeout_seconds
        self.max_fetch_depth = max(1, max_fetch_depth)
        self.max_files = max_files
        self.max_bytes = max_bytes
        self.max_total_bytes = max_total_bytes
        # 仅测试用：允许 file:// 与本地路径（生产环境保持 False）。
        self.allow_local_transport = allow_local_transport
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._version: tuple[int, int] | None = None

    # 每个镜像目录一把线程锁：并发的异步样本会在线程池里同时访问。
    def _lock_for(self, mirror: Path) -> threading.Lock:
        key = str(mirror)
        with self._locks_guard:
            return self._locks.setdefault(key, threading.Lock())

    @property
    def options(self) -> tuple[str, ...]:
        if self.allow_local_transport:
            return (*_SAFE_OPTIONS, "-c", "protocol.file.allow=always")
        return _SAFE_OPTIONS

    @property
    def executable(self) -> str:
        if self._executable is None:
            self._executable = shutil.which("git")
        if not self._executable:
            raise IntegrationError("git_unavailable", "服务器未安装 Git，无法获取代码快照。")
        return self._executable

    def _git_version(self) -> tuple[int, int]:
        if self._version is None:
            completed = self._execute(["version"])
            match = _VERSION.search(completed.stdout or "")
            if match is None:
                raise IntegrationError("git_unavailable", "无法识别 Git 版本。")
            self._version = (int(match.group(1)), int(match.group(2)))
        return self._version

    def pinned_options(self, host: str, addresses: list[str]) -> tuple[str, ...]:
        """把已验证的公网地址固定给 libcurl，避免连接时再次解析主机名。"""
        if not addresses:
            raise IntegrationError("network_unavailable", "未获得可用的托管主机地址。")
        if self._git_version() < _MIN_PINNED_GIT:
            raise IntegrationError(
                "git_unsupported", "Git 版本过低，无法固定已验证的托管主机地址。"
            )
        resolved = ",".join(addresses)
        return (*self.options, "-c", f"http.curloptResolve={host}:443:{resolved}")

    def _environment(self) -> dict[str, str]:
        env = {
            key: value
            for key, value in os.environ.items()
            if key not in _SCRUBBED_ENV
            and not any(key.startswith(prefix) for prefix in _SCRUBBED_ENV_PREFIXES)
        }
        env.update(
            {
                "GIT_TERMINAL_PROMPT": "0",
                "GIT_CONFIG_NOSYSTEM": "1",
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_OPTIONAL_LOCKS": "0",
                "LC_ALL": "C",
            }
        )
        return env

    def _execute(
        self,
        args: list[str],
        *,
        options: tuple[str, ...] | None = None,
        cancel_event: threading.Event | None = None,
        text: bool = True,
    ) -> _CommandResult:
        command = [self.executable, *(options or self.options), *args]
        deadline = time.monotonic() + self.timeout_seconds
        try:
            # 参数均为程序生成的固定列表，未使用 shell；提交哈希与主机构成已校验。
            # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
            process = subprocess.Popen(
                command,
                env=self._environment(),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=text,
                encoding="utf-8" if text else None,
                errors="replace" if text else None,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise IntegrationError(
                "git_unavailable", "服务器未安装 Git，无法获取代码快照。"
            ) from exc
        while True:
            if cancel_event is not None and cancel_event.is_set():
                process.kill()
                process.communicate()
                raise IntegrationError("repository_cancelled", "准备代码快照的操作已取消。")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                process.kill()
                process.communicate()
                raise IntegrationError("repository_fetch_timeout", "获取代码快照超时。")
            try:
                stdout, stderr = process.communicate(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        return _CommandResult(command, process.returncode, stdout, stderr)

    def _run(
        self,
        args: list[str],
        *,
        code: str,
        options: tuple[str, ...] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> str:
        completed = self._execute(args, options=options, cancel_event=cancel_event)
        if completed.returncode != 0:
            detail = (completed.stderr or "").strip().splitlines()
            if detail:
                logger.warning("git command failed: %s", detail[-1][:200])
            raise _GitFailure(code, self._message(code), completed.stderr or "")
        return completed.stdout

    @staticmethod
    def _message(code: str) -> str:
        return {
            "repository_fetch_failed": "无法从代码托管主机获取代码快照。",
            "commit_not_found": "快照中找不到指定提交。",
            "snapshot_export_failed": "导出指定版本快照失败。",
        }.get(code, "Git 操作失败。")

    def _mirror_path(self, repo_url: str) -> Path:
        digest = hashlib.sha256(repo_url.encode("utf-8")).hexdigest()[:24]
        return self.mirror_root / f"{digest}.git"

    def local_mirror(self, repo_url: str) -> Path | None:
        mirror = self._mirror_path(repo_url)
        if (mirror / "HEAD").is_file():
            return mirror
        return None

    def has_commit(self, handle: Path, commit: str) -> bool:
        completed = self._execute(["-C", str(handle), "cat-file", "-e", f"{commit}^{{commit}}"])
        return completed.returncode == 0

    def _ensure_remote(self, mirror: Path, repo_url: str) -> None:
        """修复缺 HEAD 或缺少/错误 origin 的半成品镜像。"""
        if not (mirror / "HEAD").is_file():
            shutil.rmtree(mirror, ignore_errors=True)
            mirror.parent.mkdir(parents=True, exist_ok=True)
            self._run(["init", "--bare", "--quiet", str(mirror)], code="repository_fetch_failed")
        current = self._execute(["-C", str(mirror), "config", "--get", "remote.origin.url"])
        if current.returncode != 0:
            self._run(
                ["-C", str(mirror), "remote", "add", "origin", repo_url],
                code="repository_fetch_failed",
            )
        elif current.stdout.strip() != repo_url:
            self._run(
                ["-C", str(mirror), "remote", "set-url", "origin", repo_url],
                code="repository_fetch_failed",
            )

    def fetch(
        self,
        repo_url: str,
        commit: str,
        *,
        options: tuple[str, ...] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> Path:
        mirror = self._mirror_path(repo_url)
        options = options or self.options
        with self._lock_for(mirror):
            self._ensure_remote(mirror, repo_url)
            if not self.has_commit(mirror, commit):
                self._fetch_commit(mirror, commit, options=options, cancel_event=cancel_event)
            self._enforce_mirror_quota(keep=mirror)
        return mirror

    def _fetch_commit(
        self,
        mirror: Path,
        commit: str,
        *,
        options: tuple[str, ...],
        cancel_event: threading.Event | None = None,
    ) -> None:
        branches = "+refs/heads/*:refs/remotes/origin/*"
        attempts = (
            ["-C", str(mirror), "fetch", "--no-tags", "--depth=1", "origin", commit],
            ["-C", str(mirror), "fetch", "--no-tags", "--depth=1", "origin", branches],
            [
                "-C",
                str(mirror),
                "fetch",
                "--no-tags",
                f"--depth={self.max_fetch_depth}",
                "origin",
                branches,
            ],
        )
        reachable = False
        for args in attempts:
            try:
                self._run(
                    args, code="repository_fetch_failed", options=options, cancel_event=cancel_event
                )
            except _GitFailure:
                continue
            reachable = True
            if self.has_commit(mirror, commit):
                return
        if self.has_commit(mirror, commit):
            return
        if reachable:
            # 托管端点可达但提交对象不存在（例如链接中的 sha 不存在）。
            raise IntegrationError("commit_not_found", "托管主机上找不到指定提交。")
        raise IntegrationError("repository_fetch_failed", "无法从代码托管主机获取指定提交。")

    def ensure(
        self,
        handle: Path,
        commit: str,
        *,
        options: tuple[str, ...] | None = None,
        cancel_event: threading.Event | None = None,
    ) -> None:
        if self.has_commit(handle, commit):
            return
        options = options or self.options
        with self._lock_for(handle):
            if not self.has_commit(handle, commit):
                self._fetch_commit(handle, commit, options=options, cancel_event=cancel_event)

    def resolve(self, handle: Path, commit: str) -> str:
        output = self._run(
            [
                "-C",
                str(handle),
                "rev-parse",
                "--verify",
                "--end-of-options",
                f"{commit}^{{commit}}",
            ],
            code="commit_not_found",
        )
        resolved = output.strip()
        if len(resolved) != 40 or any(ch not in "0123456789abcdef" for ch in resolved):
            raise IntegrationError("commit_not_found", "提交标识无法解析为完整提交。")
        return resolved

    def parents(self, handle: Path, commit: str) -> list[str]:
        # 直接读取提交对象头部：shallow 克隆的 rev-list 会隐藏父提交，
        # 但 cat-file 仍保留 parent 行，因此能可靠判断多父提交。
        output = self._run(
            ["-C", str(handle), "cat-file", "commit", commit],
            code="commit_not_found",
        )
        parents = []
        for line in output.splitlines():
            if line.startswith("parent "):
                candidate = line.split(" ", 1)[1].strip()
                if len(candidate) != 40 or any(ch not in "0123456789abcdef" for ch in candidate):
                    raise IntegrationError("commit_not_found", "提交对象中的父提交无效。")
                parents.append(candidate)
        return parents

    def export(
        self,
        handle: Path,
        commit: str,
        destination: Path,
        *,
        cancel_event: threading.Event | None = None,
    ) -> int:
        """按提交树直接读取 blob，不应用 `export-ignore`/`export-subst`。"""
        entries = self._tree_entries(handle, commit, cancel_event=cancel_event)
        if len(entries) > self.max_files:
            raise IntegrationError("snapshot_too_large", "指定版本快照文件数超出上限。")
        destination.mkdir(parents=True, exist_ok=True)
        root = destination.resolve()
        # 命令由固定子命令与已校验的镜像句柄组成，未使用 shell。
        # nosemgrep: python.lang.security.audit.dangerous-subprocess-use-audit
        process = subprocess.Popen(
            [self.executable, *self.options, "-C", str(handle), "cat-file", "--batch"],
            env=self._environment(),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
        )
        count = 0
        total = 0
        try:
            assert process.stdin is not None and process.stdout is not None
            for sha, raw_path in entries:
                if cancel_event is not None and cancel_event.is_set():
                    raise IntegrationError("repository_cancelled", "准备代码快照的操作已取消。")
                relative = _relative_path(raw_path)
                process.stdin.write(sha.encode("ascii") + b"\n")
                process.stdin.flush()
                header = process.stdout.readline()
                fields = header.split()
                if len(fields) != 3 or fields[1] != b"blob":
                    raise IntegrationError("snapshot_export_failed", "读取快照文件内容失败。")
                size = int(fields[2])
                if size > self.max_bytes or total + size > self.max_bytes:
                    raise IntegrationError("snapshot_too_large", "指定版本快照体积超出上限。")
                data = process.stdout.read(size)
                process.stdout.read(1)  # 结尾换行
                if len(data) != size:
                    raise IntegrationError("snapshot_export_failed", "读取快照文件内容失败。")
                target = (root / relative).resolve()
                if not target.is_relative_to(root):
                    raise IntegrationError("snapshot_export_failed", "快照路径超出目标目录。")
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
                count += 1
                total += size
        finally:
            if process.stdin is not None:
                process.stdin.close()
            if process.poll() is None:
                process.kill()
            process.wait()
        return count

    def _tree_entries(
        self,
        handle: Path,
        commit: str,
        *,
        cancel_event: threading.Event | None = None,
    ) -> list[tuple[str, bytes]]:
        completed = self._execute(
            ["-C", str(handle), "ls-tree", "-r", "-z", "--full-tree", commit],
            cancel_event=cancel_event,
            text=False,
        )
        if completed.returncode != 0:
            raise IntegrationError("snapshot_export_failed", "读取指定版本文件树失败。")
        entries: list[tuple[str, bytes]] = []
        for record in completed.stdout.split(b"\0"):
            if not record:
                continue
            meta, _, raw_path = record.partition(b"\t")
            fields = meta.split()
            if len(fields) < 3 or not raw_path:
                continue
            mode, kind, sha = fields[0], fields[1], fields[2]
            if kind != b"blob" or mode == b"120000":
                # 符号链接与子模块无法安全物化为快照文件。
                continue
            entries.append((sha.decode("ascii"), raw_path))
        entries.sort(key=lambda item: item[1])
        return entries

    def _enforce_mirror_quota(self, *, keep: Path) -> None:
        if self.max_total_bytes is None or not self.mirror_root.is_dir():
            return
        mirrors = [path for path in self.mirror_root.iterdir() if path.is_dir()]
        sizes = {path: _directory_size(path) for path in mirrors}
        total = sum(sizes.values())
        for path in sorted(mirrors, key=lambda item: item.stat().st_mtime):
            if total <= self.max_total_bytes:
                break
            if path == keep:
                continue
            shutil.rmtree(path, ignore_errors=True)
            total -= sizes[path]
        if total > self.max_total_bytes:
            raise IntegrationError("storage_quota_exceeded", "快照镜像存储配额已用尽。")


def _relative_path(raw: bytes) -> str:
    """校验提交中的路径可唯一映射到跨平台快照路径。"""
    try:
        path = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise IntegrationError("snapshot_export_failed", "提交包含非 UTF-8 路径。") from exc
    if "\\" in path:
        raise IntegrationError("snapshot_export_failed", "提交包含跨平台歧义的路径。")
    parts = path.split("/")
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise IntegrationError("snapshot_export_failed", "提交包含非法路径。")
    if any(part.casefold() == ".git" for part in parts):
        raise IntegrationError("snapshot_export_failed", "提交包含 Git 元数据路径。")
    return "/".join(parts)


def _directory_size(path: Path) -> int:
    total = 0
    for file in path.rglob("*"):
        try:
            if file.is_file():
                total += file.stat().st_size
        except OSError:
            continue
    return total
