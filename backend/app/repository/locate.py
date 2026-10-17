"""文本级定位：函数原文定位、字面量搜索与符号定义/调用启发式分类。

这里不做编译器级语法分析：空白归一化后按原文匹配，行号来自原文偏移；
符号分类依据括号与花括号文本形态，注释和字符串不会被剔除。覆盖范围
写入 `RepositoryResult.scope`，由 Agent 判断证据与条件的关系。
"""

import re
from dataclasses import dataclass

from app.repository.store import SnapshotStore
from app.schemas.models import CodeLocation, RepositoryResult
from app.schemas.ports import IntegrationError

MAX_SCAN_BYTES = 2 * 1024 * 1024
_IDENTIFIER_KEYWORDS = frozenset(
    {
        "if",
        "for",
        "while",
        "switch",
        "return",
        "sizeof",
        "else",
        "case",
        "do",
        "new",
        "delete",
        "throw",
        "goto",
        "and",
        "or",
        "not",
    }
)
_TRAILING_QUALIFIERS = re.compile(
    r"^(?:const\b|volatile\b|noexcept\b|override\b|final\b|__attribute__|requires\b)"
)
_TYPE_PREFIX_ENDINGS = frozenset("=(),;{}!|<>?:~^+-/%")
_RANK = {"definition": 0, "macro": 0, "declaration": 1, "call": 2, "reference": 3}


def normalize_whitespace(text: str) -> tuple[str, list[int]]:
    """折叠空白并保留归一化字符到原文偏移的映射。"""
    characters: list[str] = []
    offsets: list[int] = []
    previous_space = False
    for offset, character in enumerate(text):
        if character.isspace():
            if previous_space:
                continue
            characters.append(" ")
            offsets.append(offset)
            previous_space = True
        else:
            characters.append(character)
            offsets.append(offset)
            previous_space = False
    start = 0
    while start < len(characters) and characters[start] == " ":
        start += 1
    end = len(characters)
    while end > start and characters[end - 1] == " ":
        end -= 1
    return "".join(characters[start:end]), offsets[start:end]


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _expand_lines(text: str, start: int, end: int) -> tuple[int, int, str]:
    """把匹配偏移扩展为完整行区间，保证内容与原文逐行一致。"""
    start_line = _line_number(text, start)
    end_line = _line_number(text, max(end - 1, start))
    lines = text.splitlines()
    return start_line, end_line, "\n".join(lines[start_line - 1 : end_line])


def iter_normalized_matches(text: str, needle: str) -> list[tuple[int, int]]:
    """返回 `needle` 在原文中的 (start, end) 偏移列表。"""
    haystack, offsets = normalize_whitespace(text)
    found: list[tuple[int, int]] = []
    position = haystack.find(needle)
    while position != -1:
        start = offsets[position]
        end = offsets[position + len(needle) - 1] + 1
        found.append((start, end))
        position = haystack.find(needle, position + len(needle))
    return found


def locate_function(store: SnapshotStore, snapshot_ref: str, func: str) -> CodeLocation:
    """在快照中定位待测函数的相对路径与原始行号。"""
    needle, _ = normalize_whitespace(func)
    if not needle:
        raise IntegrationError("function_not_found", "待测函数内容为空，无法在快照中定位。")
    found: list[CodeLocation] = []
    for entry in store.iter_files(snapshot_ref, max_bytes=MAX_SCAN_BYTES):
        for start, end in iter_normalized_matches(entry.text, needle):
            start_line, end_line, content = _expand_lines(entry.text, start, end)
            found.append(
                CodeLocation(
                    snapshot_ref=snapshot_ref,
                    path=entry.path,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                )
            )
            if len(found) > 1:
                locations = ", ".join(f"{item.path}:{item.start_line}" for item in found[:5])
                raise IntegrationError(
                    "function_ambiguous",
                    f"待测函数在快照中出现多次（{locations}），无法确定唯一证据位置。",
                )
    if not found:
        raise IntegrationError(
            "function_not_found", "当前函数与指定版本快照不一致，快照中找不到该函数。"
        )
    return found[0]


