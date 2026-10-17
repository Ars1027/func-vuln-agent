"""#4 证据工具：搜索、按行读取、定义/调用定位与失败语义。

样例代码为人工编写，覆盖容量、长度来源、边界检查与跨函数调用路径。
"""

import pytest
from app.repository import RepositoryAdapters
from app.schemas.models import CourseSample
from app.schemas.ports import IntegrationError
from fake_git import FakeGit

COMMIT = "1" * 40
PARENT = "2" * 40
REPO = "https://github.com/acme/buf.git"
COMMIT_URL = f"https://github.com/acme/buf/commit/{COMMIT}"

BUF_C_LINES = [
    "#include <string.h>",
    '#include "buf.h"',
    "",
    "static size_t buffer_capacity = 64;",
    "",
    "void copy_into(char *dst, size_t cap, const char *src, size_t len) {",
    "    if (len > cap) {",
    "        return;",
    "    }",
    "    memcpy(dst, src, len);",
    "}",
    "",
    "void copy_unchecked(char *dst, const char *src, size_t len) {",
    "    memcpy(dst, src, len);",
    "}",
    "",
    "void copy_similar(char *dst, const char *src, size_t len) {",
    "    memcpy(dst, src, len); /* copy_into is not called here */",
    "}",
]
BUF_C = "\n".join(BUF_C_LINES) + "\n"
COPY_INTO = "\n".join(BUF_C_LINES[5:11])
HELPER_C = (
    "size_t remaining(size_t cap, size_t used) {\n"
    "    if (used > cap) return 0;\n"
    "    return cap - used;\n"
    "}\n"
    "\n"
    "void call_copy(char *dst, char *src, size_t len) {\n"
    "    copy_into(dst, MAX_BUF, src, len);\n"
    "}\n"
    "\n"
    "void check_then_change(char *dst, size_t cap, const char *src, size_t len) {\n"
    "    size_t used = remaining(cap, 0);\n"
    "    if (len > used) {\n"
    "        return;\n"
    "    }\n"
    "    used = len + 1;\n"
    "    copy_into(dst, used, src, len);\n"
    "}\n"
)
BUF_H = "#define MAX_BUF 64\nvoid copy_into(char *dst, size_t cap, const char *src, size_t len);\n"
README = "# 说明\n\ncopy_into 只出现在文档中，不应作为代码证据。\n"
ORDER_C = (
    "int use_capacity(void) {\n"
    "    capacity_check();\n"
    "    capacity_check();\n"
    "    return 0;\n"
    "}\n"
    "\n"
    "int capacity_check(void) { return 1; }\n"
)
CXX = "namespace N {\nint capacity = 8;\n}\n"

FILES = {
    "src/buf.c": BUF_C,
    "src/helper.c": HELPER_C,
    "src/buf.h": BUF_H,
    "src/order.c": ORDER_C,
    "src/cxx.cpp": CXX,
    ".hidden/util.c": "int hidden_helper(void) { return 1; }\n",
    "README.md": README,
    "assets/blob.bin": b"\x00\x01binary",
    "assets/latin1.c": b"int caf\xe9;\n",
}


def public_resolver(_host: str):
    return [(2, 1, 6, "", ("140.82.112.3", 443))]


def build_adapters(tmp_path, **kwargs):
    fake = FakeGit({REPO: {PARENT: FILES, COMMIT: FILES}}, {(REPO, COMMIT): [PARENT]})
    return RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver, **kwargs)


@pytest.fixture
async def snapshot(tmp_path):
    adapters = build_adapters(tmp_path)
    sample = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=COPY_INTO)
    )
    return adapters, sample.snapshot_ref


async def test_read_file_returns_source_lines_with_one_based_numbers(snapshot):
    adapters, ref = snapshot
    result = await adapters.read_file(ref, "src/buf.c", 7, 10)
    location = result.matches[0]

    assert (location.path, location.start_line, location.end_line) == ("src/buf.c", 7, 10)
    assert location.content == (
        "    if (len > cap) {\n        return;\n    }\n    memcpy(dst, src, len);"
    )
    assert "lines 7-10" in result.scope


async def test_read_file_clamps_end_line_and_records_it(snapshot):
    adapters, ref = snapshot
    result = await adapters.read_file(ref, "src/buf.c", 18, 500)
    assert result.matches[0].end_line == 19
    assert "file ends at line 19" in result.scope


@pytest.mark.parametrize(
    ("path", "start_line", "end_line", "code"),
    [
        ("src/missing.c", 1, 1, "file_not_found"),
        ("../outside.c", 1, 1, "invalid_path"),
        (".git/config", 1, 1, "invalid_path"),
        ("/etc/passwd", 1, 1, "invalid_path"),
        ("assets/blob.bin", 1, 1, "file_unreadable"),
        ("src/buf.c", 500, 501, "line_out_of_range"),
        ("src/buf.c", 0, 3, "invalid_line_range"),
    ],
)
async def test_read_failures_are_distinct_from_not_found(
    snapshot, path, start_line, end_line, code
):
    adapters, ref = snapshot
    with pytest.raises(IntegrationError) as failure:
        await adapters.read_file(ref, path, start_line, end_line)
    assert failure.value.code == code


async def test_read_range_limit_is_enforced(tmp_path):
    adapters = build_adapters(tmp_path / "limited", max_read_lines=2)
    sample = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=COPY_INTO)
    )
    with pytest.raises(IntegrationError) as limited:
        await adapters.read_file(sample.snapshot_ref, "src/buf.c", 1, 5)
    assert limited.value.code == "range_too_large"


