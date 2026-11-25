import { useState } from "react";
import { askAboutReport } from "../api/client";

type Message = {role: "user" | "assistant"; content: string};

export function ReportDiscussion({taskId, idx}: {taskId: string; idx: number | string}) {
  const key = "report-discussion/" + JSON.stringify([taskId, idx]);
  const [messages, setMessages] = useState<Message[]>(() => {
    try { return JSON.parse(sessionStorage.getItem(key) ?? "[]"); }
    catch { return []; }
  });
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  async function submit() {
    const text = question.trim();
    if (!text || busy) return;
    setBusy(true);
    setError("");
    try {
      const history = messages.slice(-12).map(m => ({...m, content: m.content.slice(0, 8000)}));
      const {answer} = await askAboutReport(taskId, idx, text, history);
      const next: Message[] = [...messages, {role: "user", content: text}, {role: "assistant", content: answer}];
      setMessages(next);
      setQuestion("");
      try { sessionStorage.setItem(key, JSON.stringify(next)); } catch { /* Storage may be full. */ }
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "问答请求失败");
    } finally { setBusy(false); }
  }
  return <section aria-label="报告问答">
    <h3>报告问答</h3>
    {messages.map((m, i) => <p key={i}><strong>{m.role === "user" ? "我" : "审查助手"}</strong> {m.content}</p>)}
    <form onSubmit={e => {e.preventDefault(); void submit();}}>
      <textarea aria-label="关于此报告的问题" value={question} maxLength={8000} disabled={busy}
        onChange={e => setQuestion(e.target.value)} placeholder="哪条证据支持这个判断？" />
      <button disabled={busy || !question.trim()}>{busy ? "回答中…" : "提问"}</button>
    </form>
    {error && <p role="alert">{error}</p>}
  </section>;
}
