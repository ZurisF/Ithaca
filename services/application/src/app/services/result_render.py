"""Deterministic Markdown projections of the current PostgreSQL result facts."""

from app.domain.contracts import Report, ResultView

DIMENSIONS = (
    ("requirements_understanding", "需求理解"),
    ("system_design", "系统设计"),
    ("technical_depth", "技术深度"),
    ("engineering_quality", "工程质量"),
    ("failure_thinking", "故障思维"),
    ("data_awareness", "数据意识"),
    ("communication_structure", "沟通结构"),
    ("retrospection", "复盘能力"),
)


def render_report_markdown(report: Report) -> str:
    lines = ["# 复盘报告", "", "## 总评", "", report.overall, "", "## 能力画像", ""]
    for key, label in DIMENSIONS:
        lines.extend((f"### {label}", "", report.dimensions[key].analysis, ""))
    lines.extend(
        (
            "## 项目改进建议",
            "",
            report.project_recommendations,
            "",
            "## 下一轮训练建议",
            "",
            report.training_recommendations,
            "",
        )
    )
    return "\n".join(lines)


def render_full_qa_markdown(result: ResultView) -> str:
    lines = ["# 完整问答", ""]
    current_stage = None
    for turn in result.turns:
        if turn.stage_index != current_stage:
            current_stage = turn.stage_index
            title = (
                result.plan.stages[current_stage].title
                if result.plan and current_stage < len(result.plan.stages)
                else f"Stage {current_stage + 1}"
            )
            lines.extend((f"## {title}", ""))
        lines.extend(
            (
                f"### 第 {turn.turn_no} 题",
                "",
                "**问题**",
                "",
                turn.question,
                "",
                "**回答**",
                "",
                turn.answer or "未回答",
                "",
            )
        )
        if turn.interviewer_message:
            lines.extend(("**面试官消息**", "", turn.interviewer_message, ""))
        if turn.project_answer:
            lines.extend(("**项目版答案**", "", turn.project_answer, ""))
        if turn.ideal_answer:
            lines.extend(
                (
                    "**理想版答案**",
                    "",
                    "基于通用行业实践，仅供参考，不代表当前项目唯一正确实现。",
                    "",
                    turn.ideal_answer,
                    "",
                )
            )
        if turn.comment:
            lines.extend(("**逐题反馈**", "", turn.comment, ""))
        if turn.feedback:
            label = "好评" if turn.feedback.value == "upvote" else "差评"
            reason = f"（{turn.feedback.reason}）" if turn.feedback.reason else ""
            lines.extend(("**题目反馈**", "", label + reason, ""))
    return "\n".join(lines)
