import type { ReactNode } from "react";

const CPP_KEYWORDS = new Set([
  "auto", "break", "case", "catch", "class", "const", "constexpr", "continue",
  "default", "delete", "do", "else", "enum", "explicit", "extern", "false",
  "for", "friend", "goto", "if", "inline", "mutable", "namespace", "new",
  "noexcept", "nullptr", "operator", "private", "protected", "public", "register",
  "reinterpret_cast", "return", "sizeof", "static", "static_assert", "static_cast",
  "struct", "switch", "template", "this", "throw", "true", "try", "typedef",
  "typename", "union", "using", "virtual", "volatile", "while", "NULL",
]);

const CPP_TYPES = new Set([
  "void", "bool", "char", "short", "int", "long", "float", "double", "signed",
  "unsigned", "size_t", "ssize_t", "ptrdiff_t", "intptr_t", "uintptr_t",
  "int8_t", "int16_t", "int32_t", "int64_t", "uint8_t", "uint16_t", "uint32_t",
  "uint64_t", "FILE", "off_t", "u8", "u16", "u32", "u64",
]);

const CPP_SINKS = new Set([
  "memcpy", "memmove", "memset", "strcpy", "strncpy", "strcat", "strncat",
  "sprintf", "snprintf", "vsprintf", "vsnprintf", "gets", "scanf", "sscanf",
  "malloc", "calloc", "realloc", "free", "alloca", "read", "recv", "recvfrom",
]);

const TOKEN_PATTERN =
  /(\/\/[^\n]*|\/\*[\s\S]*?\*\/|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|^\s*#\s*[a-zA-Z_]\w*|\b0x[0-9a-fA-F]+[uUlL]*\b|\b\d+(?:\.\d+)?[uUlLfF]*\b|\b[a-zA-Z_]\w*\b)/gm;

/**
 * 纯 React 节点的轻量 C/C++ 词法着色：
 * - 不使用 dangerouslySetInnerHTML，完全遵循“代码作为数据处理”的安全要求；
 * - 保留原始空白与字符内容，textContent 与原文严格一致；
 * - 对常见内存/字符串危险汇聚点（如 memcpy/strcpy/malloc）给出温和强调。
 */
export function highlightCpp(source: string): ReactNode[] {
  const nodes: ReactNode[] = [];
  let lastIndex = 0;
  let key = 0;

  TOKEN_PATTERN.lastIndex = 0;
  let match = TOKEN_PATTERN.exec(source);
  while (match !== null) {
    const start = match.index;
    const token = match[0];
    if (start > lastIndex) {
      nodes.push(source.slice(lastIndex, start));
    }

    let className = "";
    if (token.startsWith("//") || token.startsWith("/*")) {
      className = "tok-comment";
    } else if (token.startsWith('"') || token.startsWith("'")) {
      className = "tok-string";
    } else if (/^\s*#/.test(token)) {
      className = "tok-macro";
    } else if (/^(?:0x|\d)/.test(token)) {
      className = "tok-number";
    } else if (CPP_SINKS.has(token)) {
      className = "tok-sink";
    } else if (CPP_KEYWORDS.has(token)) {
      className = "tok-keyword";
    } else if (CPP_TYPES.has(token)) {
      className = "tok-type";
    } else {
      const after = source.slice(start + token.length);
      if (/^\s*\(/.test(after)) {
        className = "tok-fn";
      }
    }

    if (className) {
      nodes.push(
        <span key={key++} className={className}>
          {token}
        </span>,
      );
    } else {
      nodes.push(token);
    }

    lastIndex = start + token.length;
    match = TOKEN_PATTERN.exec(source);
  }

  if (lastIndex < source.length) {
    nodes.push(source.slice(lastIndex));
  }
  return nodes;
}
