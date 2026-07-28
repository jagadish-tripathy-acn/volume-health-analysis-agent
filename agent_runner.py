"""
LangGraph-powered Volume Health Analysis Agent (AWS Bedrock + LangSmith).

Workflow:  collect -> analyze -> health_check -> assemble
Invalid/empty payloads short-circuit to `assemble` with status="error".
`analyze` makes exactly ONE Bedrock call (ChatBedrockConverse + with_structured_output)
that produces the full analysis, anomalies, recommendations, and executive summary
together -- one round-trip instead of a sequential tool loop.
If it fails the response degrades to status="partial" instead of raising.

Usage:
    agent = VolumeHealthGraph()
    response = agent.invoke()           # -> VolumeHealthResponse
    text    = run_agent(request)        # backward-compatible for web_runner.py
"""
from __future__ import annotations

import logging
import os
import sys
import time
from collections import defaultdict
from typing import List, Literal, Optional, TypedDict

# LangSmith tracing — no-op when LANGCHAIN_API_KEY is absent
os.environ.setdefault("LANGCHAIN_TRACING_V2", "true")
os.environ.setdefault("LANGCHAIN_PROJECT", "volume-health-analysis")

from langchain_aws import ChatBedrockConverse
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "us.anthropic.claude-sonnet-4-6"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
SUMMARY_FILE = os.path.join(DATA_DIR, "OUTPUT_agent_summary.txt")

SYSTEM_PROMPT = (
    "You are the Teamcenter Volume Health Analyst. "
    "Analyze the provided volume disk usage data and produce a structured health summary. "
    "Use ONLY the data given — never invent metrics, paths, or numbers. "
    "If something is missing, say so instead of guessing. "
    "Respond only via the requested structured schema, no extra text.\n\n"
    "Metrics explanation:\n"
    "  Each volume name (e.g. DefaultVolume) maps to a directory path.\n"
    "  used_gb  = used space on the drive that directory lives on\n"
    "  total_gb = total capacity of that drive\n"
    "  free_gb  = free space remaining on that drive\n"
    "  percent  = drive usage % (from the OS)\n"
    "  HEALTHY < 60%  |  MODERATE 60–89%  |  CRITICAL >= 90%\n\n"
    "Produce in a single response:\n"
    "1. overall_rating: HEALTHY | WATCH | WARNING | CRITICAL\n"
    "2. active_tc_volume_risk: TC operational impact statement\n"
    "3. anomalies: based on provided history analysis — RAPID_GROWTH, NEWLY_CRITICAL, "
    "PERSISTENTLY_ELEVATED\n"
    "4. recommendations: 3-6 concrete prioritized actions referencing drive names and percentages\n"
    "5. executive_summary: STRICT LIMIT of 1-2 short sentences (max ~40 words). Plain-language "
    "headline naming overall health and, if unhealthy, the single biggest issue only.\n"
    "6. confidence: 0.0-1.0 based on completeness of provided data\n"
    "7. health_score: 0.0-100.0 or null if sample is too small\n"
)


# --------------------------------------------------------------------------- #
# Structured output schemas
# --------------------------------------------------------------------------- #

class Anomaly(BaseModel):
    drive: str
    anomaly_type: Literal["RAPID_GROWTH", "NEWLY_CRITICAL", "PERSISTENTLY_ELEVATED", "OTHER"]
    description: str
    severity: Literal["low", "medium", "high", "critical"] = "medium"


class Recommendation(BaseModel):
    title: str
    description: str
    priority: Literal["low", "medium", "high", "critical"] = "medium"


class VolumeAnalysisResult(BaseModel):
    """Everything the single Bedrock call produces, in one combined schema."""
    overall_rating: Literal["HEALTHY", "WATCH", "WARNING", "CRITICAL"]
    active_tc_volume_risk: str
    anomalies: List[Anomaly] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    executive_summary: str = Field(description="1-2 sentences max, ~40 words.")
    confidence: float = Field(ge=0.0, le=1.0)
    health_score: Optional[float] = Field(default=None, ge=0.0, le=100.0)


