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
    "src/traits.tcc": "int template_value(void) { return 1; }\n",
    "include/ext_header": ("#define EXT_HELPER 1\nint ext_helper(void) { return EXT_HELPER; }\n"),
    "LICENSE": "Copyright text without C directives.\n",
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


async def test_extended_and_extensionless_sources_are_scanned(snapshot):
    adapters, ref = snapshot
    template = await adapters.find_symbol(ref, "template_value")
    assert (template.matches[0].path, template.matches[0].start_line) == ("src/traits.tcc", 1)

    extensionless = await adapters.find_symbol(ref, "ext_helper")
    assert (extensionless.matches[0].path, extensionless.matches[0].start_line) == (
        "include/ext_header",
        2,
    )


async def test_symbol_scan_budget_reports_byte_limit(snapshot):
    from app.repository.locate import find_symbol as locate_symbol

    adapters, ref = snapshot
    result = locate_symbol(adapters.store, ref, "capacity", scan_byte_budget=5)
    assert "scan stopped after 5 bytes" in result.scope


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


async def test_read_file_enforces_bytes_even_for_one_long_line(tmp_path):
    fake = FakeGit({REPO: {COMMIT: {"a.c": "int f(void) { return 1; }\n", "long.c": "x" * 1000}}})
    adapters = RepositoryAdapters(
        tmp_path / "storage", git=fake, resolver=public_resolver, max_file_bytes=100
    )
    prepared = await adapters.prepare_course(
        CourseSample(
            idx=1,
            func="int f(void) { return 1; }",
            commit_url=COMMIT_URL,
            target=0,
        )
    )
    with pytest.raises(IntegrationError) as failure:
        await adapters.read_file(prepared.snapshot_ref, "long.c", 1, 1)
    assert failure.value.code == "file_too_large"


@pytest.mark.parametrize("separator", ["\f", "\v", "\r", "\u0085", "\u2028", "\u2029"])
async def test_location_and_file_reads_use_the_same_lf_lines(tmp_path, separator):
    func = "int f(void) { return 1; }"
    fake = FakeGit({REPO: {COMMIT: {"a.c": f"/* before{separator}still same line */\n{func}\n"}}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            target=0,
        )
    )
    location = await adapters.locate_function(prepared.snapshot_ref, func)
    read = await adapters.read_file(prepared.snapshot_ref, "a.c", 2, 2)
    assert location.start_line == location.end_line == 2
    assert location.content == read.matches[0].content == func


async def test_symbol_ranking_keeps_calls_and_declarations_after_references(tmp_path):
    from app.repository.locate import find_symbol

    func = "int entry(void) { return 1; }"
    text = "/* needle */\n/* needle */\nvoid needle(void);\nvoid caller(void) { needle(); }\n"
    fake = FakeGit({REPO: {COMMIT: {"a.c": text + func}}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            target=0,
        )
    )
    result = find_symbol(adapters.store, prepared.snapshot_ref, "needle", limit=2)
    assert [match.start_line for match in result.matches] == [3, 4]
    assert "a.c:3 declaration" in result.scope and "a.c:4 call" in result.scope


async def test_symbol_scopes_are_scanned_once_even_after_count_cap(tmp_path, monkeypatch):
    from app.repository import locate

    func = "int entry(void) { return 1; }"
    text = "namespace N {\n" + "int capacity;\n" * 1000 + "}\n" + func
    fake = FakeGit({REPO: {COMMIT: {"a.cpp": text}}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            target=0,
        )
    )
    original = locate._opener_kind
    openings = []

    def count_opener(source, offset):
        openings.append(offset)
        return original(source, offset)

    monkeypatch.setattr(locate, "_opener_kind", count_opener)
    result = locate.find_symbol(
        adapters.store, prepared.snapshot_ref, "capacity", max_occurrences=3
    )
    assert len(openings) == 1
    assert "3+ occurrence(s)" in result.scope
    assert "definition" in result.scope


async def test_search_returns_distinct_locations_but_counts_all_occurrences(tmp_path):
    from app.repository.locate import search_code

    func = "int entry(void) { return 1; }"
    files = {"a.c": "/* needle needle needle */\nneedle();\n" + func, "b.c": "needle();\n"}
    fake = FakeGit({REPO: {COMMIT: files}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            target=0,
        )
    )
    result = search_code(adapters.store, prepared.snapshot_ref, "needle", limit=3)
    assert [(item.path, item.start_line, item.end_line) for item in result.matches] == [
        ("a.c", 1, 1),
        ("a.c", 2, 2),
        ("b.c", 1, 1),
    ]
    assert "5 match(es)" in result.scope
    assert "truncated by limit" not in result.scope

    limited = search_code(adapters.store, prepared.snapshot_ref, "needle", limit=2)
    assert [item.start_line for item in limited.matches] == [1, 2]
    assert "truncated by limit 2" in limited.scope


