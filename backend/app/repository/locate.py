"""文本级定位：函数原文定位、字面量搜索与符号定义/调用启发式分类。

这里不做编译器级语法分析：空白归一化后按原文匹配，行号来自原文偏移；
符号分类依据括号与花括号文本形态，注释和字符串不会被剔除。覆盖范围
写入 `RepositoryResult.scope`，由 Agent 判断证据与条件的关系。
"""

import re
import threading
from bisect import bisect_left
from collections.abc import Iterator
from dataclasses import dataclass

from app.repository.store import ScanReport, SnapshotStore, check_scan_cancelled
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
_LINE_SPLICE = r"\\\r?\n"
_PP_NUMBER = (
    rf"(?<![\w.])(?:[0-9]|\.(?:{_LINE_SPLICE})*[0-9])"
    rf"(?:(?:{_LINE_SPLICE})*(?:[eEpP](?:{_LINE_SPLICE})*[+-]|[\w.]|'(?:{_LINE_SPLICE})*\w))*"
)
_LEXEMES = re.compile(
    # C/C++ 先拼接反斜线换行；直接匹配原文，以保留物理行号和偏移。
    rf"(?P<comment>/(?:{_LINE_SPLICE})*(?:(?P<line_comment>/(?:{_LINE_SPLICE}|[^\n])*)|"
    rf"\*[\s\S]*?(?:\*(?:{_LINE_SPLICE})*/|$)))|"
    r"""(?:u8|u|U|L)?R"(?P<delimiter>[^\s()\\]{0,16})\([\s\S]*?\)(?P=delimiter)"|"""
    # 先消费完整 pp-number，避免数字分隔符配对成跨越函数的字符字面量。
    rf"(?P<number>{_PP_NUMBER})|"
    r""""(?:\\[\s\S]|[^"\\])*"|"""
    rf"(?:(?:u(?:{_LINE_SPLICE})*8|[uUL])(?:{_LINE_SPLICE})*)?'(?:\\[\s\S]|[^'\\])*'"
)
_DECLARATION_TOKENS = re.compile(
    _LEXEMES.pattern
    + rf"|(?P<splice>{_LINE_SPLICE})|(?P<newline>\n)"
    + rf"|(?P<code><(?:{_LINE_SPLICE})*%|%(?:{_LINE_SPLICE})*[>:]|\w+(?:{_LINE_SPLICE}\w+)*|[^\s])"
)
_ALTERNATIVE_PUNCTUATORS = {"<%": "{", "%>": "}", "%:": "#"}
CLASSIFY_LOOKAHEAD = 400


def _directive_line_ends(
    text: str, *, cancel_event: threading.Event | None = None
) -> Iterator[int]:
    """产出预处理指令终止换行；注释、字面量和续行中的换行不结束逻辑行。"""
    logical_start = True
    directive = False
    next_cancel_check = 0
    for token in _DECLARATION_TOKENS.finditer(text):
        if cancel_event is not None and token.start() >= next_cancel_check:
            check_scan_cancelled(cancel_event)
            next_cancel_check = token.start() + 4096
        if token.group("comment") is not None or token.group("splice") is not None:
            continue
        if token.group("newline") is not None:
            if directive:
                yield token.start()
            logical_start = True
            directive = False
            continue
        value = token.group().replace("\\\r\n", "").replace("\\\n", "")
        if token.start() == 0 and value == "\ufeff":
            continue
        if logical_start and _ALTERNATIVE_PUNCTUATORS.get(value, value) == "#":
            directive = True
        logical_start = False