async def test_search_code_locates_capacity_and_length_uses(snapshot):
    adapters, ref = snapshot
    result = await adapters.search_code(ref, "memcpy")
    lines = [(item.path, item.start_line, item.content) for item in result.matches]

    assert lines == [
        ("src/buf.c", 10, "    memcpy(dst, src, len);"),
        ("src/buf.c", 14, "    memcpy(dst, src, len);"),
        ("src/buf.c", 18, "    memcpy(dst, src, len); /* copy_into is not called here */"),
    ]
    assert "3 match(es)" in result.scope
    assert "README" not in result.scope


async def test_search_code_reports_no_match_without_failing(snapshot):
    adapters, ref = snapshot
    result = await adapters.search_code(ref, "not_present_token")
    assert result.matches == []
    assert "0 match(es)" in result.scope


async def test_search_code_truncates_and_reports_limit(tmp_path):
    adapters = build_adapters(tmp_path, search_limit=2)
    sample = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=COPY_INTO)
    )
    result = await adapters.search_code(sample.snapshot_ref, "memcpy")
    assert len(result.matches) == 2
    assert "truncated by limit 2" in result.scope


async def test_find_symbol_distinguishes_definition_declaration_and_calls(snapshot):
    adapters, ref = snapshot
    result = await adapters.find_symbol(ref, "copy_into")
    scope = result.scope

    assert result.matches[0].path == "src/buf.c"
    assert result.matches[0].start_line == 6
    assert "src/buf.c:6 definition" in scope
    assert "src/buf.h:2 declaration" in scope
    assert "src/helper.c:7 call" in scope
    assert "src/buf.c:18 reference" in scope
    assert "not a compiler AST" in scope


async def test_find_symbol_does_not_merge_similar_identifiers(snapshot):
    adapters, ref = snapshot
    result = await adapters.find_symbol(ref, "copy")
    assert result.matches == []


async def test_find_symbol_reports_macros_and_global_variables(snapshot):
    adapters, ref = snapshot
    macro = await adapters.find_symbol(ref, "MAX_BUF")
    assert "src/buf.h:1 macro" in macro.scope
    assert macro.matches[0].content == "#define MAX_BUF 64"

    global_variable = await adapters.find_symbol(ref, "buffer_capacity")
    assert "src/buf.c:4 definition" in global_variable.scope


async def test_find_symbol_follows_cross_file_call_path(snapshot):
    adapters, ref = snapshot
    result = await adapters.find_symbol(ref, "remaining")
    assert (result.matches[0].path, result.matches[0].start_line) == ("src/helper.c", 1)
    assert "definition" in result.scope


async def test_tools_locate_check_then_change_sequence(snapshot):
    adapters, ref = snapshot

    check = await adapters.search_code(ref, "if (len > used)")
    assert [(item.path, item.start_line) for item in check.matches] == [("src/helper.c", 12)]

    mutation = await adapters.search_code(ref, "used = len + 1;")
    assert (mutation.matches[0].path, mutation.matches[0].start_line) == ("src/helper.c", 15)

    body = await adapters.read_file(ref, "src/helper.c", 12, 16)
    assert "used = len + 1;" in body.matches[0].content
    assert "copy_into(dst, used, src, len);" in body.matches[0].content

    symbol = await adapters.find_symbol(ref, "remaining")
    assert "src/helper.c:11 call" in symbol.scope


async def test_find_symbol_rejects_invalid_names(snapshot):
    adapters, ref = snapshot
    with pytest.raises(IntegrationError) as invalid:
        await adapters.find_symbol(ref, "copy-into")
    assert invalid.value.code == "invalid_symbol"


async def test_hidden_directories_are_scanned(snapshot):
    adapters, ref = snapshot
    result = await adapters.find_symbol(ref, "hidden_helper")
    assert (result.matches[0].path, result.matches[0].start_line) == (".hidden/util.c", 1)


async def test_namespace_scope_variable_counts_as_definition(snapshot):
    adapters, ref = snapshot
    result = await adapters.find_symbol(ref, "capacity")
    assert "src/cxx.cpp:2 definition" in result.scope


async def test_definitions_survive_occurrence_cap(snapshot):
    from app.repository.locate import find_symbol as locate_symbol

    adapters, ref = snapshot
    result = locate_symbol(adapters.store, ref, "capacity_check", max_occurrences=1)
    assert (result.matches[0].path, result.matches[0].start_line) == ("src/order.c", 7)
    assert "definition" in result.scope
    assert "counts beyond 1 were not tallied" in result.scope


async def test_invalid_utf8_file_is_rejected(snapshot):
    adapters, ref = snapshot
    with pytest.raises(IntegrationError) as failure:
        await adapters.read_file(ref, "assets/latin1.c", 1, 1)
    assert failure.value.code == "file_unreadable"


async def test_scan_reports_files_skipped_by_size(tmp_path):
    adapters = build_adapters(tmp_path, max_file_bytes=40)
    sample = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=COPY_INTO)
    )
    result = await adapters.search_code(sample.snapshot_ref, "memcpy")
    assert result.matches == []
    assert "skipped" in result.scope and "oversized" in result.scope


@pytest.mark.parametrize("tool", ["search_code", "find_symbol"])
async def test_tools_reject_snapshot_refs_from_outside(snapshot, tool):
    adapters, _ref = snapshot
    argument = {"search_code": ("memcpy",), "find_symbol": ("copy_into",)}[tool]
    with pytest.raises(IntegrationError) as unknown:
        await getattr(adapters, tool)("snap-" + "f" * 16, *argument)
    assert unknown.value.code == "snapshot_not_found"
