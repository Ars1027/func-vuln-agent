"""课程 `commit_url` 的解析、托管主机白名单与网络目标校验。

准备层只接受白名单内的固定托管端点，并且仅用于拼接仓库地址；
实际拉取由 `GitClient` 用 https 完成，并关闭 HTTP 重定向。
"""

import ipaddress
import re
import socket
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from urllib.parse import urlsplit

from app.schemas.ports import IntegrationError

DEFAULT_ALLOWED_HOSTS = ("github.com",)

# Git 托管端点的提交页：/{owner}/{repo}/commit/{sha}[.patch|.diff][/]
_COMMIT_PATH = re.compile(
    r"^/(?P<owner>[A-Za-z0-9][A-Za-z0-9_.-]*)"
    r"/(?P<repo>[A-Za-z0-9][A-Za-z0-9_.-]*)"
    r"/commit/(?P<commit>[0-9a-fA-F]{7,40})"
    r"(?:\.(?:patch|diff))?/?$"
)
_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?$")

AddressInfo = Iterable[tuple]
Resolver = Callable[[str], AddressInfo]


@dataclass(frozen=True)
class CommitTarget:
    """解析后的托管端点信息；不携带 `target` 等标签语义。"""

    host: str
    owner: str
    repo: str
    commit: str
    repo_url: str


def parse_commit_url(
    url: str, allowed_hosts: Iterable[str] = DEFAULT_ALLOWED_HOSTS
) -> CommitTarget:
    """校验提交链接并返回可拼接的 https 仓库地址。

    拒绝非 https、带凭据/端口的主机、白名单外主机、IP 字面量
    以及不符合约定格式的路径。
    """
    normalized_hosts = {host.strip().lower() for host in allowed_hosts if host.strip()}
    if not normalized_hosts:
        raise IntegrationError("repository_host_not_configured", "未配置允许的代码托管主机。")
    if not isinstance(url, str) or not url.strip():
        raise IntegrationError("unsupported_commit_url", "提交链接为空。")
    try:
        parts = urlsplit(url.strip())
    except ValueError as exc:
        raise IntegrationError("unsupported_commit_url", "提交链接格式无效。") from exc

    if parts.scheme.lower() != "https":
        raise IntegrationError("unsupported_commit_url", "提交链接必须使用 https。")
    if "@" in parts.netloc or ":" in parts.netloc:
        raise IntegrationError("unsupported_commit_url", "提交链接不能包含凭据或端口。")
    host = (parts.hostname or "").lower()
    if not host or not _HOST.match(host) or host.endswith("."):
        raise IntegrationError("unsupported_host", "提交链接的主机名无效。")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise IntegrationError("unsupported_host", "提交链接不能直接使用 IP 地址。")
    if host not in normalized_hosts:
        raise IntegrationError(
            "unsupported_host", f"不支持从 {host} 获取快照，仅允许配置的代码托管主机。"
        )

    match = _COMMIT_PATH.match(parts.path)
    if match is None:
        raise IntegrationError(
            "unsupported_commit_url",
            "提交链接需形如 https://<host>/<owner>/<repo>/commit/<sha>。",
        )
    owner = match.group("owner")
    repo = match.group("repo")
    if repo.lower().endswith(".git"):
        repo = repo[:-4]
    if owner in {".", ".."} or repo in {".", ".."} or not repo:
        raise IntegrationError("unsupported_commit_url", "提交链接的仓库路径无效。")

    commit = match.group("commit").lower()
    return CommitTarget(
        host=host,
        owner=owner,
        repo=repo,
        commit=commit,
        repo_url=f"https://{host}/{owner}/{repo}.git",
    )


def _system_resolver(host: str) -> list[tuple]:
    return socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)


def verify_public_host(host: str, resolver: Resolver | None = None) -> None:
    """解析托管主机并拒绝解析到私网、回环、链路本地等非公网地址的目标。"""
    resolve = resolver or _system_resolver
    try:
        addresses = {str(info[4][0]).split("%", 1)[0] for info in resolve(host) if len(info) > 4}
    except OSError as exc:
        raise IntegrationError("network_unavailable", "无法解析代码托管主机。") from exc
    if not addresses:
        raise IntegrationError("network_unavailable", "无法解析代码托管主机。")
    for address in addresses:
        try:
            parsed = ipaddress.ip_address(address)
        except ValueError as exc:
            raise IntegrationError("private_network_target", "托管主机解析结果无效。") from exc
        # is_global 排除私网、回环、链路本地、保留地址与 CGNAT 等非公网范围。
        if not parsed.is_global:
            raise IntegrationError(
                "private_network_target", "托管主机解析到非公网地址，已拒绝访问。"
            )