def normalize_whitespace(
    text: str,
    *,
    preserve_logical_lines: bool = False,
    cancel_event: threading.Event | None = None,
) -> tuple[str, list[int]]:
    """折叠字面量外空白；函数比较保留行注释和预处理指令的终止换行。"""
    check_scan_cancelled(cancel_event)
    characters: list[str] = []
    offsets: list[int] = []
    previous_space = False
    lexemes = _LEXEMES.finditer(text)
    lexeme = next(lexemes, None)
    line_comment_end = None
    directive_ends = (
        _directive_line_ends(text, cancel_event=cancel_event)
        if preserve_logical_lines
        else iter(())
    )
    directive_end = next(directive_ends, None)
    for offset, character in enumerate(text):
        if cancel_event is not None and offset % 4096 == 0:
            check_scan_cancelled(cancel_event)
        while directive_end is not None and directive_end < offset:
            directive_end = next(directive_ends, None)
        while lexeme is not None and offset >= lexeme.end():
            line_comment_end = lexeme.end() if lexeme.group("line_comment") is not None else None
            lexeme = next(lexemes, None)
        in_literal = (
            lexeme is not None
            and lexeme.group("comment") is None
            and lexeme.group("number") is None
            and lexeme.start() <= offset < lexeme.end()
        )
        if (
            preserve_logical_lines
            and character == "\n"
            and offset in (line_comment_end, directive_end)
        ):
            if previous_space:
                characters[-1] = "\n"
                offsets[-1] = offset
            else:
                characters.append("\n")
                offsets.append(offset)
            previous_space = True
            continue
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
    while end > start and characters[end - 1] in {" ", "\n"}:
        end -= 1
    check_scan_cancelled(cancel_event)
    return "".join(characters[start:end]), offsets[start:end]


def _line_number(text: str, offset: int) -> int:
    return text.count("\n", 0, offset) + 1


def _expand_lines(text: str, start: int, end: int) -> tuple[int, int, str]:
    """把匹配偏移扩展为完整行区间，保证内容与原文逐行一致。"""
    start_line = _line_number(text, start)
    end_line = _line_number(text, max(end - 1, start))
    lines = text.replace("\r\n", "\n").split("\n")
    return start_line, end_line, "\n".join(lines[start_line - 1 : end_line])


def iter_matches(
    text: str,
    needle: str,
    *,
    code_offset: int | None = None,
    cancel_event: threading.Event | None = None,
) -> Iterator[tuple[int, int]]:
    """按原文偏移逐个产出匹配，避免为高频词一次性分配全部结果。"""
    haystack, offsets = normalize_whitespace(
        text, preserve_logical_lines=code_offset is not None, cancel_event=cancel_event
    )
    starts = (
        _declaration_starts(text, cancel_event=cancel_event)
        if code_offset is not None
        else iter(())
    )
    declaration_start = next(starts, None)
    position = haystack.find(needle)
    while position != -1:
        check_scan_cancelled(cancel_event)
        start = offsets[position]
        end = offsets[position + len(needle) - 1] + 1
        valid_start = True
        if code_offset is not None:
            code_start = offsets[position + code_offset]
            while declaration_start is not None and declaration_start < code_start:
                declaration_start = next(starts, None)
            valid_start = declaration_start == code_start
        if valid_start:
            yield start, end
        position = haystack.find(needle, position + len(needle))