async def test_search_deduplication_preserves_multiline_ranges_and_match_budget(tmp_path):
    from app.repository.locate import search_code

    func = "int entry(void) { return 1; }"
    text = "foo\nbar foo\nbar\nfoo\nbar\n" + func
    fake = FakeGit({REPO: {COMMIT: {"a.c": text}}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            target=0,
        )
    )
    result = search_code(adapters.store, prepared.snapshot_ref, "foo bar", limit=3)
    assert [(item.start_line, item.end_line) for item in result.matches] == [(1, 2), (2, 3), (4, 5)]
    bounded = search_code(adapters.store, prepared.snapshot_ref, "foo bar", match_budget=1)
    assert len(bounded.matches) == 1
    assert "1+ match(es)" in bounded.scope
    assert "match counting stopped at budget 1" in bounded.scope


_TOOL_ARGUMENTS = {
    "locate_function": (COPY_INTO,),
    "search_code": ("missing_token",),
    "find_symbol": ("missing_symbol",),
    "read_file": ("src/buf.c", 1, 1),
}


@pytest.mark.parametrize("tool", _TOOL_ARGUMENTS)
@pytest.mark.parametrize("timeout", [False, True])
async def test_cancelled_repository_tool_exits_before_await_returns(
    snapshot, monkeypatch, timeout, tool
):
    import asyncio
    import threading

    adapters, ref = snapshot
    started, stopped, stop_test = threading.Event(), threading.Event(), threading.Event()
    observed = []

    def paused_files(*args, cancel_event=None, **kwargs):
        observed.append(cancel_event)
        started.set()
        try:
            while not stop_test.wait(0.005):
                if cancel_event is not None and cancel_event.is_set():
                    break
            return (["source"], 1, False) if tool == "read_file" else []
        finally:
            stopped.set()

    monkeypatch.setattr(
        adapters.store, "read_lines" if tool == "read_file" else "iter_files", paused_files
    )

    deadline = asyncio.timeout(None)

    async def locate():
        if timeout:
            async with deadline:
                return await getattr(adapters, tool)(ref, *_TOOL_ARGUMENTS[tool])
        return await getattr(adapters, tool)(ref, *_TOOL_ARGUMENTS[tool])

    task = asyncio.create_task(locate())
    try:
        assert await asyncio.to_thread(started.wait, 2)
        if timeout:
            deadline.reschedule(asyncio.get_running_loop().time())
        else:
            task.cancel()
        with pytest.raises(TimeoutError if timeout else asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert observed[0] is not None and observed[0].is_set()
        assert stopped.is_set()
    finally:
        stop_test.set()
        assert await asyncio.to_thread(stopped.wait, 2)


@pytest.mark.parametrize("tool", _TOOL_ARGUMENTS)
async def test_repeated_cancellation_waits_for_repository_cleanup(snapshot, monkeypatch, tool):
    import asyncio
    import threading

    adapters, ref = snapshot
    started, cancelled, release, stopped = (threading.Event() for _ in range(4))

    def paused_files(*args, cancel_event=None, **kwargs):
        started.set()
        try:
            while not release.wait(0.005):
                if cancel_event is not None and cancel_event.is_set():
                    cancelled.set()
            return (["source"], 1, False) if tool == "read_file" else []
        finally:
            stopped.set()

    monkeypatch.setattr(
        adapters.store, "read_lines" if tool == "read_file" else "iter_files", paused_files
    )
    task = asyncio.create_task(getattr(adapters, tool)(ref, *_TOOL_ARGUMENTS[tool]))
    try:
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        assert await asyncio.to_thread(cancelled.wait, 2)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 2)
        assert stopped.is_set()
    finally:
        release.set()
        assert await asyncio.to_thread(stopped.wait, 2)


def test_function_text_normalization_checks_cancellation_during_work():
    import threading

    from app.repository.locate import normalize_whitespace

    class CancelDuringWork(threading.Event):
        def __init__(self):
            super().__init__()
            self.checks = 0

        def is_set(self):
            self.checks += 1
            if self.checks == 3:
                self.set()
            return super().is_set()

    cancel = CancelDuringWork()
    with pytest.raises(IntegrationError) as failure:
        normalize_whitespace("x" * 20_000, cancel_event=cancel)
    assert failure.value.code == "repository_cancelled"