class VolumeHealthResponse(BaseModel):
    """The single object VolumeHealthGraph.invoke() returns, success or failure."""
    status: Literal["success", "partial", "error"] = "success"
    overall_rating: str = ""
    executive_summary: str = ""
    active_tc_volume: str = ""
    active_tc_volume_usage: Optional[float] = None
    active_tc_volume_status: str = ""
    active_tc_volume_risk: str = ""
    drives_summary: str = ""
    anomalies: List[Anomaly] = Field(default_factory=list)
    recommendations: List[Recommendation] = Field(default_factory=list)
    actions_taken: str = ""
    health_score: Optional[float] = None
    confidence: float = 0.0
    error: Optional[str] = None


# --------------------------------------------------------------------------- #
# LangGraph state
# --------------------------------------------------------------------------- #

class GraphState(TypedDict, total=False):
    request: str
    # collect stage
    drives: list
    active_volume: str
    history_analysis: str
    is_valid: bool
    error: Optional[str]
    # analyze stage
    result: Optional[VolumeAnalysisResult]
    analyze_error: Optional[str]
    # health_check stage
    actions_taken: str
    health_report: str
    # final
    response: VolumeHealthResponse


# --------------------------------------------------------------------------- #
# VolumeHealthGraph
# --------------------------------------------------------------------------- #

