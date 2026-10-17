/**
 * 与 `examples/synthetic.jsonl` 和 `backend/app/demo.py` 保持一致的合成样例。
 * 仅用于本地联调 `app.demo` 入口；正式 app.main 入口不会接受这些提交链接。
 */
export const DEMO_COMMIT_URL = "https://example.invalid/synthetic/commit/001";

export const DEMO_SNAPSHOTS = {
  vulnerable: {
    label: "合成样例·漏洞版（取父提交）",
    idx: "1",
    func: "void copy(char *dst, const char *src, size_t n) { memcpy(dst, src, n); }",
    commitUrl: DEMO_COMMIT_URL,
    revision: "parent" as const,
  },
  fixed: {
    label: "合成样例·修复版（取该提交）",
    idx: "1",
    func: "void copy(char *dst, size_t cap, const char *src, size_t n) { copy_checked(dst, cap, src, n); }",
    commitUrl: DEMO_COMMIT_URL,
    revision: "commit" as const,
  },
} as const;
