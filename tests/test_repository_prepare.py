"""#3 快照准备的版本选择、隔离与失败路径。

仓库内容为人工编写的合成样例；真实效果以课程数据评测为准。
"""

import pytest
from app.repository import RepositoryAdapters
from app.repository.urls import parse_commit_url
from app.schemas.models import CourseSample, SnapshotRequest
from app.schemas.ports import IntegrationError
from fake_git import FakeGit

COMMIT = "1" * 40
PARENT = "2" * 40
EXTRA = "3" * 40
REPO = "https://github.com/acme/buf.git"
COMMIT_URL = f"https://github.com/acme/buf/commit/{COMMIT}"

BUGGY_FUNC = (
    "void copy_into(char *dst, const char *src, size_t len) {\n    memcpy(dst, src, len);\n}"
)
CHECKED_FUNC = (
    "void copy_into(char *dst, size_t cap, const char *src, size_t len) {\n"
    "    if (len > cap) {\n"
    "        return;\n"
    "    }\n"
    "    memcpy(dst, src, len);\n"
    "}"
)
PARENT_FILES = {"src/buf.c": "#include <string.h>\n\n" + BUGGY_FUNC + "\n"}
FIXED_FILES = {
    "src/buf.c": "#include <string.h>\n\n" + CHECKED_FUNC + "\n",
    "src/fixed_only.c": "int fixed_marker;\n",
}


def public_resolver(_host: str):
    return [(2, 1, 6, "", ("140.82.112.3", 443))]


def build_fake(parents=None):
    repositories = {REPO: {PARENT: PARENT_FILES, COMMIT: FIXED_FILES}}
    return FakeGit(repositories, parents if parents is not None else {(REPO, COMMIT): [PARENT]})


def build_adapters(tmp_path, fake=None, resolver=public_resolver, **kwargs):
    return RepositoryAdapters(
        tmp_path / "storage", git=fake or build_fake(), resolver=resolver, **kwargs
    )


async def test_course_target_and_explicit_revision_select_single_version(tmp_path):
    adapters = build_adapters(tmp_path)
    buggy = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
    )
    fixed = await adapters.prepare_course(
        CourseSample(idx=0, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
    )

    assert buggy.snapshot_ref != fixed.snapshot_ref
    assert adapters.store.metadata(buggy.snapshot_ref)["commit"] == PARENT
    assert adapters.store.metadata(fixed.snapshot_ref)["commit"] == COMMIT

    parent_revision = await adapters.prepare_snapshot(
        SnapshotRequest(idx="w1", func=BUGGY_FUNC, commit_url=COMMIT_URL, revision="parent")
    )
    commit_revision = await adapters.prepare_snapshot(
        SnapshotRequest(idx="w2", func=CHECKED_FUNC, commit_url=COMMIT_URL, revision="commit")
    )
    assert parent_revision.snapshot_ref == buggy.snapshot_ref
    assert commit_revision.snapshot_ref == fixed.snapshot_ref


async def test_prepared_input_keeps_identity_and_hides_selection(tmp_path):
    adapters = build_adapters(tmp_path)
    sample = await adapters.prepare_course(
        CourseSample(idx="7", commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
    )

    assert sample.idx == "7" and type(sample.idx) is str
    assert sample.func == BUGGY_FUNC
    assert set(sample.model_dump()) == {"idx", "func", "snapshot_ref"}
    assert sample.snapshot_ref.startswith("snap-")
    for secret in (COMMIT, PARENT, "acme/buf", "commit_url", "target", "parent"):
        assert secret not in sample.model_dump_json()


async def test_snapshot_tree_has_no_git_metadata_or_selection_data(tmp_path):
    adapters = build_adapters(tmp_path)
    sample = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
    )
    root = adapters.store.snapshot_dir(sample.snapshot_ref)

    names = {path.name.casefold() for path in root.rglob("*")}
    assert ".git" not in names
    assert "commit" not in names
    assert (adapters.store.refs / f"{sample.snapshot_ref}.json").is_file()
    assert adapters.store.refs not in root.parents


async def test_locate_function_returns_relative_path_and_source_lines(tmp_path):
    adapters = build_adapters(tmp_path)
    sample = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
    )

    location = await adapters.locate_function(sample.snapshot_ref, BUGGY_FUNC)
    assert location.snapshot_ref == sample.snapshot_ref
    assert location.path == "src/buf.c"
    assert (location.start_line, location.end_line) == (3, 5)
    assert location.content == BUGGY_FUNC


