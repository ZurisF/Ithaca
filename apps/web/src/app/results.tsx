"use client";

import { useState } from "react";
import type { components } from "../generated/api";
import { api } from "../lib/api";

type Result = components["schemas"]["ResultView"];
type ResultTurn = components["schemas"]["ResultTurn"];
type Report = components["schemas"]["Report"];
type FeedbackRequest = components["schemas"]["FeedbackRequest"];

const dimensions: { key: keyof Report["dimensions"]; label: string }[] = [
  { key: "requirements_understanding", label: "需求理解" },
  { key: "system_design", label: "系统设计" },
  { key: "technical_depth", label: "技术深度" },
  { key: "engineering_quality", label: "工程质量" },
  { key: "failure_thinking", label: "故障思维" },
  { key: "data_awareness", label: "数据意识" },
  { key: "communication_structure", label: "沟通结构" },
  { key: "retrospection", label: "复盘能力" },
];

function level(score: number): string {
  if (score === 0) return "证据不足";
  if (score <= 2) return "需改进";
  if (score === 3) return "普通";
  return "优秀";
}

function radar(report: Report) {
  const point = (index: number, radius: number) => {
    const angle = -Math.PI / 2 + index * Math.PI / 4;
    return `${160 + Math.cos(angle) * radius},${160 + Math.sin(angle) * radius}`;
  };
  return <svg className="radar" viewBox="0 0 320 320" role="img" aria-label="八个能力维度的雷达图；证据不足的维度以空心圆标记">
    {[30, 60, 90].map(radius => <polygon key={radius} className="radar-grid"
      points={dimensions.map((_, index) => point(index, radius)).join(" ")} />)}
    {dimensions.map((_, index) => <line key={index} className="radar-axis" x1="160" y1="160"
      x2={point(index, 90).split(",")[0]} y2={point(index, 90).split(",")[1]} />)}
    <polygon className="radar-shape" points={dimensions.map(({ key }, index) =>
      point(index, (report.dimensions[key]?.score ?? 0) * 18)).join(" ")} />
    {dimensions.map(({ key }, index) => report.dimensions[key]?.score === 0 &&
      <circle key={key} className="radar-empty" cx={point(index, 11).split(",")[0]}
        cy={point(index, 11).split(",")[1]} r="5" />)}
    {dimensions.map(({ key, label }, index) => <text key={key} className="radar-label"
      x={point(index, 127).split(",")[0]} y={point(index, 127).split(",")[1]}
      textAnchor="middle" dominantBaseline="middle">{label}</text>)}
  </svg>;
}

function ResultQuestion({ turn, stageTitle, editable, onFeedback }: {
  turn: ResultTurn;
  stageTitle: string;
  editable: boolean;
  onFeedback: (turnNo: number, body: FeedbackRequest) => Promise<void>;
}) {
  const [reason, setReason] = useState<FeedbackRequest["reason"]>(null);
  const [saving, setSaving] = useState(false);
  async function save(body: FeedbackRequest) {
    setSaving(true);
    try { await onFeedback(turn.turn_no, body); }
    finally { setSaving(false); }
  }
  return <article className="qa-card">
    <p className="step">{stageTitle} · 第 {turn.turn_no} 题</p>
    <h4>{turn.question}</h4>
    <div className="qa-fields"><p><strong>你的回答</strong><br />{turn.answer ?? "尚未回答"}</p>
      <p><strong>项目版答案</strong><br />{turn.project_answer ?? "尚未生成"}</p>
      <p><strong>理想版答案</strong><br />{turn.ideal_answer ?? "尚未生成"}<br />
        <small>基于通用行业实践，仅供参考，不代表当前项目唯一正确实现。</small></p>
      <p><strong>逐题反馈</strong><br />{turn.comment ?? "尚未生成"}</p></div>
    {turn.interviewer_message && <p className="muted">面试官：{turn.interviewer_message}</p>}
    {turn.feedback && <p className="muted">已反馈：{turn.feedback.value === "upvote" ? "好评" : `差评${turn.feedback.reason ? ` · ${turn.feedback.reason}` : ""}`}</p>}
    {editable && <div className="feedback-controls">
      <button className="secondary" disabled={saving} onClick={() => void save({ value: "upvote" })}>好评</button>
      <select aria-label={`第 ${turn.turn_no} 题差评原因`} value={reason ?? ""}
        onChange={event => setReason(event.target.value as FeedbackRequest["reason"])}>
        <option value="">差评原因（可选）</option>
        {["重复", "不相关", "表述不清", "其他"].map(item => <option key={item}>{item}</option>)}
      </select>
      <button className="secondary" disabled={saving} onClick={() => void save({ value: "downvote", reason })}>差评</button>
    </div>}
  </article>;
}

