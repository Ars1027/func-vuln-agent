"""文本级定位：函数原文定位、字面量搜索与符号定义/调用启发式分类。

这里不做编译器级语法分析：空白归一化后按原文匹配，行号来自原文偏移；
符号分类依据括号与花括号文本形态，注释和字符串不会被剔除。覆盖范围
写入 `RepositoryResult.scope`，由 Agent 判断证据与条件的关系。
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass

from app.repository.store import ScanReport, SnapshotStore
from app.schemas.models import CodeLocation, RepositoryResult
from app.schemas.ports import IntegrationError

MAX_SCAN_BYTES = 2 * 1024 * 1024
MAX_SCAN_TOTAL_BYTES = 64 * 1024 * 1024
MAX_MATCH_BUDGET = 50_000
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
_SCOPE_OPENERS = re.compile(r"\b(?:namespace|class|struct|union|enum)\b")
_RANK = {"definition": 0, "macro": 0, "declaration": 1, "call": 2, "reference": 3}
_LEXEMES = re.compile(
    r"""//[^\n]*|/\*[\s\S]*?(?:\*/|$)|"""
    r"""(?:u8|u|U|L)?R"(?P<delimiter>[^\s()\\]{0,16})\([\s\S]*?\)(?P=delimiter)"|"""
    r""""(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'"""
)
CLASSIFY_LOOKAHEAD = 400


def normalize_whitespace(text: str) -> tuple[str, list[int]]:
    """只折叠字面量外的空白，保留字符、字符串和原始字符串的内容及偏移。"""
    characters: list[str] = []
    offsets: list[int] = []
    previous_space = False
    literals = (
        match for match in _LEXEMES.finditer(text) if not match.group().startswith(("//", "/*"))
    )
    literal = next(literals, None)
    for offset, character in enumerate(text):
        while literal is not None and offset >= literal.end():
            literal = next(literals, None)
        in_literal = literal is not None and literal.start() <= offset < literal.end()
        if character.isspace() and not in_literal:
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
    lines = text.replace("\r\n", "\n").split("\n")
    return start_line, end_line, "\n".join(lines[start_line - 1 : end_line])


def iter_matches(text: str, needle: str) -> Iterator[tuple[int, int]]:
    """按原文偏移逐个产出匹配，避免为高频词一次性分配全部结果。"""
    haystack, offsets = normalize_whitespace(text)
    position = haystack.find(needle)
    while position != -1:
        start = offsets[position]
        end = offsets[position + len(needle) - 1] + 1
        yield start, end
        position = haystack.find(needle, position + len(needle))


def locate_function(
    store: SnapshotStore,
    snapshot_ref: str,
    func: str,
    *,
    report: ScanReport | None = None,
) -> CodeLocation:
    """在快照中定位待测函数的相对路径与原始行号。"""
    needle, _ = normalize_whitespace(func)
    if not needle:
        raise IntegrationError("function_not_found", "待测函数内容为空，无法在快照中定位。")
    scan = report if report is not None else ScanReport()
    found: list[CodeLocation] = []
    for entry in store.iter_files(snapshot_ref, max_bytes=MAX_SCAN_BYTES, report=scan):
        for start, end in iter_matches(entry.text, needle):
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
        detail = scan.note()
        if detail:
            detail = f"（{detail}）"
        raise IntegrationError(
            "function_scan_limit" if scan.oversized else "function_not_found",
            f"源码扫描超出大小上限，无法确认待测函数的位置{detail}。"
            if scan.oversized
            else f"当前函数与指定版本快照不一致，快照中找不到该函数{detail}。",
        )
    return found[0]


def search_code(
    store: SnapshotStore,
    snapshot_ref: str,
    query: str,
    *,
    limit: int = 20,
    max_file_bytes: int = MAX_SCAN_BYTES,
    match_budget: int = MAX_MATCH_BUDGET,
) -> RepositoryResult:
    """在快照的 C/C++ 源文件内做字面量搜索，返回完整行区间。"""
    needle, _ = normalize_whitespace(query)
    if not needle:
        raise IntegrationError("empty_query", "搜索内容不能为空。")
    report = ScanReport()
    matches: list[CodeLocation] = []
    total = 0
    truncated = False
    for entry in store.iter_files(snapshot_ref, max_bytes=max_file_bytes, report=report):
        for start, end in iter_matches(entry.text, needle):
            if total >= match_budget:
                truncated = True
                break
            total += 1
            if len(matches) >= limit:
                continue
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
        if truncated:
            break
    scope = (
        f"case-sensitive literal text search (whitespace-normalized) over "
        f"{report.scanned} C/C++ files; {total}{'+' if truncated else ''} match(es), "
        f"returning {len(matches)}"
    )
    if truncated:
        scope += f"; match counting stopped at budget {match_budget}"
    elif total > len(matches):
        scope += f" (truncated by limit {limit})"
    skipped = report.note()
    if skipped:
        scope += f"; {skipped}"
    scope += "; text-level scan, not semantic or dataflow analysis"
    return RepositoryResult(matches=matches, scope=scope)


@dataclass(frozen=True)
class SymbolMatch:
    location: CodeLocation
    kind: str


def _matching_paren(text: str, start: int) -> int:
    depth = 0
    index = start
    while index < min(len(text), start + CLASSIFY_LOOKAHEAD):
        if text[index] == "(":
            depth += 1
        elif text[index] == ")":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return -1