def search_code(
    store: SnapshotStore,
    snapshot_ref: str,
    query: str,
    *,
    limit: int = 20,
    max_file_bytes: int = MAX_SCAN_BYTES,
) -> RepositoryResult:
    """在快照的 C/C++ 源文件内做字面量搜索，返回完整行区间。"""
    needle, _ = normalize_whitespace(query)
    if not needle:
        raise IntegrationError("empty_query", "搜索内容不能为空。")
    matches: list[CodeLocation] = []
    total = 0
    scanned = 0
    for entry in store.iter_files(snapshot_ref, max_bytes=max_file_bytes):
        scanned += 1
        offsets = iter_normalized_matches(entry.text, needle)
        total += len(offsets)
        for start, end in offsets:
            if len(matches) >= limit:
                break
            start_line, end_line, content = _expand_lines(entry.text, start, end)
            matches.append(
                CodeLocation(
                    snapshot_ref=snapshot_ref,
                    path=entry.path,
                    start_line=start_line,
                    end_line=end_line,
                    content=content,
                )
            )
    scope = (
        f"case-sensitive literal text search (whitespace-normalized) over {scanned} C/C++ "
        f"files; {total} match(es), returning {len(matches)}"
    )
    if total > len(matches):
        scope += f" (truncated by limit {limit})"
    scope += "; text-level scan, not semantic or dataflow analysis"
    return RepositoryResult(matches=matches, scope=scope)


@dataclass(frozen=True)
class SymbolMatch:
    location: CodeLocation
    kind: str


def _matching_paren(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < len(text):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _brace_depth(text: str, offset: int) -> int:
    return text.count("{", 0, offset) - text.count("}", 0, offset)


def _line_text(text: str, offset: int) -> str:
    start = text.rfind("\n", 0, offset) + 1
    end = text.find("\n", offset)
    return text[start : len(text) if end == -1 else end]


def _looks_like_declaration(prefix: str) -> bool:
    """`prefix` 为符号前的同行或前文，用于区分返回类型与调用语境。"""
    trimmed = prefix.rstrip()
    if not trimmed or trimmed.endswith("->") or trimmed.endswith("."):
        return False
    if trimmed[-1] in _TYPE_PREFIX_ENDINGS:
        return False
    tokens = re.findall(r"[A-Za-z_][A-Za-z0-9_]*", prefix)
    if not tokens:
        return False
    return tokens[-1] not in _IDENTIFIER_KEYWORDS


def _classify(text: str, offset: int, symbol: str) -> str:
    line = _line_text(text, offset)
    if re.match(rf"\s*#\s*define\s+{re.escape(symbol)}(?![A-Za-z0-9_])", line):
        return "macro"
    after = text[offset + len(symbol) :]
    match = re.match(r"\s*\(", after)
    if match:
        close = _matching_paren(text, offset + len(symbol) + match.end() - 1)
        if close != -1:
            rest = text[close + 1 : close + 400].lstrip()
            if rest.startswith("{") or (
                _TRAILING_QUALIFIERS.match(rest) and ";" not in rest.split("{", 1)[0]
            ):
                return "definition"
        line_start = text.rfind("\n", 0, offset) + 1
        prefix = text[max(line_start, offset - 200) : offset]
        return "declaration" if _looks_like_declaration(prefix) else "call"
    stripped = text[offset + len(symbol) : offset + len(symbol) + 40].lstrip()
    if stripped[:1] in {"=", ";", "["} and _brace_depth(text, offset) == 0:
        return "definition"
    return "reference"


def find_symbol(
    store: SnapshotStore,
    snapshot_ref: str,
    symbol: str,
    *,
    limit: int = 20,
    max_file_bytes: int = MAX_SCAN_BYTES,
    max_occurrences: int = 5000,
) -> RepositoryResult:
    """按标识符定位定义、宏、声明与调用位置。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        raise IntegrationError("invalid_symbol", "符号名称必须是单个 C/C++ 标识符。")
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    collected: list[SymbolMatch] = []
    total = 0
    scanned = 0
    for entry in store.iter_files(snapshot_ref, max_bytes=max_file_bytes):
        scanned += 1
        for match in pattern.finditer(entry.text):
            total += 1
            if total > max_occurrences:
                break
            start_line, end_line, content = _expand_lines(entry.text, match.start(), match.end())
            collected.append(
                SymbolMatch(
                    location=CodeLocation(
                        snapshot_ref=snapshot_ref,
                        path=entry.path,
                        start_line=start_line,
                        end_line=end_line,
                        content=content,
                    ),
                    kind=_classify(entry.text, match.start(), symbol),
                )
            )
        if total > max_occurrences:
            break
    collected.sort(
        key=lambda item: (_RANK[item.kind], item.location.path, item.location.start_line)
    )
    selected = collected[:limit]
    summary = ", ".join(
        f"{item.location.path}:{item.location.start_line} {item.kind}" for item in selected[:8]
    )
    scope = (
        f"text-level identifier scan over {scanned} C/C++ files; {total} occurrence(s), "
        f"returning {len(selected)}; order: definitions/macros, declarations, calls, other "
        "references; classification by parenthesis and brace heuristics, comments and strings "
        "are not excluded, not a compiler AST"
    )
    if summary:
        scope += f"; matches: {summary}"
    if total > len(selected):
        scope += f" (truncated by limit {limit})"
    return RepositoryResult(matches=[item.location for item in selected], scope=scope)