class VolumeHealthGraph:
    """LangGraph-based Volume Health Analysis Agent using AWS Bedrock."""

    def __init__(self, model_name: str = DEFAULT_MODEL):
        self.model = ChatBedrockConverse(model=model_name)
        self._graph = self._build_graph()

    def invoke(self, request: str = "") -> VolumeHealthResponse:
        """Run the full workflow and return a VolumeHealthResponse."""
        state: GraphState = {"request": request, "is_valid": True}
        result = self._graph.invoke(state)
        return result["response"]

    # ── graph wiring ──────────────────────────────────────────────────────────

    def _build_graph(self):
        g = StateGraph(GraphState)
        g.add_node("collect", self._collect)
        g.add_node("analyze", self._analyze)
        g.add_node("health_check", self._health_check)
        g.add_node("assemble", self._assemble)

        g.add_edge(START, "collect")
        g.add_conditional_edges(
            "collect",
            lambda s: "analyze" if s.get("is_valid") else "assemble",
            {"analyze": "analyze", "assemble": "assemble"},
        )
        g.add_edge("analyze", "health_check")
        g.add_edge("health_check", "assemble")
        g.add_edge("assemble", END)
        return g.compile()

    # ── nodes ─────────────────────────────────────────────────────────────────

    def _collect(self, _state: GraphState) -> dict:
        """Collect fresh disk stats, run Find_Volume_InUse.exe, parse history."""
        assert _state is not None or True  # required LangGraph node signature
        try:
            import collect_volume_data as cvd

            rows = cvd.collect_drives()
            if not rows:
                return {
                    "is_valid": False,
                    "error": "No accessible drives found in volume_path_list.txt.",
                }
            cvd.write_report(rows)
            cvd.append_history(rows)
            active = cvd.run_find_volume_exe() or "UNKNOWN"

            return {
                "is_valid": True,
                "drives": rows,
                "active_volume": active,
                "history_analysis": self._parse_history(),
            }
        except Exception as exc:
            logger.error("collect failed: %s", exc)
            return {"is_valid": False, "error": f"Data collection failed: {exc}"}

    def _analyze(self, state: GraphState) -> dict:
        """Single Bedrock call producing the full structured analysis."""
        try:
            user_prompt = self._build_user_prompt(
                state.get("drives", []),
                state.get("active_volume", "UNKNOWN"),
                state.get("history_analysis", "No history available."),
            )
            result = self.model.with_structured_output(VolumeAnalysisResult).invoke(
                [SystemMessage(content=SYSTEM_PROMPT), HumanMessage(content=user_prompt)]
            )
            return {"result": result}
        except Exception as exc:
            logger.error("analyze failed: %s", exc)
            return {"result": None, "analyze_error": f"Analysis failed: {exc}"}

    def _health_check(self, _state: GraphState) -> dict:
        """Run health evaluation + optional volume switch via check_volume_health."""
        assert _state is not None or True  # required LangGraph node signature
        try:
            import check_volume_health as cvh

            drives_raw = cvh.parse_report()
            current = cvh.read_current_volume()
            switched, next_vol, switch_note = cvh.maybe_switch(drives_raw, current)
            report = cvh.build_report(drives_raw, current, switched, next_vol, switch_note)

            with open(os.path.join(DATA_DIR, "OUTPUT_health_report.txt"), "w", encoding="utf-8") as f:
                f.write(report)

            actions = (
                f"Volume switch performed: {current} → {next_vol}. {switch_note}"
                if switched
                else "No switch required."
            )
            return {"actions_taken": actions, "health_report": report}
        except Exception as exc:
            logger.error("health_check failed: %s", exc)
            return {"actions_taken": f"Health check error: {exc}", "health_report": ""}

    def _assemble(self, state: GraphState) -> dict:
        if not state.get("is_valid"):
            return {
                "response": VolumeHealthResponse(
                    status="error",
                    error=state.get("error") or "Invalid input.",
                )
            }

        result = state.get("result")
        drives = state.get("drives", [])
        active = state.get("active_volume", "UNKNOWN")
        actions = state.get("actions_taken", "No switch required.")

        if not result:
            return {
                "response": VolumeHealthResponse(
                    status="partial",
                    executive_summary="Analysis could not be generated.",
                    active_tc_volume=active,
                    error=state.get("analyze_error") or "Analysis step failed.",
                )
            }

        drives_lines = []
        for d in drives:
            pct = d.get("percent", 0)
            status = "CRITICAL" if pct >= 90 else ("MODERATE" if pct >= 60 else "HEALTHY")
            drives_lines.append(
                f"  {d.get('name')}  {pct:.1f}%  [{status}]  {d.get('mountpoint')}"
            )

        active_drive = next((d for d in drives if d["name"] == active), None)
        active_pct = active_drive["percent"] if active_drive else None
        if active_pct is None:
            active_status = "UNKNOWN"
        elif active_pct >= 90:
            active_status = "CRITICAL"
        elif active_pct >= 60:
            active_status = "MODERATE"
        else:
            active_status = "HEALTHY"

        return {
            "response": VolumeHealthResponse(
                status="success",
                overall_rating=result.overall_rating,
                executive_summary=result.executive_summary,
                active_tc_volume=active,
                active_tc_volume_usage=active_pct,
                active_tc_volume_status=active_status,
                active_tc_volume_risk=result.active_tc_volume_risk,
                drives_summary="\n".join(drives_lines),
                anomalies=result.anomalies,
                recommendations=result.recommendations,
                actions_taken=actions,
                health_score=result.health_score,
                confidence=result.confidence,
            )
        }

    # ── helpers ───────────────────────────────────────────────────────────────

    def _build_user_prompt(self, drives: list, active_volume: str, history_analysis: str) -> str:
        lines = [f"Active TC volume: {active_volume}", "", "DRIVE DISK USAGE:"]
        for d in drives:
            pct = d.get("percent", 0)
            status = "CRITICAL" if pct >= 90 else ("MODERATE" if pct >= 60 else "HEALTHY")
            lines.append(
                f"  {d.get('name')}  {pct:.1f}%  [{status}]"
                f"  used={d.get('used_gb')}  free={d.get('free_gb')}  total={d.get('total_gb')}"
                f"  mount={d.get('mountpoint')}  fs={d.get('fstype')}"
            )
        lines += ["", "HISTORY ANOMALY ANALYSIS:", history_analysis, ""]
        note = (
            "sufficient for a numeric health score."
            if len(drives) >= 1
            else "too small — return null for health_score."
        )
        lines.append(f"Sample size ({len(drives)} drive(s)) is {note}")
        return "\n".join(lines)

    @staticmethod
    def _parse_history() -> str:
        """Deterministic anomaly detection from output_usage_history.txt."""
        history_file = os.path.join(DATA_DIR, "output_usage_history.txt")
        if not os.path.exists(history_file):
            return "No history file found — this may be the first run."

        CRIT, MOD = 90, 60
        per_drive: dict = defaultdict(list)
        with open(history_file, "r", encoding="utf-8") as f:
            for line in f:
                parts = line.strip().split("|")
                if len(parts) != 3:
                    continue
                ts, drive, pct_str = parts
                try:
                    per_drive[drive.strip()].append(
                        (ts.strip(), float(pct_str.replace("%", "")))
                    )
                except ValueError:
                    continue

        if not per_drive:
            return "History file contains no parseable data."

        anomaly_list = []
        lines = []
        for drive, readings in sorted(per_drive.items()):
            pcts = [p for _, p in readings]
            latest   = pcts[-1]
            previous = pcts[-2] if len(pcts) >= 2 else latest
            oldest   = pcts[0]
            delta_recent = latest - previous
            delta_total  = latest - oldest
            trend = "↑" if delta_total > 0.1 else ("↓" if delta_total < -0.1 else "→")
            flags = []

            if len(pcts) >= 2 and delta_recent >= 5:
                flags.append(f"RAPID_GROWTH (+{delta_recent:.1f}% since last reading)")
                anomaly_list.append(f"{drive}: rapid growth +{delta_recent:.1f}%")

            if len(pcts) >= 2 and latest >= CRIT and previous < CRIT:
                flags.append("NEWLY_CRITICAL")
                anomaly_list.append(f"{drive}: newly crossed critical threshold")

            recent = pcts[-min(3, len(pcts)):]
            if len(recent) >= 3 and all(p >= MOD for p in recent):
                flags.append(f"PERSISTENTLY_ELEVATED (last {len(recent)} readings ≥{MOD}%)")
                anomaly_list.append(f"{drive}: persistently elevated")

            lines.append(
                f"  {drive}  now={latest:.1f}%  prev={previous:.1f}%  "
                f"oldest={oldest:.1f}%  trend={trend}{abs(delta_total):.1f}%  "
                f"({len(pcts)} readings)  flags: {' | '.join(flags) if flags else 'none'}"
            )

        lines.append(f"Total anomalies detected: {len(anomaly_list)}")
        return "\n".join(lines)