def _opener_kind(text: str, index: int) -> str:
    header = text[max(0, index - 300) : index]
    header = header[header.rfind(";") + 1 :]
    stripped = header.rstrip()
    if not stripped:
        return "block"
    if _SCOPE_OPENERS.search(stripped) and not stripped.endswith(")"):
        return "scope"
    if stripped.endswith(")"):
        return "function"
    if "=" in stripped:
        return "initializer"
    return "block"


def _symbol_contexts(
    text: str, matches: Iterator[re.Match]
) -> Iterator[tuple[re.Match, bool, int]]:
    """按符号位置向前扫描一次，避免对每次出现重新扫描整个文件前缀。"""
    stack: list[bool] = []
    non_global = 0
    index = 0
    line_start = 0
    quote: str | None = None
    line_comment = False
    block_comment = False
    for match in matches:
        while index < match.start():
            character = text[index]
            if character == "\n":
                line_start = index + 1
            if line_comment:
                if character == "\n":
                    line_comment = False
            elif block_comment:
                if text.startswith("*/", index):
                    block_comment = False
                    index += 1
            elif quote is not None:
                if character == "\\":
                    if text[index + 1 : index + 2] == "\n":
                        line_start = index + 2
                    index += 1
                elif character == quote:
                    quote = None
            elif text.startswith("//", index):
                line_comment = True
                index += 1
            elif text.startswith("/*", index):
                block_comment = True
                index += 1
            elif character in "'\"":
                quote = character
            elif character == "{":
                local = _opener_kind(text, index) != "scope"
                stack.append(local)
                non_global += local
            elif character == "}" and stack:
                non_global -= stack.pop()
            index += 1
        yield match, non_global == 0, line_start


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


def _classify(text: str, offset: int, symbol: str, *, global_scope: bool, line_start: int) -> str:
    if offset - line_start < 200 and re.fullmatch(
        rf"\s*#\s*define\s+{re.escape(symbol)}", text[line_start : offset + len(symbol)]
    ):
        return "macro"
    after = text[offset + len(symbol) : offset + len(symbol) + CLASSIFY_LOOKAHEAD]
    match = re.match(r"\s*\(", after)
    if match:
        close = _matching_paren(text, offset + len(symbol) + match.end() - 1)
        if close != -1:
            rest = text[close + 1 : close + 400].lstrip()
            if rest.startswith("{") or (
                _TRAILING_QUALIFIERS.match(rest) and ";" not in rest.split("{", 1)[0]
            ):
                return "definition"
        prefix = text[max(line_start, offset - 200) : offset]
        return "declaration" if _looks_like_declaration(prefix) else "call"
    stripped = text[offset + len(symbol) : offset + len(symbol) + 40].lstrip()
    if stripped[:1] in {"=", ";", "["} and global_scope:
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
    scan_byte_budget: int = MAX_SCAN_TOTAL_BYTES,
) -> RepositoryResult:
    """按标识符定位定义、宏、声明与调用位置。"""
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        raise IntegrationError("invalid_symbol", "符号名称必须是单个 C/C++ 标识符。")
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    report = ScanReport()
    buckets: dict[int, list[SymbolMatch]] = {rank: [] for rank in set(_RANK.values())}
    counted = 0
    scanned_bytes = 0
    count_truncated = False
    scan_truncated = False
    for entry in store.iter_files(snapshot_ref, max_bytes=max_file_bytes, report=report):
        scanned_bytes += entry.size
        if scanned_bytes > scan_byte_budget:
            scan_truncated = True
            break
        for match, global_scope, line_start in _symbol_contexts(
            entry.text, pattern.finditer(entry.text)
        ):
            if counted >= max_occurrences:
                count_truncated = True
            else:
                counted += 1
            kind = _classify(
                entry.text, match.start(), symbol, global_scope=global_scope, line_start=line_start
            )
            bucket = buckets[_RANK[kind]]
            if len(bucket) >= limit:
                continue
            start_line, end_line, content = _expand_lines(entry.text, match.start(), match.end())
            bucket.append(
                SymbolMatch(
                    location=CodeLocation(
                        snapshot_ref=snapshot_ref,
                        path=entry.path,
                        start_line=start_line,
                        end_line=end_line,
                        content=content,
                    ),
                    kind=kind,
                )
            )
    candidates = [item for bucket in buckets.values() for item in bucket]
    candidates.sort(
        key=lambda item: (_RANK[item.kind], item.location.path, item.location.start_line)
    )
    selected = candidates[:limit]
    summary = ", ".join(
        f"{item.location.path}:{item.location.start_line} {item.kind}" for item in selected[:8]
    )
    scope = (
        f"text-level identifier scan over {report.scanned} C/C++ files; "
        f"{counted}{'+' if count_truncated or scan_truncated else ''} occurrence(s), "
        f"returning {len(selected)}; order: definitions/macros, declarations, calls, other "
        f"references; classification by parenthesis and brace heuristics with {CLASSIFY_LOOKAHEAD}"
        "-character lookahead, comments and strings "
        "are not excluded, not a compiler AST"
    )
    if count_truncated:
        scope += f"; counts beyond {max_occurrences} were not tallied"
    if scan_truncated:
        scope += f"; scan stopped after {scan_byte_budget} bytes"
    if summary:
        scope += f"; matches: {summary}"
    if counted > len(selected) or count_truncated:
        scope += f" (truncated by limit {limit})"
    skipped = report.note()
    if skipped:
        scope += f"; {skipped}"
    return RepositoryResult(matches=[item.location for item in selected], scope=scope)