async def test_symbol_results_are_distinct_before_rank_limits(tmp_path):
    from app.repository.locate import find_symbol

    func = "int entry(void) { return 1; }"
    files = {
        "a.c": "void first(void) { " + "needle(); " * 20 + "}\n" + func,
        "b.c": "void second(void) { needle(); }\n",
        "c.c": "void third(void) { needle(); }\n",
    }
    fake = FakeGit({REPO: {COMMIT: files}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(idx=1, func=func, commit_url=COMMIT_URL, target=0)
    )
    result = find_symbol(adapters.store, prepared.snapshot_ref, "needle", limit=3)
    assert [(match.path, match.start_line) for match in result.matches] == [
        ("a.c", 1),
        ("b.c", 1),
        ("c.c", 1),
    ]
    assert "22 occurrence(s)" in result.scope
    assert "truncated by limit" not in result.scope

    limited = find_symbol(adapters.store, prepared.snapshot_ref, "needle", limit=2)
    assert [match.path for match in limited.matches] == ["a.c", "b.c"]
    assert "truncated by limit 2" in limited.scope


async def test_symbol_results_keep_highest_kind_for_one_location(tmp_path):
    func = "int entry(void) { return 1; }"
    text = "extern int needle; int needle = 1; /* needle */\n" + func
    fake = FakeGit({REPO: {COMMIT: {"a.c": text}}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(idx=1, func=func, commit_url=COMMIT_URL, target=0)
    )
    result = await adapters.find_symbol(prepared.snapshot_ref, "needle")
    assert len(result.matches) == 1
    assert "a.c:1 definition" in result.scope
    assert "3 occurrence(s)" in result.scope
    assert "truncated by limit" not in result.scope


@pytest.mark.parametrize(
    ("declaration", "kind"),
    [
        ("extern int needle;", "declaration"),
        ("extern int\nneedle;", "declaration"),
        ("extern int needle[8];", "declaration"),
        ("extern int needle[2][4];", "declaration"),
        ("extern int other = 1, needle;", "declaration"),
        ("extern int needle, other;", "declaration"),
        ("extern int needle /* note */;", "declaration"),
        ("extern int needle /* note */ = 1;", "definition"),
        ("extern int other{1}, needle;", "declaration"),
        ("extern int other[] = {1}, needle;", "declaration"),
        ("extern int other[sizeof(int)]{1}, needle;", "declaration"),
        ("extern int first{f()}, other{2}, needle;", "declaration"),
        ("namespace N { extern int other{1}, needle; }", "declaration"),
        ("extern int f() {} int needle;", "definition"),
        ("extern int f() noexcept {} int needle;", "definition"),
        ('extern "C" { int f(); } int needle;', "definition"),
        ("int other = [] { extern int nested; return 1; }(), needle;", "definition"),
        ("extern int needle = 1;", "definition"),
        ("extern int needle[8] = {1};", "definition"),
        ("extern int needle[limits[0]] = {1};", "definition"),
        ("extern int needle{1};", "definition"),
        ("extern int needle[]{1, 2};", "definition"),
        ('extern "C" { int needle; }', "definition"),
        ('namespace N { extern "C++" { extern int needle; } }', "declaration"),
        ("/* extern */ int needle;", "definition"),
        ('const char *note = "extern"; int needle;', "definition"),
    ],
)
async def test_symbol_storage_class_and_initializer_are_classified(tmp_path, declaration, kind):
    func = "int entry(void) { return 1; }"
    fake = FakeGit({REPO: {COMMIT: {"a.cpp": declaration + "\n" + func}}})
    adapters = RepositoryAdapters(tmp_path / "storage", git=fake, resolver=public_resolver)
    prepared = await adapters.prepare_course(
        CourseSample(idx=1, func=func, commit_url=COMMIT_URL, target=0)
    )
    result = await adapters.find_symbol(prepared.snapshot_ref, "needle")
    assert len(result.matches) == 1
    line = declaration.count("\n") + 1
    assert f"a.cpp:{line} {kind}" in result.scope


@pytest.mark.parametrize("prefix", [" " * 20_000, '"' + r"\a" * 10_000 + '" '])
def test_symbol_context_checks_cancellation_during_long_scan(prefix):
    import re
    import threading

    from app.repository.locate import _symbol_contexts

    class CancelDuringScan(threading.Event):
        checks = 0

        def is_set(self):
            self.checks += 1
            if self.checks == 3:
                self.set()
            return super().is_set()

    text = prefix + "needle"
    with pytest.raises(IntegrationError) as failure:
        list(_symbol_contexts(text, re.finditer("needle", text), cancel_event=CancelDuringScan()))
    assert failure.value.code == "repository_cancelled"