# --------------------------------------------------------------------------- #
# Module-level entry point — backward-compatible with web_runner.py
# --------------------------------------------------------------------------- #

_graph_instance: VolumeHealthGraph | None = None


def _get_graph() -> VolumeHealthGraph:
    global _graph_instance
    if _graph_instance is None:
        _graph_instance = VolumeHealthGraph()
    return _graph_instance


def run_agent(request: str = "") -> str:
    """Run the volume health agent and return formatted text (saves OUTPUT_agent_summary.txt)."""
    response = _get_graph().invoke(request)
    summary = _format_as_text(response)

    os.makedirs(DATA_DIR, exist_ok=True)
    with open(SUMMARY_FILE, "w", encoding="utf-8") as f:
        f.write(f"Generated: {time.strftime('%d-%b-%Y %I:%M %p')}\n\n")
        f.write(summary)

    return summary


def _format_as_text(r: VolumeHealthResponse) -> str:
    """Serialize VolumeHealthResponse to the section-headed text format home.html parses."""
    if r.status == "error":
        return f"OVERALL HEALTH RATING: ERROR\n\nError: {r.error}"

    lines = [f"OVERALL HEALTH RATING: {r.overall_rating or 'UNKNOWN'}", ""]

    lines += [
        "ACTIVE TC VOLUME",
        f"  Name   : {r.active_tc_volume}",
        f"  Usage  : {r.active_tc_volume_usage if r.active_tc_volume_usage is not None else 'N/A'}%"
        f"  Status: {r.active_tc_volume_status}",
        f"  Risk   : {r.active_tc_volume_risk or 'N/A'}",
        "",
    ]

    lines += ["ALL DRIVES", r.drives_summary or "  No drives data available.", ""]

    lines.append("ANOMALIES DETECTED")
    if r.anomalies:
        for a in r.anomalies:
            lines.append(f"  • [{a.severity.upper()}] {a.drive}: {a.description}")
    else:
        lines.append("  None detected")
    lines.append("")

    lines += ["ACTIONS TAKEN", f"  {r.actions_taken}", ""]

    lines.append("RECOMMENDATIONS")
    if r.recommendations:
        for i, rec in enumerate(r.recommendations, 1):
            lines.append(f"  {i}. [{rec.priority.upper()}] {rec.title}: {rec.description}")
    else:
        lines.append("  No recommendations.")

    if r.executive_summary:
        lines += ["", "EXECUTIVE SUMMARY", f"  {r.executive_summary}"]

    return "\n".join(lines)


if __name__ == "__main__":
    request = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    print("=" * 70)
    print("  VOLUME HEALTH ANALYSIS AGENT  (LangGraph + AWS Bedrock)")
    print("=" * 70)
    print()
    result = run_agent(request)
    print(result)
