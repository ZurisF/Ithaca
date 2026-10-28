"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "../generated/api";
import { api } from "../lib/api";

type Session = components["schemas"]["SessionView"];
type Summary = components["schemas"]["SessionSummary"];
type Snapshot = components["schemas"]["SnapshotView"];
type Plan = components["schemas"]["InterviewPlan"];
type Section = components["schemas"]["SectionRef"];
type Direction = components["schemas"]["Direction"];

const headers = { "X-Dev-User": process.env.NEXT_PUBLIC_DEV_USER_ID ?? "00000000-0000-4000-8000-000000000001" };
const directions: Record<Direction, string> = {
  project_overview: "项目全貌", core_flow_deep_dive: "核心流程深挖",
  cross_cutting: "横切能力", stress_interview: "压力面试",
  contribution_retrospective: "贡献与复盘",
};

function errorMessage(error: unknown): string {
  if (error && typeof error === "object" && "error" in error) {
    const detail = error.error;
    if (detail && typeof detail === "object" && "message" in detail && typeof detail.message === "string") return detail.message;
  }
  return "请求未完成，请检查服务状态后重试。";
}

export default function Home() {
  const [sessions, setSessions] = useState<Summary[]>([]);
  const [session, setSession] = useState<Session | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [opinion, setOpinion] = useState("");
  const [direction, setDirection] = useState<Direction>("project_overview");
  const [selected, setSelected] = useState<Section[]>([]);
  const [confirmEmpty, setConfirmEmpty] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const pendingOpinionKey = useRef<string | null>(null);

  const loadSession = useCallback(async (id: string) => {
    const current = await api.GET("/v1/interviews/{session_id}", { params: { path: { session_id: id } }, headers });
    if (!current.data) throw new Error(errorMessage(current.error));
    setSession(current.data);
    setDirection(current.data.interview_direction ?? "project_overview");
    setSelected(current.data.selected_sections);
    if (current.data.has_snapshot) {
      const response = await api.POST("/v1/interviews/{session_id}/snapshot:parse-ranges", { params: { path: { session_id: id } }, headers });
      if (!response.data) throw new Error(errorMessage(response.error));
      setSnapshot(response.data);
      setMarkdown(response.data.content);
    } else { setSnapshot(null); setMarkdown(""); }
    if (current.data.has_plan) {
      const response = await api.GET("/v1/interviews/{session_id}/plan", { params: { path: { session_id: id } }, headers });
      if (!response.data) throw new Error(errorMessage(response.error));
      setPlan(response.data);
    } else setPlan(null);
    window.history.replaceState(null, "", `/?session=${encodeURIComponent(id)}`);
  }, []);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const response = await api.GET("/v1/interviews", { headers });
        if (!response.data) throw new Error(errorMessage(response.error));
        if (cancelled) return;
        setSessions(response.data);
        const id = new URLSearchParams(window.location.search).get("session");
        if (id) await loadSession(id);
      } catch (cause) { if (!cancelled) setError(cause instanceof Error ? cause.message : "无法读取会话。"); }
    }
    void bootstrap();
    return () => { cancelled = true; };
  }, [loadSession]);

  async function run(action: () => Promise<void>) {
    setBusy(true); setError("");
    try { await action(); }
    catch (cause) {
      setError(cause instanceof TypeError ? "请求失败，请检查服务连接后重试。" :
        cause instanceof Error ? cause.message : "请求未完成。");
    }
    finally { setBusy(false); }
  }

  function toggle(section: Section) {
    const present = selected.some(item => item.kind === section.kind && item.title === section.title);
    setSelected(present ? selected.filter(item => item.kind !== section.kind || item.title !== section.title) : [...selected, section]);
  }

  return <main className="shell">
    <header className="masthead">
      <p className="eyebrow">PROJECT INTERVIEW LAB · 准备工作台</p>
      <h1>让项目经验经得起追问</h1>
      <p className="lead">整理真实项目材料，确定面试范围，再生成阶段计划。</p>
    </header>
    {error && <div className="error" role="alert">{error}</div>}
    <section className="panel" aria-labelledby="sessions-title">
      <div className="section-head"><div><p className="step">01 / SESSION</p><h2 id="sessions-title">选择一场面试</h2></div>
        <button disabled={busy} onClick={() => void run(async () => {
          const response = await api.POST("/v1/interviews", { headers });
          if (!response.data) throw new Error(errorMessage(response.error));
          setSessions(previous => [response.data!, ...previous]);
          await loadSession(response.data.id);
        })}>创建会话</button></div>
      {sessions.length === 0 ? <p className="muted">还没有会话。创建后可从 Markdown 开始准备。</p> :
        <div className="session-list">{sessions.map(item => <button key={item.id}
          className={session?.id === item.id ? "session-item active" : "session-item"} disabled={busy}
          onClick={() => void run(() => loadSession(item.id))}>
          <span>{new Date(item.created_at).toLocaleString("zh-CN")}</span><small>{item.status}</small>
        </button>)}</div>}
    </section>
    {session && <>
      <section className="panel" aria-labelledby="snapshot-title">
        <p className="step">02 / SNAPSHOT</p><h2 id="snapshot-title">项目快照</h2>
        <p className="muted">粘贴项目 Markdown。写入前会执行敏感内容过滤；内容变化会清空原有范围和计划。</p>
        <label htmlFor="markdown">Markdown 材料</label>
        <textarea id="markdown" rows={12} maxLength={200000} value={markdown}
          disabled={busy || session.status !== "preparing"} onChange={event => setMarkdown(event.target.value)}
          placeholder="# 项目名\n## Modules\n### 模块名\n...\n## Threads\n### 流程名\n..." />
        <div className="actions"><button disabled={busy || session.status !== "preparing" || !markdown.trim()}
          onClick={() => void run(async () => {
            const response = await api.POST("/v1/interviews/{session_id}/snapshot:import", {
              params: { path: { session_id: session.id } }, headers, body: { markdown },
            });
            if (!response.data) throw new Error(errorMessage(response.error));
            await loadSession(session.id);
          })}>保存快照并解析范围</button></div>
        {snapshot && <div className="opinion"><label htmlFor="opinion">补充你的观点（可选）</label>
          <div className="inline"><input id="opinion" maxLength={4000} value={opinion}
            disabled={busy || session.status !== "preparing"} onChange={event => { setOpinion(event.target.value); pendingOpinionKey.current = null; }}
            placeholder="例如：目前最难维护的是权限边界" />
            <button disabled={busy || session.status !== "preparing" || !opinion.trim()}
              onClick={() => void run(async () => {
                pendingOpinionKey.current ??= crypto.randomUUID();
                const response = await api.POST("/v1/interviews/{session_id}/snapshot:append-user-opinion", {
                  params: { path: { session_id: session.id }, header: { "Idempotency-Key": pendingOpinionKey.current } },
                  headers, body: { text: opinion },
                });
                if (!response.data) throw new Error(errorMessage(response.error));
                pendingOpinionKey.current = null;
                setOpinion(""); await loadSession(session.id);
              })}>追加观点</button></div></div>}
      </section>
      {snapshot && <section className="panel" aria-labelledby="scope-title">
        <p className="step">03 / SCOPE</p><h2 id="scope-title">方向与范围</h2>
        <label htmlFor="direction">面试方向</label>
        <select id="direction" value={direction} disabled={busy || session.status !== "preparing"}
          onChange={event => setDirection(event.target.value as Direction)}>
          {Object.entries(directions).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
        <fieldset disabled={busy || session.status !== "preparing"}><legend>面试范围</legend>
          {snapshot.sections.length > 0 ? snapshot.sections.map(section => <label className="check-row" key={`${section.kind}:${section.title}`}>
            <input type="checkbox" checked={selected.some(item => item.kind === section.kind && item.title === section.title)}
              onChange={() => toggle(section)} /><span>{section.kind === "module" ? "模块" : "流程"} · {section.title}</span>
          </label>) : <label className="check-row"><input type="checkbox" checked={confirmEmpty}
            onChange={event => setConfirmEmpty(event.target.checked)} /><span>没有解析出范围，确认使用整份 Markdown</span></label>}
        </fieldset>
        <div className="actions"><button disabled={busy || session.status !== "preparing" ||
          (snapshot.sections.length > 0 ? selected.length === 0 : !confirmEmpty)}
          onClick={() => void run(async () => {
            const response = await api.PUT("/v1/interviews/{session_id}/selection", {
              params: { path: { session_id: session.id } }, headers,
              body: { interview_direction: direction, selected_sections: selected, confirm_empty_range: confirmEmpty },
            });
            if (!response.data) throw new Error(errorMessage(response.error));
            await loadSession(session.id);
          })}>保存方向与范围</button></div>
      </section>}
      {session.interview_direction && snapshot && <section className="panel" aria-labelledby="plan-title">
        <div className="section-head"><div><p className="step">04 / PLAN</p><h2 id="plan-title">阶段计划</h2></div>
          <button disabled={busy || session.status !== "preparing" || !!plan}
            onClick={() => void run(async () => {
              const response = await api.POST("/v1/interviews/{session_id}/plan:generate", {
                params: { path: { session_id: session.id } }, headers,
              });
              if (!response.data) throw new Error(errorMessage(response.error));
              await loadSession(session.id);
            })}>{busy ? "处理中…" : plan ? "计划已生成" : "生成计划"}</button></div>
        {plan ? <ol className="stage-list">{plan.stages.map(stage => <li key={stage.id}>
          <strong>{stage.title}</strong><span>{stage.goal}</span><small>完成标准：{stage.complete_when}</small>
        </li>)}</ol> : <p className="muted">模型未配置时，生成请求会显示明确错误。</p>}
      </section>}
    </>}
    <footer>施工进度：Markdown 准备流程可操作；目录观察、实时面试和赛后功能仍在开发。</footer>
  </main>;
}