async def test_cached_snapshot_does_not_require_dns(tmp_path):
    calls: list[str] = []

    def resolver(host: str):
        calls.append(host)
        if len(calls) > 1:
            raise OSError("dns unavailable")
        return public_resolver(host)

    adapters = build_adapters(tmp_path, resolver=resolver)
    sample = CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
    first = await adapters.prepare_course(sample)
    second = await adapters.prepare_course(sample)

    assert second.snapshot_ref == first.snapshot_ref
    assert calls == ["github.com"]


async def test_repeated_preparation_reuses_materialized_snapshot(tmp_path):
    fake = build_fake()
    adapters = build_adapters(tmp_path, fake)
    for _ in range(2):
        await adapters.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
        )
    assert len(fake.exported) == 1


async def test_fetch_pins_verified_public_addresses(tmp_path):
    fake = build_fake()
    adapters = build_adapters(tmp_path, fake)
    await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
    )

    assert fake.fetch_options
    assert any(
        "http.curloptResolve=github.com:443:140.82.112.3" in option
        for option in fake.fetch_options[0]
    )


async def test_snapshots_are_isolated_from_each_other(tmp_path):
    adapters = build_adapters(tmp_path)
    buggy = await adapters.prepare_course(
        CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
    )
    fixed = await adapters.prepare_course(
        CourseSample(idx=0, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
    )

    with pytest.raises(IntegrationError) as missing:
        await adapters.read_file(buggy.snapshot_ref, "src/fixed_only.c", 1, 1)
    assert missing.value.code == "file_not_found"
    readable = await adapters.read_file(fixed.snapshot_ref, "src/fixed_only.c", 1, 1)
    assert readable.matches[0].content == "int fixed_marker;"

    with pytest.raises(IntegrationError) as unknown:
        await adapters.read_file("snap-" + "0" * 16, "src/buf.c", 1, 1)
    assert unknown.value.code == "snapshot_not_found"


async def test_multi_parent_and_root_commit_are_rejected(tmp_path):
    merge = build_adapters(tmp_path / "merge", build_fake({(REPO, COMMIT): [PARENT, EXTRA]}))
    with pytest.raises(IntegrationError) as ambiguous:
        await merge.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
        )
    assert ambiguous.value.code == "multi_parent_commit"

    root = build_adapters(tmp_path / "root", build_fake({}))
    with pytest.raises(IntegrationError) as missing:
        await root.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
        )
    assert missing.value.code == "parent_unavailable"


async def test_fetch_and_function_mismatch_failures_are_explicit(tmp_path):
    adapters = build_adapters(tmp_path)
    with pytest.raises(IntegrationError) as unknown_repo:
        await adapters.prepare_snapshot(
            SnapshotRequest(
                idx=1,
                func=BUGGY_FUNC,
                commit_url="https://github.com/acme/missing/commit/" + COMMIT,
                revision="commit",
            )
        )
    assert unknown_repo.value.code == "repository_fetch_failed"

    with pytest.raises(IntegrationError) as unknown_commit:
        await adapters.prepare_snapshot(
            SnapshotRequest(
                idx=1,
                func=BUGGY_FUNC,
                commit_url="https://github.com/acme/buf/commit/" + EXTRA,
                revision="commit",
            )
        )
    assert unknown_commit.value.code == "commit_not_found"

    with pytest.raises(IntegrationError) as mismatch:
        await adapters.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=CHECKED_FUNC)
        )
    assert mismatch.value.code == "function_not_found"


async def test_duplicate_function_text_is_ambiguous(tmp_path):
    duplicated = dict(PARENT_FILES)
    duplicated["include/buf_copy.h"] = "/* header copy */\n" + BUGGY_FUNC + "\n"
    fake = FakeGit(
        {REPO: {PARENT: duplicated, COMMIT: FIXED_FILES}},
        {(REPO, COMMIT): [PARENT]},
    )
    adapters = build_adapters(tmp_path, fake)
    with pytest.raises(IntegrationError) as ambiguous:
        await adapters.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=1, func=BUGGY_FUNC)
        )
    assert ambiguous.value.code == "function_ambiguous"


