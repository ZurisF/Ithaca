"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { components } from "../generated/api";
import { api } from "../lib/api";
import { Results } from "./results";

type Session = components["schemas"]["SessionView"];
type Summary = components["schemas"]["SessionSummary"];
type Snapshot = components["schemas"]["SnapshotView"];
type Plan = components["schemas"]["InterviewPlan"];
type Interview = components["schemas"]["InterviewView"];
type Section = components["schemas"]["SectionRef"];
type Direction = components["schemas"]["Direction"];
type SourceInventory = components["schemas"]["SourceInventory"];
type ModelReadiness = components["schemas"]["ModelReadiness"];
type Result = components["schemas"]["ResultView"];

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
  const [sourceInventory, setSourceInventory] = useState<SourceInventory | null>(null);
  const [modelReadiness, setModelReadiness] = useState<ModelReadiness | null>(null);
  const [plan, setPlan] = useState<Plan | null>(null);
  const [interview, setInterview] = useState<Interview | null>(null);
  const [result, setResult] = useState<Result | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [opinion, setOpinion] = useState("");
  const [answerText, setAnswerText] = useState("");
  const [correctionText, setCorrectionText] = useState("");
  const [confirmationNotice, setConfirmationNotice] = useState("");
  const [direction, setDirection] = useState<Direction>("project_overview");
  const [selected, setSelected] = useState<Section[]>([]);
  const [confirmEmpty, setConfirmEmpty] = useState(false);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [confirmExit, setConfirmExit] = useState(false);
  const pendingOpinionKey = useRef<string | null>(null);
  const pendingObserveKey = useRef<string | null>(null);

  useEffect(() => {
    setCorrectionText(interview?.pending_correction ?? "");
  }, [interview?.pending_correction]);

  const loadSession = useCallback(async (id: string) => {
    const current = await api.GET("/v1/interviews/{session_id}", { params: { path: { session_id: id } }, headers });
    if (!current.data) throw new Error(errorMessage(current.error));
    setSession(current.data);
    setDirection(current.data.interview_direction ?? "project_overview");
    setSelected(current.data.selected_sections);
    if (current.data.source_handle) {
      const inventory = await api.GET("/v1/interviews/{session_id}/source/inventory", {
        params: { path: { session_id: id } }, headers,
      });
      if (inventory.data) setSourceInventory(inventory.data);
      else { setSourceInventory(null); setError(errorMessage(inventory.error)); }
    } else setSourceInventory(null);
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
    if (current.data.status !== "preparing") {
      const response = await api.GET("/v1/interviews/{session_id}/current", {
        params: { path: { session_id: id } }, headers,
      });
      if (!response.data) throw new Error(errorMessage(response.error));
      setInterview(response.data);
      const history = await api.GET("/v1/interviews/{session_id}/full-qa", {
        params: { path: { session_id: id } }, headers,
      });
      if (!history.data) throw new Error(errorMessage(history.error));
      setResult(history.data);
    } else { setInterview(null); setResult(null); }
    setConfirmExit(false);
    window.history.replaceState(null, "", `/?session=${encodeURIComponent(id)}`);
  }, []);

  useEffect(() => {
    if (!session || !["interviewing", "post_processing"].includes(session.status)) return;
    const id = session.id;
    const controller = new AbortController();
    const baseUrl = process.env.NEXT_PUBLIC_APPLICATION_URL ?? "http://127.0.0.1:8100";
    async function refresh() {
      const response = await api.GET("/v1/interviews/{session_id}/current", {
        params: { path: { session_id: id } }, headers,
      });
      if (response.data && !controller.signal.aborted) {
        setInterview(response.data);
        setSession(response.data.session);
        const history = await api.GET("/v1/interviews/{session_id}/full-qa", {
          params: { path: { session_id: id } }, headers,
        });
        if (history.data && !controller.signal.aborted) setResult(history.data);
      }
    }
    async function subscribe() {
      while (!controller.signal.aborted) {
        try {
          await refresh();
          const response = await fetch(`${baseUrl}/v1/interviews/${id}/events`, {
            headers, signal: controller.signal,
          });
          if (!response.ok || !response.body) throw new Error("事件连接失败");
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = "";
          while (!controller.signal.aborted) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const parts = buffer.split("\n\n");
            buffer = parts.pop() ?? "";
            if (parts.some(part => part.includes("event:") || part.includes(": connected"))) await refresh();
          }
        } catch { /* Reconnect and read the PostgreSQL-backed current view. */ }
        if (!controller.signal.aborted) await new Promise(resolve => setTimeout(resolve, 3000));
      }
    }
    void subscribe();
    return () => controller.abort();
  }, [session?.id, session?.status]);

  useEffect(() => {
    let cancelled = false;
    async function bootstrap() {
      try {
        const response = await api.GET("/v1/interviews", { headers });
        if (!response.data) throw new Error(errorMessage(response.error));
        if (cancelled) return;
        setSessions(response.data);
        const readiness = await api.GET("/v1/model-readiness");
        if (!cancelled) setModelReadiness(readiness.data ?? null);
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
      <p className="eyebrow">PROJECT INTERVIEW LAB · 面试工作台</p>
      <h1>让项目经验经得起追问</h1>
      <p className="lead">整理项目材料、完成面试，并回看完整问答与复盘报告。</p>
    </header>
    {error && <div className="error" role="alert">{error} <button className="secondary" onClick={() => void run(async () => {
      if (session) await loadSession(session.id);
      else window.location.reload();
    })}>重新读取</button></div>}
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
        <div className="source-box">
          <h3>从本机目录观察</h3>
          <p className="muted">选择器只在本机运行。服务器和数据库只接收目录授权标识；模型只会收到经过过滤的相对路径和必要文件片段。</p>
          <div className="actions"><button disabled={busy || session.status !== "preparing"}
            onClick={() => void run(async () => {
              const response = await api.POST("/v1/interviews/{session_id}/source:choose", {
                params: { path: { session_id: session.id } }, headers,
              });
              if (!response.data) throw new Error(errorMessage(response.error));
              pendingObserveKey.current = null;
              setSourceInventory(response.data);
              await loadSession(session.id);
            })}>{sourceInventory ? "重新选择目录" : "选择本机目录"}</button></div>
          {sourceInventory && <>
            <p className="muted">已清点 {sourceInventory.files.length} 项{sourceInventory.partial ? "；目录清点达到预算，仅覆盖部分内容" : ""}。请先检查清单，再生成快照。</p>
            <details><summary>查看文件、跳过原因与脱敏位置</summary>
              <ul className="inventory-list">{sourceInventory.files.map(item => <li key={item.relative_path}>
                <span>{item.relative_path}</span>
                {item.skip_reason && <small>跳过：{item.skip_reason}</small>}
                {item.redactions.map((hit, index) => <small key={`${hit.line}:${hit.kind}:${index}`}>
                  第 {hit.line} 行 · {hit.kind} 已脱敏
                </small>)}
              </li>)}</ul>
            </details>
            <p className="muted">{modelReadiness
              ? `点击生成后，已过滤的项目片段将发送到 ${modelReadiness.provider_host}，由 ${modelReadiness.model} 分析；真实目录路径不会发送。`
              : "当前模型尚未配置，目录清单可查看，观察生成暂不可用。"}</p>
            <div className="actions"><button disabled={busy || session.status !== "preparing" || !modelReadiness}
              onClick={() => void run(async () => {
                pendingObserveKey.current ??= crypto.randomUUID();
                const response = await api.POST("/v1/interviews/{session_id}/snapshot:observe", {
                  params: { path: { session_id: session.id }, header: { "Idempotency-Key": pendingObserveKey.current } },
                  headers, body: { source_handle: sourceInventory.source_handle },
                });
                if (!response.data) throw new Error(errorMessage(response.error));
                pendingObserveKey.current = null;
                await loadSession(session.id);
              })}>{busy ? "观察中…" : "生成项目快照"}</button></div>
          </>}
        </div>
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
        {plan && session.status === "preparing" && <div className="actions"><button
          disabled={busy || !modelReadiness}
          onClick={() => void run(async () => {
            const response = await api.POST("/v1/interviews/{session_id}/start", {
              params: { path: { session_id: session.id } }, headers,
            });
            if (!response.data) throw new Error(errorMessage(response.error));
            await loadSession(session.id);
          })}>{busy ? "进入面试中…" : "开始面试"}</button></div>}
      </section>}
      {interview && <section className="panel" aria-labelledby="interview-title">
        <p className="step">05 / INTERVIEW</p><h2 id="interview-title">当前面试</h2>
        {interview.current_stage_index !== null && interview.plan &&
          <p className="muted">阶段 {interview.current_stage_index + 1}：{interview.plan.stages[interview.current_stage_index]?.title}</p>}
        {interview.plan && interview.session.status === "interviewing" && <ol className="progress-list">
          {interview.plan.stages.map((stage, index) => <li key={stage.id} className={index === interview.current_stage_index ? "current" : ""}>
            {stage.title}{index < (interview.current_stage_index ?? 0) ? " · 已结束" : ""}
          </li>)}
        </ol>}
        {interview.previous_turn?.interviewer_message &&
          <p className="muted">面试官：{interview.previous_turn.interviewer_message}</p>}
        {interview.awaiting === "snapshot_confirmation" ? <>
          <p className="muted">面试官识别到一条项目事实更正。请核对并编辑；确认后只追加到快照，不会重新生成本轮决策。</p>
          <label htmlFor="correction">待追加内容</label>
          <textarea id="correction" rows={4} maxLength={4000} value={correctionText}
            disabled={busy} onChange={event => { setCorrectionText(event.target.value); setConfirmationNotice(""); }} />
          {confirmationNotice && <p role="status">{confirmationNotice}</p>}
          <div className="actions">
            <button disabled={busy || !correctionText.trim()} onClick={() => void run(async () => {
              const response = await api.POST("/v1/interviews/{session_id}/snapshot-corrections:resolve", {
                params: { path: { session_id: session.id } }, headers,
                body: { turn_no: interview.current_turn!.turn_no, decision: "confirm",
                  edited_text: correctionText === interview.pending_correction ? null : correctionText },
              });
              if (!response.data) throw new Error(errorMessage(response.error));
              if (response.data.awaiting === "snapshot_confirmation" && response.data.pending_correction !== correctionText)
                setConfirmationNotice("敏感内容已替换。请检查最终文字并再次确认。");
              else setConfirmationNotice("");
              await loadSession(session.id);
            })}>确认写入快照</button>
            <button disabled={busy} onClick={() => void run(async () => {
              const response = await api.POST("/v1/interviews/{session_id}/snapshot-corrections:resolve", {
                params: { path: { session_id: session.id } }, headers,
                body: { turn_no: interview.current_turn!.turn_no, decision: "do_not_write" },
              });
              if (!response.data) throw new Error(errorMessage(response.error));
              setConfirmationNotice(""); await loadSession(session.id);
            })}>暂不写入</button>
          </div>
        </> : interview.awaiting === "decision_retry" ? <>
          <p className="muted">当前面试决策暂时失败。你可以明确重试，原回答不会被改写。</p>
          <div className="actions"><button disabled={busy} onClick={() => void run(async () => {
            const response = await api.POST("/v1/interviews/{session_id}/decision:retry", {
              params: { path: { session_id: session.id } }, headers,
            });
            if (!response.data) throw new Error(errorMessage(response.error));
            await loadSession(session.id);
          })}>重试当前决策</button></div>
        </> : interview.current_turn && interview.awaiting === "answer" ? <>
          <p className="lead">{interview.current_turn.question}</p>
          <p className="muted">第 {interview.current_turn.turn_no} 题</p>
          <label htmlFor="answer">你的回答</label>
          <textarea id="answer" rows={6} maxLength={8000} value={answerText}
            disabled={busy} onChange={event => setAnswerText(event.target.value)} />
          <div className="actions"><button disabled={busy || !answerText.trim()} onClick={() => void run(async () => {
            const response = await api.POST("/v1/interviews/{session_id}/answers", {
              params: { path: { session_id: session.id } }, headers,
              body: { turn_no: interview.current_turn!.turn_no, answer: answerText },
            });
            if (!response.data) throw new Error(errorMessage(response.error));
            setAnswerText(""); await loadSession(session.id);
          })}>{busy ? "处理中…" : "提交回答"}</button></div>
        </> : interview.session.status === "interviewing" ?
          <p className="muted">面试官正在处理当前回答。刷新后会从当前视图恢复。</p> :
          <p className="muted">{interview.session.status === "post_processing" ? "面试已结束，赛后内容正在生成。" : "面试已结束。"}</p>}
        {interview.session.status === "interviewing" && <div className="end-actions">
          <button className="secondary" disabled={busy} onClick={() => void run(async () => {
            const response = await api.POST("/v1/interviews/{session_id}/finish-early", {
              params: { path: { session_id: session.id } }, headers,
            });
            if (!response.data) throw new Error(errorMessage(response.error));
            await loadSession(session.id);
          })}>提前完成</button>
          {!confirmExit ? <button className="danger" disabled={busy} onClick={() => setConfirmExit(true)}>强制退出</button> :
            <div className="exit-confirm" role="group" aria-label="确认强制退出">
              <p>强制退出后不会继续生成赛后报告。确认退出吗？</p>
              <button className="secondary" disabled={busy} onClick={() => setConfirmExit(false)}>取消</button>
              <button className="danger" disabled={busy} onClick={() => void run(async () => {
                const response = await api.POST("/v1/interviews/{session_id}/force-exit:confirm", {
                  params: { path: { session_id: session.id } }, headers,
                });
                if (!response.data) throw new Error(errorMessage(response.error));
                await loadSession(session.id);
              })}>确认强制退出</button>
            </div>}
        </div>}
      </section>}
      {result && <Results result={result} headers={headers} onRefresh={() => loadSession(session.id)} />}
    </>}
  </main>;
}
