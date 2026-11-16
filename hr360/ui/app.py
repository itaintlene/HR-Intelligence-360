"""Streamlit HR dashboard.   Run:  streamlit run hr360/ui/app.py

The UI only talks to HRRunner (the graph) - no business logic lives here. Authentication is
simulated with a role selector; the planned React/Clerk frontend will replace the sidebar login
and call the same runner behind FastAPI.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from hr360.agents.base import AgentContext  # noqa: E402
from hr360.config import Settings  # noqa: E402
from hr360.data.db import HRDatabase, public_employee_view  # noqa: E402
from hr360.data.sample_docs import generate_sample_docs  # noqa: E402
from hr360.data.synthetic import build_database  # noqa: E402
from hr360.graph.runner import HRRunner  # noqa: E402
from hr360.reporting.report import findings_dataframe  # noqa: E402
from hr360.security.rbac import PERMISSIONS, ROLES, role_can  # noqa: E402

st.set_page_config(page_title="HR Intelligence 360", page_icon="🧭", layout="wide")

EXAMPLES = {
    "Policy question": "How many days of earned leave can I carry forward?",
    "Onboarding": "Run onboarding for new joiners EMP-1031, EMP-1032 and EMP-1035",
    "Audit summary": "Give me an audit summary of all employee records",
    "Leave summary": "Summarize pending leave requests",
}
SEV_ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "🟩"}


@st.cache_resource(show_spinner="Starting agents (first run loads the embedding model)...")
def get_runner() -> HRRunner:
    settings = Settings()
    settings.ensure_dirs()
    if not HRDatabase(settings.hr_target).has_data():
        db = build_database(settings.hr_target, settings.as_of)
        generate_sample_docs(settings.sample_docs_dir, db, settings.as_of)
    return HRRunner(AgentContext.build(settings))


runner = get_runner()
ctx = runner.ctx

# ----------------------------------------------------------------- sidebar
with st.sidebar:
    st.title("🧭 HR Intelligence 360")
    st.caption("Multi-agent HR automation & audit · synthetic data")
    user_id = st.text_input("User", "hr.demo")
    role = st.selectbox("Role", ROLES, index=1, help="Simulated login. RBAC is enforced in the graph.")
    st.markdown(f"**Permissions:** {', '.join(sorted(PERMISSIONS[role]))}")
    st.divider()
    st.caption(f"As-of date: **{ctx.settings.as_of}**  ·  LLM: **{'on' if ctx.llm.available else 'offline (deterministic fallbacks)'}**")
    if st.button("Re-seed synthetic data"):
        db = build_database(ctx.settings.hr_target, ctx.settings.as_of)
        generate_sample_docs(ctx.settings.sample_docs_dir, db, ctx.settings.as_of)
        st.success("Synthetic data regenerated.")

if "last" not in st.session_state:
    st.session_state.last = None


def save_uploads(files) -> list[str]:
    dest = Path(ctx.settings.sample_docs_dir).parent / "uploads"
    dest.mkdir(parents=True, exist_ok=True)
    paths = []
    for f in files or []:
        p = dest / Path(f.name).name  # strip any path components
        p.write_bytes(f.getvalue())
        paths.append(str(p))
    return paths


def render_result(res: dict) -> None:
    fr, state = res.get("final_response") or {}, res.get("state") or {}
    if res["status"] == "awaiting_approval":
        st.warning(f"⏸ Request {res['request_id']} is waiting for human approval of "
                   f"{len(res['interrupt']['drafts'])} email draft(s). Open the **Approvals** tab.")
    elif fr:
        {"completed": st.success, "partial": st.warning, "denied": st.error, "unsupported": st.info}.get(fr["status"], st.write)(
            f"{fr['status'].upper()} · workflow `{fr['task_type']}` · request {fr['request_id']}")
    if fr.get("message"):
        st.markdown(fr["message"])
    pa = state.get("policy_answer")
    if pa and pa.get("citations"):
        with st.expander("📚 Sources", expanded=True):
            for c in pa["citations"]:
                st.markdown(f"- **{c['citation']}** (`{c['doc_file']}`)")
            st.caption(f"Answer method: {pa['method']} · citations validated: {pa['validated']}")
    if state.get("audit_findings"):
        st.subheader("Audit findings")
        show_findings(state["audit_findings"])
    if state.get("workflow_recommendations"):
        st.subheader("Workflow recommendations")
        for r in state["workflow_recommendations"]:
            with st.expander(f"{'🧑‍⚖️ ' if r['requires_human_decision'] else ''}[{r['priority'].upper()}] {r['title']}"):
                st.write(r["detail"])
                if r["items"] and r["kind"] == "checklist":
                    st.dataframe(pd.DataFrame(r["items"]), hide_index=True, use_container_width=True)
    if state.get("generated_email_drafts"):
        st.subheader("Email drafts (never sent without approval)")
        for d in state["generated_email_drafts"]:
            with st.expander(f"{d['draft_id']} → {d['recipient_masked']} · {d['status']}"):
                st.text(f"Subject: {d['subject']}\n\n{d['body']}")
    if fr.get("report_paths"):
        c1, c2 = st.columns(2)
        for col, (kind, label, mime) in zip((c1, c2), (("pdf", "⬇ PDF report", "application/pdf"), ("csv", "⬇ CSV findings", "text/csv"))):
            p = Path(fr["report_paths"][kind])
            col.download_button(label, p.read_bytes(), file_name=p.name, mime=mime, key=f"{kind}-{fr['request_id']}")
    if fr.get("errors"):
        with st.expander("⚠ Errors"):
            st.write(fr["errors"])


def show_findings(findings: list[dict]) -> None:
    df = findings_dataframe(findings)
    c1, c2 = st.columns(2)
    sev = c1.multiselect("Severity", ["critical", "high", "medium", "low"], default=["critical", "high", "medium", "low"], key=f"sev{len(findings)}")
    cls = c2.multiselect("Classification", ["confirmed_violation", "potential_discrepancy"],
                         default=["confirmed_violation", "potential_discrepancy"], key=f"cls{len(findings)}")
    df = df[df["severity"].isin(sev) & df["classification"].isin(cls)]
    df.insert(0, "", df["severity"].map(SEV_ICON))
    st.dataframe(df.drop(columns=["evidence"]), hide_index=True, use_container_width=True)
    with st.expander("Evidence"):
        st.dataframe(df[["employee_id", "rule_id", "evidence"]], hide_index=True, use_container_width=True)


tab_assist, tab_approve, tab_dash, tab_emp, tab_obs, tab_arch = st.tabs(
    ["💬 Assistant", "✅ Approvals", "📊 Audit dashboard", "👥 Employees", "🔍 Observability", "🏗 Architecture"])

# ----------------------------------------------------------------- assistant
with tab_assist:
    st.subheader("Ask or request an HR task")
    cols = st.columns(len(EXAMPLES))
    for col, (label, text) in zip(cols, EXAMPLES.items()):
        if col.button(label, use_container_width=True):
            st.session_state.query = text
    query = st.text_area("Request", key="query", height=90, placeholder="e.g. How many sick days do I get?")
    uploads = st.file_uploader("Documents (PDF, DOCX, PNG/JPG scans) for audit / onboarding", type=["pdf", "docx", "png", "jpg", "jpeg", "txt"],
                               accept_multiple_files=True)
    if uploads and not role_can(role, "document_upload"):
        st.error("Your role cannot upload documents.")
    if st.button("▶ Run", type="primary", disabled=not query.strip()):
        with st.spinner("Agents working..."):
            st.session_state.last = runner.run(query.strip(), user_id, role, save_uploads(uploads))
    if st.session_state.last:
        render_result(st.session_state.last)

# ----------------------------------------------------------------- approvals
with tab_approve:
    st.subheader("Pending human approvals")
    pending = runner.list_requests("awaiting_approval")
    if not pending:
        st.info("Nothing waiting for approval.")
    for req in pending:
        snap = runner.get(req["request_id"])
        if snap["status"] != "awaiting_approval":
            continue
        payload = snap["interrupt"]
        with st.container(border=True):
            st.markdown(f"**{req['request_id']}** · requested by `{req['user_id']}` · _{req['query']}_")
            chosen = []
            for d in payload["drafts"]:
                if st.checkbox(f"{d['draft_id']} → {d['recipient_masked']}: {d['subject']}", value=True, key=f"chk-{req['request_id']}-{d['draft_id']}"):
                    chosen.append(d["draft_id"])
                st.code(d["body"], language=None)
            comment = st.text_input("Comment", key=f"cm-{req['request_id']}")
            if not role_can(role, "approve_actions"):
                st.warning(f"Role '{role}' cannot approve actions (requires hr_manager or admin).")
            a, b = st.columns(2)
            if a.button("✅ Approve selected", key=f"ok-{req['request_id']}"):
                res = runner.resume(req["request_id"], user_id, role, True, comment, chosen)
                st.session_state.last = res
                st.rerun()
            if b.button("❌ Reject all", key=f"no-{req['request_id']}"):
                st.session_state.last = runner.resume(req["request_id"], user_id, role, False, comment)
                st.rerun()
    if ctx.settings.outbox_path.exists():
        with st.expander("Outbox (approved emails, delivery simulated)"):
            st.code(ctx.settings.outbox_path.read_text(encoding="utf-8")[-4000:], language="json")

# ----------------------------------------------------------------- dashboard
with tab_dash:
    st.subheader("Compliance audit")
    if not role_can(role, "run_audit"):
        st.info("Your role cannot run audits.")
    elif st.button("Run full audit (Workflow D)"):
        with st.spinner("Auditing..."):
            st.session_state.dash = runner.run("Give me an audit summary of all employee records", user_id, role)
    dash = st.session_state.get("dash")
    if dash and dash["state"].get("audit_findings"):
        s = dash["state"]["audit_summary"]
        m = st.columns(4)
        m[0].metric("Findings", s["total_findings"])
        m[1].metric("Employees affected", s["employees_affected"])
        m[2].metric("Confirmed violations", s["by_classification"].get("confirmed_violation", 0))
        m[3].metric("Potential discrepancies", s["by_classification"].get("potential_discrepancy", 0))
        left, right = st.columns(2)
        left.bar_chart(pd.Series(s["by_severity"], name="findings"))
        right.bar_chart(pd.Series(s["by_rule"], name="findings"), horizontal=True)
        st.info(s["narrative"])
        show_findings(dash["state"]["audit_findings"])
        render_result({**dash, "state": {}})

# ----------------------------------------------------------------- employees
with tab_emp:
    st.subheader("Employee directory")
    if not role_can(role, "view_employee_masked"):
        st.error("Access restricted: your role cannot view employee records.")
    else:
        full = role_can(role, "view_employee_full")
        st.caption("Full records" if full else "Sensitive fields masked/hidden for your role")
        ctx.audit_log.record("view_employee_directory", actor=user_id, role=role, agent="ui", detail={"full": full})
        st.dataframe(public_employee_view(ctx.db.employees(), full), hide_index=True, use_container_width=True)

# ----------------------------------------------------------------- observability
with tab_obs:
    st.subheader("Execution trace")
    last = st.session_state.last
    if last:
        stat = last["state"].get("agent_execution_status", {})
        st.dataframe(pd.DataFrame([{"agent": k, **v} for k, v in stat.items()]), hide_index=True, use_container_width=True)
    st.subheader("Request history")
    st.dataframe(pd.DataFrame(runner.list_requests()), hide_index=True, use_container_width=True)
    if role_can(role, "view_audit_log"):
        st.subheader("Audit log")
        st.dataframe(pd.DataFrame(ctx.audit_log.fetch(limit=200)), hide_index=True, use_container_width=True)
    else:
        st.caption("Audit log is visible to admins only.")

# ----------------------------------------------------------------- architecture
with tab_arch:
    st.subheader("LangGraph workflow")
    png = ROOT / "docs" / "workflow_graph.png"
    if png.exists():
        st.image(str(png))
    mmd = ROOT / "docs" / "workflow_graph.mmd"
    if mmd.exists():
        with st.expander("Mermaid source"):
            st.code(mmd.read_text(encoding="utf-8"), language="text")
    arch = ROOT / "docs" / "ARCHITECTURE.md"
    if arch.exists():
        st.markdown(arch.read_text(encoding="utf-8"))