@pytest.mark.parametrize(
    ("url", "code"),
    [
        (f"http://github.com/acme/buf/commit/{COMMIT}", "unsupported_commit_url"),
        (f"https://gitlab.com/acme/buf/commit/{COMMIT}", "unsupported_host"),
        (f"https://github.com.evil.test/acme/buf/commit/{COMMIT}", "unsupported_host"),
        (f"https://user:pw@github.com/acme/buf/commit/{COMMIT}", "unsupported_commit_url"),
        (f"https://github.com:8443/acme/buf/commit/{COMMIT}", "unsupported_commit_url"),
        (f"https://192.168.1.5/acme/buf/commit/{COMMIT}", "unsupported_host"),
        (f"https://github.com/acme/buf/pull/1/commit/{COMMIT}", "unsupported_commit_url"),
        ("https://github.com/acme/buf/commit/not-a-sha", "unsupported_commit_url"),
        ("github.com/acme/buf/commit/" + COMMIT, "unsupported_commit_url"),
    ],
)
async def test_commit_url_must_match_allowlisted_host_and_shape(tmp_path, url, code):
    adapters = build_adapters(tmp_path)
    with pytest.raises(IntegrationError) as invalid:
        await adapters.prepare_snapshot(
            SnapshotRequest(idx=1, func=BUGGY_FUNC, commit_url=url, revision="commit")
        )
    assert invalid.value.code == code


async def test_private_network_and_dns_failures_are_rejected(tmp_path):
    private = build_adapters(
        tmp_path / "private",
        resolver=lambda _host: [(2, 1, 6, "", ("10.0.0.7", 443))],
    )
    with pytest.raises(IntegrationError) as blocked:
        await private.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
        )
    assert blocked.value.code == "private_network_target"

    def broken(_host):
        raise OSError("dns failure")

    offline = build_adapters(tmp_path / "offline", resolver=broken)
    with pytest.raises(IntegrationError) as unavailable:
        await offline.prepare_course(
            CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
        )
    assert unavailable.value.code == "network_unavailable"


def test_commit_url_variants_share_the_same_repo_target():
    for url in (
        COMMIT_URL,
        COMMIT_URL + "/",
        COMMIT_URL + ".patch",
        COMMIT_URL + "?w=1",
        COMMIT_URL + "#diff-1",
    ):
        target = parse_commit_url(url)
        assert target.repo_url == REPO
        assert target.commit == COMMIT


async def test_cached_full_commit_survives_mirror_eviction_offline(tmp_path):
    fake = build_fake()
    adapters = build_adapters(tmp_path, fake)
    sample = CourseSample(idx=1, commit_url=COMMIT_URL, target=0, func=CHECKED_FUNC)
    first = await adapters.prepare_course(sample)
    fake.fetched.clear()

    def offline(_host):
        pytest.fail("a materialized commit snapshot needs neither DNS nor the mirror")

    adapters.preparation.resolver = offline
    second = await adapters.prepare_course(sample)
    assert second.snapshot_ref == first.snapshot_ref
    assert len(fake.exported) == 1


@pytest.mark.parametrize(
    ("literal", "different"),
    [
        ('"a  b"', '"a b"'),
        (r'"a\"  b"', r'"a\" b"'),
        ('R"tag(a  b " quoted )tag"', 'R"tag(a b " quoted )tag"'),
        ("'\t'", "' '"),
    ],
)
async def test_function_matching_preserves_literal_whitespace(tmp_path, literal, different):
    func = f"void f(void) {{ use({literal}); }}"
    fake = FakeGit({REPO: {COMMIT: {"a.c": func}}})
    adapters = build_adapters(tmp_path, fake)
    with pytest.raises(IntegrationError) as failure:
        await adapters.prepare_course(
            CourseSample(
                idx=1,
                commit_url=COMMIT_URL,
                target=0,
                func=func.replace(literal, different),
            )
        )
    assert failure.value.code == "function_not_found"


async def test_function_in_an_oversized_file_reports_a_scan_limit(tmp_path):
    from app.repository.locate import MAX_SCAN_BYTES

    func = "int f(void) { return 1; }"
    fake = FakeGit({REPO: {COMMIT: {"large.c": "/*" + "x" * MAX_SCAN_BYTES + "*/\n" + func}}})
    adapters = build_adapters(tmp_path, fake)
    with pytest.raises(IntegrationError) as failure:
        await adapters.prepare_course(
            CourseSample(
                idx=1,
                commit_url=COMMIT_URL,
                target=0,
                func=func,
            )
        )
    assert failure.value.code == "function_scan_limit"
    assert "无法确认" in failure.value.message and "不一致" not in failure.value.message