def _declaration_starts(text: str, *, cancel_event: threading.Event | None = None) -> Iterator[int]:
    """单次词法扫描声明起点；换行、注释和预处理指令不截断声明前缀。"""
    boundary = True
    depth = 0
    parameter_lists: list[bool] = []
    braces: list[tuple[bool, bool]] = []
    type_definition = False
    function_declarator = False
    requires_expression = False
    requires_parameters = False
    directive = False
    previous = ""
    next_cancel_check = 0
    for token in _DECLARATION_TOKENS.finditer(text):
        if cancel_event is not None and token.start() >= next_cancel_check:
            check_scan_cancelled(cancel_event)
            next_cancel_check = token.start() + 4096
        if token.group("comment") is not None or token.group("splice") is not None:
            continue
        value = token.group().replace("\\\r\n", "").replace("\\\n", "")
        value = _ALTERNATIVE_PUNCTUATORS.get(value, value)
        if token.start() == 0 and value == "\ufeff":
            continue
        if token.group("newline") is not None:
            directive = False
            continue
        if value == "#":
            if boundary:
                yield token.start()
            directive = True
            continue
        if directive:
            continue
        if boundary and token.group("code") is not None:
            yield token.start()
        expression_brace = False
        type_brace = False
        closes_requires_parameters = False
        if value == "(":
            if depth == 0 and previous not in {
                "__attribute__",
                "__attribute",
                "__declspec",
                "alignas",
                "_Alignas",
            }:
                function_declarator = True
            parameter_lists.append(previous == "requires" and requires_expression)
            depth += 1
        elif value == "[":
            depth += 1
        elif value == ")":
            closes_requires_parameters = parameter_lists.pop() if parameter_lists else False
            depth = max(0, depth - 1)
        elif value == "]":
            depth = max(0, depth - 1)
        elif value == "{":
            # requires 表达式（含可选参数表）仍属于当前声明；其内部不是新函数起点。
            expression_brace = depth > 0 or previous == "requires" or requires_parameters
            type_brace = not expression_brace and type_definition and not function_declarator
            braces.append((expression_brace, type_brace))
            depth += expression_brace
        elif value == "}":
            expression_brace, type_brace = braces.pop() if braces else (False, False)
            depth = max(0, depth - expression_brace)
        if depth == 0 and value in {"struct", "class", "union", "enum"}:
            type_definition = True
        boundary = (
            depth == 0
            and not expression_brace
            and not (value == "}" and type_brace)
            and (
                value in {";", "{", "}"}
                or (value == ":" and previous in {"public", "protected", "private"})
            )
        )
        if boundary or (value == "}" and type_brace):
            type_definition = False
            function_declarator = False
        # 区分 requires 子句的约束括号与 requires 表达式的参数表。
        requires_expression = value == "requires" and previous in {
            "requires",
            "(",
            "=",
            "&",
            "|",
            "!",
            "and",
            "or",
            "not",
        }
        requires_parameters = closes_requires_parameters
        previous = value


def _first_code_offset(text: str) -> int | None:
    offset = 0
    while offset < len(text):
        if text[offset].isspace():
            offset += 1
            continue
        lexeme = _LEXEMES.match(text, offset)
        if lexeme is None or lexeme.group("comment") is None:
            return offset
        offset = lexeme.end()
    return None


def locate_function(
    store: SnapshotStore,
    snapshot_ref: str,
    func: str,
    *,
    report: ScanReport | None = None,
    cancel_event: threading.Event | None = None,
) -> CodeLocation:
    """在快照中定位待测函数的相对路径与原始行号。"""
    needle, offsets = normalize_whitespace(
        func, preserve_logical_lines=True, cancel_event=cancel_event
    )
    first_code = _first_code_offset(func)
    if not needle or first_code is None:
        raise IntegrationError("function_not_found", "待测函数不包含代码，无法在快照中定位。")
    code_offset = bisect_left(offsets, first_code)
    scan = report if report is not None else ScanReport()
    found: list[CodeLocation] = []
    for entry in store.iter_files(
        snapshot_ref, max_bytes=MAX_SCAN_BYTES, report=scan, cancel_event=cancel_event
    ):
        check_scan_cancelled(cancel_event)
        for start, end in iter_matches(
            entry.text, needle, code_offset=code_offset, cancel_event=cancel_event
        ):
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
    check_scan_cancelled(cancel_event)
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
    cancel_event: threading.Event | None = None,
) -> RepositoryResult:
    """在快照的 C/C++ 源文件内做字面量搜索，返回完整行区间。"""
    needle, _ = normalize_whitespace(query, cancel_event=cancel_event)
    if not needle:
        raise IntegrationError("empty_query", "搜索内容不能为空。")
    report = ScanReport()
    matches: list[CodeLocation] = []
    seen: set[tuple[str, int, int]] = set()
    total = 0
    truncated = False
    locations_truncated = False
    for entry in store.iter_files(
        snapshot_ref, max_bytes=max_file_bytes, report=report, cancel_event=cancel_event
    ):
        line, cursor = 1, 0
        for start, end in iter_matches(entry.text, needle, cancel_event=cancel_event):
            if total >= match_budget:
                truncated = True
                break
            total += 1
            line += entry.text.count("\n", cursor, start)
            cursor = start
            last_line = line + entry.text.count("\n", start, max(end - 1, start))
            key = (entry.path, line, last_line)
            if key in seen:
                continue
            if len(matches) >= limit:
                locations_truncated = True
                continue
            seen.add(key)
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
    check_scan_cancelled(cancel_event)
    scope = (
        f"case-sensitive literal text search (whitespace-normalized) over "
        f"{report.scanned} C/C++ files; {total}{'+' if truncated else ''} match(es), "
        f"returning {len(matches)} distinct location(s)"
    )
    if truncated:
        scope += f"; match counting stopped at budget {match_budget}"
    elif locations_truncated:
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
    header = _LEXEMES.sub(
        lambda match: " " if match.group("comment") is not None else match.group(), header
    )
    header = header[header.rfind(";") + 1 :]
    stripped = header.rstrip()
    if not stripped:
        return "block"
    if _SCOPE_OPENERS.search(stripped) and not stripped.endswith(")"):
        return "scope"
    if re.search(r'\bextern\s*"C(?:\+\+)?"\s*$', stripped):
        return "scope"
    if stripped.endswith(")"):
        return "function"
    if "=" in stripped:
        return "initializer"
    return "block"


