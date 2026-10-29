"use client";

import { useCallback, useEffect, useState } from "react";
import type { components } from "../../generated/api";
import { api } from "../../lib/api";

type Queue = components["schemas"]["CurationQueue"];
type Item = components["schemas"]["CurationItem"];
type BankQuestion = components["schemas"]["BankQuestion"];

const headers = { "X-Dev-User": process.env.NEXT_PUBLIC_DEV_ADMIN_ID ?? "00000000-0000-4000-8000-000000000002" };

function message(error: unknown): string {
  if (error && typeof error === "object" && "error" in error) {
    const detail = error.error;
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
  }
  return "请求未完成，请稍后重试。";
}

export default function AdminPage() {
  const [queue, setQueue] = useState<Queue | null>(null);
  const [bank, setBank] = useState<BankQuestion[]>([]);
  const [selected, setSelected] = useState<Item | null>(null);
  const [question, setQuestion] = useState("");
  const [topic, setTopic] = useState("");
  const [notes, setNotes] = useState("");
  const [idealAnswer, setIdealAnswer] = useState("");
  const [privacyConfirmed, setPrivacyConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    const [curation, questions] = await Promise.all([
      api.GET("/v1/admin/curation-items", { headers }),
      api.GET("/v1/admin/question-bank", { headers }),
    ]);
    if (!curation.data) throw new Error(message(curation.error));
    if (!questions.data) throw new Error(message(questions.error));
    setQueue(curation.data); setBank(questions.data);
    setSelected(previous => curation.data!.items.find(item => item.id === previous?.id) ?? null);
  }, []);

  useEffect(() => { void refresh().catch(cause => setError(cause instanceof Error ? cause.message : "无法读取策展材料。")); }, [refresh]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); }
    catch (cause) { setError(cause instanceof Error ? cause.message : "操作失败。"); }
    finally { setBusy(false); }
  }

  function choose(item: Item) {
    setSelected(item);
    const source = queue?.sources.find(row => row.session_id === item.source_session_id);
    const turn = source?.turns.find(row => row.turn_no === item.source_turn_no);
    setQuestion(item.edited_question ?? item.suggestion?.edited_question ?? turn?.question ?? "");
    setTopic(item.proposed_topic_path ?? item.suggestion?.proposed_topic_path ?? "");
    setNotes(item.review_notes ?? item.suggestion?.privacy_notes ?? "");
    setIdealAnswer(item.suggestion?.ideal_answer ?? "");
    setPrivacyConfirmed(false);
  }

  return <main className="shell">
    <header className="masthead"><p className="eyebrow">PROJECT INTERVIEW LAB · ADMINISTRATOR</p>
      <h1>人工策展</h1><p className="lead">只显示已获授权且已结束的会话。编辑、检查隐私与精确重复后，再人工确认入库。</p>
      <a href="/">返回面试工作台</a>
    </header>
    {error && <div className="error" role="alert">{error} <button className="secondary" onClick={() => void run(refresh)}>重新读取</button></div>}
    <section className="panel"><div className="section-head"><h2>已授权材料</h2><button className="secondary" disabled={busy} onClick={() => void run(refresh)}>刷新</button></div>
      {!queue || queue.sources.length === 0 ? <p className="muted">目前没有已授权且已结束的会话。</p> :
        queue.sources.map(source => <article className="qa-card" key={source.session_id}>
          <h3>会话 {source.session_id.slice(0, 8)} · {source.status}</h3>
          {source.turns.map(turn => <div key={turn.turn_no} className="curation-source-turn">
            <strong>第 {turn.turn_no} 题：{turn.question}</strong>
            <p>回答：{turn.answer ?? "未回答"}</p>
            {turn.feedback_value && <p className="muted">反馈：{turn.feedback_value}{turn.feedback_reason ? ` · ${turn.feedback_reason}` : ""}</p>}
            <button className="secondary" disabled={busy} onClick={() => void run(async () => {
              const response = await api.POST("/v1/admin/curation-items", {
                headers, body: { source_session_id: source.session_id, source_turn_no: turn.turn_no, suggest: true },
              });
              if (!response.data) throw new Error(message(response.error));
              await refresh(); choose(response.data);
            })}>选择并获取整理建议</button>
          </div>)}
        </article>)}
    </section>
    <section className="panel"><h2>策展条目</h2>
      {!queue || queue.items.length === 0 ? <p className="muted">选择源问题后，会在这里出现待审核条目。</p> :
        <div className="session-list">{queue.items.map(item => <button key={item.id} className="session-item"
          disabled={busy} onClick={() => choose(item)}>
          <span>第 {item.source_turn_no} 题 · {item.edited_question ?? "待编辑"}</span><small>{item.status}</small>
        </button>)}</div>}
      {selected && <div className="curation-editor">
        <h3>审核条目 {selected.id.slice(0, 8)}</h3>
        {selected.suggestion && <p className="muted">整理建议 · 隐私：{selected.suggestion.privacy_notes} · 重复风险：{selected.suggestion.duplicate_notes}。建议仅供审核，不能自动发布。</p>}
        <label htmlFor="edited-question">可公开的通用题目</label>
        <textarea id="edited-question" rows={4} maxLength={1000} disabled={busy || selected.status === "added"}
          value={question} onChange={event => setQuestion(event.target.value)} />
        <label htmlFor="topic-path">正式 Topic</label>
        <select id="topic-path" disabled={busy || selected.status === "added"} value={topic}
          onChange={event => setTopic(event.target.value)}>
          <option value="">请选择 Topic</option>
          {queue?.topics.map(path => <option key={path} value={path}>{path}</option>)}
        </select>
        <label htmlFor="review-notes">隐私处理与质量审核备注</label>
        <textarea id="review-notes" rows={3} maxLength={2000} disabled={busy || selected.status === "added"}
          value={notes} onChange={event => setNotes(event.target.value)}
          placeholder="记录项目名、业务数据、人员和实现细节的泛化处理结果。" />
        <label className="check-row"><input type="checkbox" checked={privacyConfirmed} disabled={busy || selected.status === "added"}
          onChange={event => setPrivacyConfirmed(event.target.checked)} />
          <span>已人工检查并泛化私人信息；公开题目与原始回答分离</span></label>
        <p className="muted">自动敏感项过滤会在保存审核时校验公开题目。{selected.exact_duplicate ? "精确查重：题库已有相同正文，不能发布。" : "精确查重：当前未发现相同正文；编辑后须重新保存审核。"}</p>
        {selected.status !== "added" && <div className="end-actions">
          <button disabled={busy || !question.trim() || !topic || !notes.trim() || !privacyConfirmed}
            onClick={() => void run(async () => {
              const response = await api.POST("/v1/admin/curation-items", { headers, body: {
                item_id: selected.id, source_session_id: selected.source_session_id,
                source_turn_no: selected.source_turn_no, status: "reviewed",
                suggest: false,
                edited_question: question, proposed_topic_path: topic, review_notes: notes,
              } });
              if (!response.data) throw new Error(message(response.error));
              await refresh(); choose(response.data); setIdealAnswer(idealAnswer);
            })}>保存人工审核</button>
          <button className="secondary" disabled={busy} onClick={() => void run(async () => {
            const response = await api.POST("/v1/admin/curation-items", { headers, body: {
              item_id: selected.id, source_session_id: selected.source_session_id,
              source_turn_no: selected.source_turn_no, status: "rejected", review_notes: notes,
              suggest: false,
            } });
            if (!response.data) throw new Error(message(response.error));
            await refresh(); choose(response.data);
          })}>拒绝入库</button>
        </div>}
        {selected.status === "reviewed" && !selected.exact_duplicate && <div>
          <label htmlFor="ideal-answer">可选理想答案（公开内容）</label>
          <textarea id="ideal-answer" rows={4} maxLength={8000} disabled={busy} value={idealAnswer}
            onChange={event => setIdealAnswer(event.target.value)} />
          <button className="danger" disabled={busy || !privacyConfirmed || question !== selected.edited_question || topic !== selected.proposed_topic_path || notes !== selected.review_notes}
            onClick={() => void run(async () => {
              const response = await api.POST("/v1/admin/curation-items/{item_id}:add-to-question-bank", {
                params: { path: { item_id: selected.id } }, headers,
                body: { ideal_answer: idealAnswer.trim() || null },
              });
              if (!response.data) throw new Error(message(response.error));
              await refresh(); choose(response.data);
            })}>人工确认加入题库并建立索引</button>
        </div>}
      </div>}
    </section>
    <section className="panel"><h2>题库管理</h2>
      {bank.length === 0 ? <p className="muted">题库暂无问题。</p> :
        <div className="bank-list">{bank.map(item => <article className="qa-card" key={item.id}>
          <strong>{item.question}</strong><p className="muted">{item.topic_path}</p>
          <p>使用 {item.usage_count} · 好评 {item.upvote_count} · 差评 {item.downvote_count}</p>
        </article>)}</div>}
    </section>
  </main>;
}