export function Results({ result, headers, onRefresh }: {
  result: Result;
  headers: Record<string, string>;
  onRefresh: () => Promise<void>;
}) {
  const [tab, setTab] = useState<"report" | "qa">("report");
  const [error, setError] = useState("");
  const [downloading, setDownloading] = useState(false);
  const terminal = result.session.status === "completed" || result.session.status === "aborted";
  const showReport = terminal && (result.report !== null || result.processing_incomplete);

  async function feedback(turnNo: number, body: FeedbackRequest) {
    const response = await api.PUT("/v1/interviews/{session_id}/turns/{turn_no}/feedback", {
      params: { path: { session_id: result.session.id, turn_no: turnNo } }, headers, body,
    });
    if (!response.data) { setError("反馈未保存，请刷新后重试。"); return; }
    setError("");
    await onRefresh();
  }

  async function download(kind: "snapshot" | "full-qa" | "report") {
    setDownloading(true); setError("");
    try {
      const base = process.env.NEXT_PUBLIC_APPLICATION_URL ?? "http://127.0.0.1:8100";
      const response = await fetch(`${base}/v1/interviews/${result.session.id}/${kind}.md`, { headers });
      if (!response.ok) throw new Error("导出暂不可用，请稍后重试。");
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement("a");
      link.href = url; link.download = `${kind}.md`; link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) { setError(cause instanceof Error ? cause.message : "导出失败。"); }
    finally { setDownloading(false); }
  }

  return <section className="panel" aria-labelledby="results-title">
    <div className="section-head"><div><p className="step">06 / REVIEW</p><h2 id="results-title">复盘与完整问答</h2></div>
      <div className="export-actions">
        <button className="secondary" disabled={downloading} onClick={() => void download("snapshot")}>导出快照</button>
        <button className="secondary" disabled={downloading} onClick={() => void download("full-qa")}>导出完整问答</button>
        {result.report && <button className="secondary" disabled={downloading} onClick={() => void download("report")}>导出报告</button>}
      </div></div>
    {error && <p className="error" role="alert">{error}</p>}
    {showReport && <div className="tabs" role="tablist" aria-label="结果内容">
      <button role="tab" aria-selected={tab === "report"} className={tab === "report" ? "active" : "secondary"}
        onClick={() => setTab("report")}>复盘报告</button>
      <button role="tab" aria-selected={tab === "qa"} className={tab === "qa" ? "active" : "secondary"}
        onClick={() => setTab("qa")}>完整问答</button>
    </div>}
    {result.session.status === "post_processing" && <p role="status" className="muted">赛后处理中。参考答案、逐题反馈和报告会随处理进度更新。</p>}
    {result.processing_incomplete && <p role="status" className="error">赛后处理未完成，以下仅显示已生成的内容。</p>}
    {showReport && tab === "report" ? result.report ? <>
      <h3>总评</h3><p className="prose">{result.report.overall}</p>
      <h3>能力画像</h3>{radar(result.report)}
      <p className="muted">能力评分由 AI 基于本次面试内容生成，仅供复盘参考，不代表对实际能力的完整评价。</p>
      <div className="dimension-list">{dimensions.map(({ key, label }) => <article key={key}>
        <h4>{label} <span className="level">{level(result.report!.dimensions[key]?.score ?? 0)}</span></h4>
        <p className="prose">{result.report!.dimensions[key]?.analysis}</p>
      </article>)}</div>
      <h3>项目改进建议</h3><p className="prose">{result.report.project_recommendations}</p>
      <h3>下一轮训练建议</h3><p className="prose">{result.report.training_recommendations}</p>
    </> : <p className="muted">{result.session.status === "aborted" ? "本场已强制退出，仅保留已有问答。" : "报告尚未生成；可查看完整问答。"}</p> :
      result.turns.length === 0 ? <p className="muted">尚无问答。</p> :
      <div>{(result.plan?.stages ?? []).map((stage, index) => {
        const turns = result.turns.filter(turn => turn.stage_index === index);
        return turns.length > 0 && <section key={stage.id} aria-label={stage.title}>
          <h3>{stage.title}</h3>
          {turns.map(turn => <ResultQuestion key={turn.turn_no} turn={turn} stageTitle={stage.title}
            editable={result.session.status === "interviewing"} onFeedback={feedback} />)}
        </section>;
      })}</div>}
  </section>;
}
