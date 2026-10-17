"""#3/#4 测试用内存 Git 后端。

仓库内容为人工编写的合成样例，不访问网络，不代表真实 Git 行为。
"""

from pathlib import Path

from app.schemas.ports import IntegrationError


class FakeGit:
    """按 `{repo_url: {commit: {path: str|bytes}}}` 提供提交与父提交关系。"""

    def __init__(self, repositories, parents=None):
        self.repositories = repositories
        self.parents_map = parents or {}
        self.exported: list[tuple[str, str]] = []

    def _repo(self, repo_url: str) -> dict:
        if repo_url not in self.repositories:
            raise IntegrationError("repository_fetch_failed", "无法获取代码快照。")
        return self.repositories[repo_url]

    def _expand(self, repo: dict, spec: str) -> str | None:
        if spec in repo:
            return spec
        matches = [sha for sha in repo if sha.startswith(spec)]
        return matches[0] if len(matches) == 1 else None

    def fetch(self, repo_url: str, commit: str) -> str:
        if self._expand(self._repo(repo_url), commit) is None:
            raise IntegrationError("commit_not_found", "找不到指定提交。")
        return repo_url

    def resolve(self, handle: str, commit: str) -> str:
        resolved = self._expand(self._repo(handle), commit)
        if resolved is None:
            raise IntegrationError("commit_not_found", "找不到指定提交。")
        return resolved

    def parents(self, handle: str, commit: str) -> list[str]:
        return list(self.parents_map.get((handle, commit), ()))

    def ensure(self, handle: str, commit: str) -> None:
        if commit not in self._repo(handle):
            raise IntegrationError("commit_not_found", "找不到指定提交。")

    def export(self, handle: str, commit: str, destination: Path) -> int:
        files = self._repo(handle).get(commit)
        if files is None:
            raise IntegrationError("commit_not_found", "找不到指定提交。")
        self.exported.append((handle, commit))
        for path, content in files.items():
            target = Path(destination) / path
            target.parent.mkdir(parents=True, exist_ok=True)
            if isinstance(content, bytes):
                target.write_bytes(content)
            else:
                target.write_text(content, encoding="utf-8")
        return len(files)
