/** @type {import('tailwindcss').Config} */
export default {
  darkMode: ["class", '[data-theme="dark"]'],
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      fontFamily: {
        sans: [
          "Inter",
          "-apple-system",
          "BlinkMacSystemFont",
          '"Segoe UI"',
          '"PingFang SC"',
          '"Hiragino Sans GB"',
          '"Microsoft YaHei"',
          "sans-serif",
        ],
        mono: [
          '"JetBrains Mono"',
          "ui-monospace",
          "SFMono-Regular",
          '"SF Mono"',
          "Menlo",
          "Consolas",
          '"Liberation Mono"',
          "monospace",
        ],
      },
      colors: {
        canvas: "var(--bg)",
        surface: {
          DEFAULT: "var(--surface)",
          elevated: "var(--surface-elevated)",
          soft: "var(--surface-soft)",
          sunken: "var(--surface-sunken)",
        },
        line: {
          DEFAULT: "var(--border)",
          soft: "var(--border-soft)",
          strong: "var(--border-strong)",
        },
        ink: {
          DEFAULT: "var(--text)",
          soft: "var(--text-soft)",
          muted: "var(--muted)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          strong: "var(--accent-strong)",
          soft: "var(--accent-soft)",
          border: "var(--accent-border)",
        },
        danger: {
          DEFAULT: "var(--danger)",
          ink: "var(--danger-ink)",
          soft: "var(--danger-soft)",
          border: "var(--danger-border)",
        },
        ok: {
          DEFAULT: "var(--ok)",
          ink: "var(--ok-ink)",
          soft: "var(--ok-soft)",
          border: "var(--ok-border)",
        },
        warn: {
          DEFAULT: "var(--warn)",
          ink: "var(--warn-ink)",
          soft: "var(--warn-soft)",
          border: "var(--warn-border)",
        },
      },
      boxShadow: {
        xs: "var(--shadow-xs)",
        card: "var(--shadow-sm)",
        float: "var(--shadow-md)",
        ring: "var(--ring)",
      },
    },
  },
  plugins: [],
};
