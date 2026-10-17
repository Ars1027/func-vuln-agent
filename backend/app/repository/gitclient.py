"""只读 Git 镜像缓存：拉取指定提交并导出为不含 `.git` 的文件树。

不 checkout 工作区、不导出历史，也不在快照目录内保留 Git 元数据。
所有命令禁用协议跳转与 HTTP 重定向，默认只允许 https 传输。
"""

import hashlib
import logging
import os
import shutil
import subprocess
import tarfile
import tempfile
import threading
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
)


class GitClient(Protocol):
    """准备层依赖的最小 Git 能力；`handle` 为后端自有句柄。"""

    def fetch(self, repo_url: str, commit: str) -> Any: ...

    def resolve(self, handle: Any, commit: str) -> str: ...

    def parents(self, handle: Any, commit: str) -> list[str]: ...

    def ensure(self, handle: Any, commit: str) -> None: ...

    def export(self, handle: Any, commit: str, destination: Path) -> int: ...


class _GitFailure(IntegrationError):
    """保留 stderr 供同一次操作内部区分可达性与提交缺失。"""

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
        max_files: int = 200_000,
        max_bytes: int = 256 * 1024 * 1024,
        allow_local_transport: bool = False,
    ) -> None:
        self.mirror_root = Path(mirror_root)
        self._executable = executable
        self.timeout_seconds = timeout_seconds
        self.max_files = max_files
        self.max_bytes = max_bytes
        # 仅测试用：允许 file:// 与本地路径（生产环境保持 False）。
        self.allow_local_transport = allow_local_transport
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()

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

    def _environment(self) -> dict[str, str]:
        env = {key: value for key, value in os.environ.items() if key not in _SCRUBBED_ENV}
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

    def _execute(self, args: list[str]) -> subprocess.CompletedProcess:
        command = [self.executable, *self.options, *args]
        try:
            return subprocess.run(
                command,
                env=self._environment(),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
                shell=False,
            )
        except FileNotFoundError as exc:
            raise IntegrationError(
                "git_unavailable", "服务器未安装 Git，无法获取代码快照。"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise IntegrationError("repository_fetch_timeout", "获取代码快照超时。") from exc

    def _run(self, args: list[str], *, code: str) -> str:
        completed = self._execute(args)
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

    def _has_commit(self, mirror: Path, commit: str) -> bool:
        completed = self._execute(["-C", str(mirror), "cat-file", "-e", f"{commit}^{{commit}}"])
        return completed.returncode == 0

    def _init_mirror(self, mirror: Path, repo_url: str) -> None:
        mirror.parent.mkdir(parents=True, exist_ok=True)
        self._run(["init", "--bare", "--quiet", str(mirror)], code="repository_fetch_failed")
        self._run(
            ["-C", str(mirror), "remote", "add", "origin", repo_url],
            code="repository_fetch_failed",
        )

    def fetch(self, repo_url: str, commit: str) -> Path:
        mirror = self._mirror_path(repo_url)
        with self._lock_for(mirror):
            if not (mirror / "HEAD").exists():
                self._init_mirror(mirror, repo_url)
            if not self._has_commit(mirror, commit):
                self._fetch_commit(mirror, commit)
        return mirror

    def _fetch_commit(self, mirror: Path, commit: str) -> None:
        attempts = (
            ["-C", str(mirror), "fetch", "--no-tags", "--depth=1", "origin", commit],
            [
                "-C",
                str(mirror),
                "fetch",
                "--no-tags",
                "--depth=1",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
            ],
            [
                "-C",
                str(mirror),
                "fetch",
                "--no-tags",
                "origin",
                "+refs/heads/*:refs/remotes/origin/*",
            ],
        )
        reachable = False
        for args in attempts:
            try:
                self._run(args, code="repository_fetch_failed")
            except _GitFailure:
                continue
            reachable = True
            if self._has_commit(mirror, commit):
                return
        if self._has_commit(mirror, commit):
            return
        if reachable:
            # 托管端点可达但提交对象不存在（例如链接中的 sha 不存在）。
            raise IntegrationError("commit_not_found", "托管主机上找不到指定提交。")
        raise IntegrationError("repository_fetch_failed", "无法从代码托管主机获取指定提交。")

    def ensure(self, handle: Path, commit: str) -> None:
        if self._has_commit(handle, commit):
            return
        with self._lock_for(handle):
            if not self._has_commit(handle, commit):
                self._fetch_commit(handle, commit)

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

    def export(self, handle: Path, commit: str, destination: Path) -> int:
        destination.mkdir(parents=True, exist_ok=True)
        descriptor, archive_name = tempfile.mkstemp(suffix=".tar", prefix="snapshot-")
        os.close(descriptor)
        archive = Path(archive_name)
        try:
            self._run(
                [
                    "-C",
                    str(handle),
                    "archive",
                    "--format=tar",
                    f"--output={archive}",
                    commit,
                ],
                code="snapshot_export_failed",
            )
            return self._extract(archive, destination)
        except OSError as exc:
            logger.warning("snapshot export failed: %s", type(exc).__name__)
            raise IntegrationError("snapshot_export_failed", "导出指定版本快照失败。") from exc
        finally:
            archive.unlink(missing_ok=True)

    def _extract(self, archive: Path, destination: Path) -> int:
        root = destination.resolve()
        count = 0
        total = 0
        with tarfile.open(archive, mode="r:") as tar:
            for member in tar:
                # 只导出普通文件；符号链接、子模块等无法安全物化。
                if not member.isfile():
                    continue
                parts = [part for part in member.name.replace("\\", "/").split("/") if part]
                if not parts or any(part in {".", ".."} for part in parts):
                    continue
                if any(part.casefold() == ".git" for part in parts):
                    continue
                relative = "/".join(parts)
                target = (root / relative).resolve()
                if not target.is_relative_to(root):
                    continue
                if member.size > self.max_bytes or total + member.size > self.max_bytes:
                    raise IntegrationError("snapshot_too_large", "指定版本快照体积超出上限。")
                count += 1
                if count > self.max_files:
                    raise IntegrationError("snapshot_too_large", "指定版本快照文件数超出上限。")
                total += member.size
                target.parent.mkdir(parents=True, exist_ok=True)
                source = tar.extractfile(member)
                if source is None:
                    continue
                with source, open(target, "wb") as out:
                    shutil.copyfileobj(source, out)
        return count