def _symbol_contexts(
    text: str, matches: Iterator[re.Match], *, cancel_event: threading.Event | None = None
) -> Iterator[tuple[re.Match, bool, int]]:
    """按符号位置向前扫描一次，避免对每次出现重新扫描整个文件前缀。"""
    stack: list[bool] = []
    non_global = 0
    index = 0
    line_start = 0
    lexemes = _LEXEMES.finditer(text)
    lexeme = next(lexemes, None)
    next_cancel_check = 0
    for match in matches:
        check_scan_cancelled(cancel_event)
        while index < match.start():
            if cancel_event is not None and index >= next_cancel_check:
                check_scan_cancelled(cancel_event)
                next_cancel_check = index + 4096
            while lexeme is not None and lexeme.end() <= index:
                lexeme = next(lexemes, None)
            if lexeme is not None and lexeme.start() <= index < lexeme.end():
                end = min(lexeme.end(), match.start())
                newline = text.rfind("\n", index, end)
                if newline != -1:
                    line_start = newline + 1
                index = end
                continue
            character = text[index]
            if character == "\n":
                line_start = index + 1
            if character == "{":
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


def _mask_non_code(text: str) -> str:
    """屏蔽注释与字符串/字符内容，保留数值代码及原始偏移。"""
    return _LEXEMES.sub(
        lambda match: (
            match.group() if match.group("number") is not None else " " * len(match.group())
        ),
        text,
    )


def _has_variable_initializer(after: str) -> bool:
    """跳过当前声明符的数组维度，只在其后判断初始化，避免混入同句的其他变量。"""
    depth = 0
    for character in _mask_non_code(after):
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        elif depth == 0 and not character.isspace():
            return character in "={"
    return False


def _direct_extern_initializer(header: str) -> bool:
    """识别 extern 变量的直接列表初始化，排除带括号的函数声明头。"""
    if not re.search(r"\bextern\b", header):
        return False
    depth = 0
    outside_arrays: list[str] = []
    for character in header:
        if character == "[":
            depth += 1
        elif character == "]":
            depth -= 1
        elif depth == 0:
            outside_arrays.append(character)
    declarator = "".join(outside_arrays).rsplit(",", 1)[-1].strip()
    declarator = re.split(r"[;{}]", declarator)[-1].strip()
    return not re.search(r"[()]", declarator) and bool(
        re.search(r"\b[A-Za-z_][A-Za-z0-9_]*$", declarator)
    )


