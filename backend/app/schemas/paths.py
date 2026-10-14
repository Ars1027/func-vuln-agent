"""Agent 参数与代码证据共用的快照相对路径规则。"""


def normalize_snapshot_path(path: str) -> str:
    """统一分隔符，拒绝越界、Git 元数据及跨平台解释不一致的路径组件。"""
    path = path.replace("\\", "/")
    if not path or path.startswith("/") or ":" in path or "\x00" in path:
        raise ValueError("path must be relative to the snapshot")
    parts = []
    for part in path.split("/"):
        if part in {"", "."}:
            continue
        # Windows 会处理尾随点或空格，直接拒绝这类歧义，不猜测对应的真实文件。
        if part == ".." or part != part.rstrip(" .") or part.casefold() == ".git":
            raise ValueError("path must stay inside the snapshot, excluding .git")
        parts.append(part)
    if not parts:
        raise ValueError("path must name a file inside the snapshot")
    return "/".join(parts)