@pytest.mark.parametrize(
    "template",
    [
        "/* {func} */",
        "// {func}\n",
        "// archived implementation \\\n{func}\n",
        "/\\\n/ {func}\n",
        "/\\\r\n* {func} *\\\r\n/",
        'const char *old = R"old({func})old";',
    ],
)
async def test_function_text_in_comments_or_literals_is_not_current_code(tmp_path, template):
    func = "int f(void) { return 1; }"
    fake = FakeGit({REPO: {COMMIT: {"a.c": template.format(func=func).encode("utf-8")}}})
    adapters = build_adapters(tmp_path, fake)
    with pytest.raises(IntegrationError) as failure:
        await adapters.prepare_snapshot(
            SnapshotRequest(
                idx=1,
                func=func,
                commit_url=COMMIT_URL,
                revision="commit",
            )
        )
    assert failure.value.code == "function_not_found"


@pytest.mark.parametrize(
    "comment",
    [
        "/* {func} */",
        "// archived implementation \\\n{func}",
        "/\\\n/ {func}",
        "/\\\n* {func} *\\\n/",
    ],
)
async def test_commented_copy_does_not_make_real_function_ambiguous(tmp_path, comment):
    func = "int f(void) { return 1; }"
    fake = FakeGit({REPO: {COMMIT: {"a.c": f"{comment.format(func=func)}\n\n{func}\n"}}})
    adapters = build_adapters(tmp_path, fake)
    prepared = await adapters.prepare_snapshot(
        SnapshotRequest(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            revision="commit",
        )
    )
    location = await adapters.locate_function(prepared.snapshot_ref, func)
    assert location.start_line == location.end_line == comment.count("\n") + 3
    assert location.content == func


@pytest.mark.parametrize(
    "func",
    [
        "/* function documentation */\nint f(void) { /* body note */ return 1; }",
        '// function documentation\nint f(void) { use("/* literal */"); return 1; }',
        "// function documentation \\\ncontinued\nint f(void) { return 1; }",
        "/\\\n* function documentation *\\\n/\nint f(void) { return 1; }",
    ],
)
async def test_function_comments_and_comment_like_literals_are_preserved(tmp_path, func):
    fake = FakeGit({REPO: {COMMIT: {"a.c": func}}})
    adapters = build_adapters(tmp_path, fake)
    prepared = await adapters.prepare_snapshot(
        SnapshotRequest(
            idx=1,
            func=func,
            commit_url=COMMIT_URL,
            revision="commit",
        )
    )
    assert prepared.func == func
    location = await adapters.locate_function(prepared.snapshot_ref, func)
    assert location.content == func


@pytest.mark.parametrize(
    "func",
    [
        "/* int f(void) { return 1; } */",
        "// archived implementation \\\nint f(void) { return 1; }",
        "/\\\n* int f(void) { return 1; } *\\\n/",
    ],
)
async def test_comment_only_input_cannot_be_a_target_function(tmp_path, func):
    fake = FakeGit({REPO: {COMMIT: {"a.c": func}}})
    adapters = build_adapters(tmp_path, fake)
    with pytest.raises(IntegrationError) as failure:
        await adapters.prepare_snapshot(
            SnapshotRequest(
                idx=1,
                func=func,
                commit_url=COMMIT_URL,
                revision="commit",
            )
        )
    assert failure.value.code == "function_not_found"


@pytest.mark.parametrize("cached", [False, True])
@pytest.mark.parametrize("timeout", [False, True])
async def test_cancelled_materialization_exits_before_returning_and_never_publishes(
    tmp_path, monkeypatch, cached, timeout
):
    import asyncio
    import threading

    func = "int f(void) { return 1; }"
    fake = FakeGit({REPO: {COMMIT: {"a.c": func}}})
    if cached:
        fake.fetched.add(REPO)
    adapters = build_adapters(tmp_path, fake)
    started, stopped, release = (threading.Event() for _ in range(3))
    observed = []

    def paused_export(handle, commit, destination, *, cancel_event=None):
        observed.append(cancel_event)
        (destination / "a.c").write_text(func, encoding="utf-8")
        started.set()
        try:
            while not release.wait(0.005):
                if cancel_event is not None and cancel_event.is_set():
                    break
            return 1
        finally:
            stopped.set()

    monkeypatch.setattr(fake, "export", paused_export)
    request = SnapshotRequest(idx=1, func=func, commit_url=COMMIT_URL, revision="commit")
    deadline = asyncio.timeout(None)

    async def prepare():
        if timeout:
            async with deadline:
                return await adapters.prepare_snapshot(request)
        return await adapters.prepare_snapshot(request)

    task = asyncio.create_task(prepare())
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
        assert not adapters.store.exists(adapters.store.ref_for(REPO, COMMIT))
        assert list(adapters.store.temp.iterdir()) == []
    finally:
        release.set()
        assert await asyncio.to_thread(stopped.wait, 2)