def _variable_prefix(text: str, offset: int) -> str:
    """只在有界窗口内回溯当前声明，跨过初始化列表但不跨越作用域边界。"""
    source = text[max(0, offset - CLASSIFY_LOOKAHEAD) : offset]
    prefix = _mask_non_code(source)
    index = len(prefix) - 1
    while index >= 0:
        if prefix[index] in ";{":
            return prefix[index + 1 :]
        if prefix[index] != "}":
            index -= 1
            continue
        closing, depth = index, 1
        while index > 0 and depth:
            index -= 1
            if prefix[index] == "}":
                depth += 1
            elif prefix[index] == "{":
                depth -= 1
        if depth:
            return prefix[closing + 1 :]
        boundary = max(prefix.rfind(mark, 0, index) for mark in ";{}") + 1
        header = source[boundary:index]
        kind = _opener_kind(header, len(header))
        if kind != "initializer" and not (
            kind == "block" and _direct_extern_initializer(prefix[:index])
        ):
            return prefix[closing + 1 :]
        # 初始化器里的 extern 等内容不属于当前声明的存储类。
        prefix = prefix[:index] + " " * (closing - index + 1) + prefix[closing + 1 :]
        index -= 1
    return prefix


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
    stripped = _mask_non_code(after).lstrip()
    if stripped[:1] in {"=", ";", "[", "{", ","} and global_scope:
        prefix = _variable_prefix(text, offset)
        if re.search(r"\bextern\b", prefix) and not _has_variable_initializer(after):
            return "declaration"
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
    cancel_event: threading.Event | None = None,
) -> RepositoryResult:
    """按标识符定位定义、宏、声明与调用位置。"""
    check_scan_cancelled(cancel_event)
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
        raise IntegrationError("invalid_symbol", "符号名称必须是单个 C/C++ 标识符。")
    pattern = re.compile(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])")
    report = ScanReport()
    buckets: dict[int, list[SymbolMatch]] = {rank: [] for rank in set(_RANK.values())}
    seen: dict[int, set[tuple[str, int, int]]] = {rank: set() for rank in buckets}
    counted = 0
    scanned_bytes = 0
    count_truncated = False
    scan_truncated = False
    locations_truncated = False
    for entry in store.iter_files(
        snapshot_ref, max_bytes=max_file_bytes, report=report, cancel_event=cancel_event
    ):
        scanned_bytes += entry.size
        if scanned_bytes > scan_byte_budget:
            scan_truncated = True
            break
        line, cursor = 1, 0
        for match, global_scope, line_start in _symbol_contexts(
            entry.text, pattern.finditer(entry.text), cancel_event=cancel_event
        ):
            if counted >= max_occurrences:
                count_truncated = True
            else:
                counted += 1
            kind = _classify(
                entry.text, match.start(), symbol, global_scope=global_scope, line_start=line_start
            )
            rank = _RANK[kind]
            bucket = buckets[rank]
            line += entry.text.count("\n", cursor, match.start())
            cursor = match.start()
            key = (entry.path, line, line)
            if key in seen[rank]:
                continue
            if len(bucket) >= limit:
                locations_truncated = True
                continue
            seen[rank].add(key)
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
    check_scan_cancelled(cancel_event)
    candidates = [item for bucket in buckets.values() for item in bucket]
    candidates.sort(
        key=lambda item: (_RANK[item.kind], item.location.path, item.location.start_line)
    )
    distinct: dict[tuple[str, int, int], SymbolMatch] = {}
    for item in candidates:
        location = item.location
        distinct.setdefault((location.path, location.start_line, location.end_line), item)
    selected = list(distinct.values())[:limit]
    locations_truncated |= len(distinct) > limit
    summary = ", ".join(
        f"{item.location.path}:{item.location.start_line} {item.kind}" for item in selected[:8]
    )
    scope = (
        f"text-level identifier scan over {report.scanned} C/C++ files; "
        f"{counted}{'+' if count_truncated or scan_truncated else ''} occurrence(s), "
        f"returning {len(selected)} distinct location(s); "
        "order: definitions/macros, declarations, calls, other "
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
    if locations_truncated:
        scope += f" (truncated by limit {limit})"
    skipped = report.note()
    if skipped:
        scope += f"; {skipped}"
    return RepositoryResult(matches=[item.location for item in selected], scope=scope)
