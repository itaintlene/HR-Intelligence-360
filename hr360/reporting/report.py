"""PDF (ReportLab) and CSV audit report generation. Deterministic - no LLM."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

SEV_COLORS = {"critical": "#b71c1c", "high": "#d84315", "medium": "#f9a825", "low": "#558b2f"}


def findings_dataframe(findings: list[dict]) -> pd.DataFrame:
    cols = ["employee_id", "rule_id", "severity", "classification", "title", "recommendation", "evidence"]
    if not findings:
        return pd.DataFrame(columns=cols)
    df = pd.DataFrame(findings)
    df["evidence"] = df["evidence"].map(lambda e: json.dumps(e, default=str))
    return df[cols]


def _p(text: str, style) -> Paragraph:
    text = str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return Paragraph(text, style)


def generate_report(request_id: str, task_type: str, state: dict, out_dir: Path, as_of) -> dict:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    findings = state.get("audit_findings") or []
    summary = state.get("audit_summary") or {}
    recs = state.get("workflow_recommendations") or []
    drafts = state.get("generated_email_drafts") or []

    csv_path = out_dir / f"{request_id}_findings.csv"
    findings_dataframe(findings).to_csv(csv_path, index=False)

    pdf_path = out_dir / f"{request_id}_report.pdf"
    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    doc = SimpleDocTemplate(str(pdf_path), pagesize=landscape(A4), leftMargin=28, rightMargin=28, topMargin=28, bottomMargin=28,
                            title=f"HR Intelligence 360 report {request_id}")
    els = [Paragraph("HR Intelligence 360 - Audit Report", styles["Title"]),
           _p(f"Request: {request_id}   |   Workflow: {task_type}   |   As of: {as_of}   |   Scope: {summary.get('scope', 'n/a')}",
              styles["Normal"]), Spacer(1, 10),
           Paragraph("Synthetic data - prototype output. Findings are produced by a deterministic rules engine; "
                     "narrative text is explanatory only.", small), Spacer(1, 10)]

    if summary:
        els.append(Paragraph("Summary", styles["Heading2"]))
        sev = summary.get("by_severity", {})
        cls = summary.get("by_classification", {})
        rows = [["Total findings", summary.get("total_findings", 0), "Employees affected", summary.get("employees_affected", 0)],
                ["Confirmed violations", cls.get("confirmed_violation", 0), "Potential discrepancies", cls.get("potential_discrepancy", 0)],
                ["Critical / High", f"{sev.get('critical', 0)} / {sev.get('high', 0)}", "Medium / Low", f"{sev.get('medium', 0)} / {sev.get('low', 0)}"]]
        t = Table(rows, colWidths=[140, 90, 140, 90])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.4, colors.grey), ("BACKGROUND", (0, 0), (0, -1), colors.whitesmoke),
                               ("BACKGROUND", (2, 0), (2, -1), colors.whitesmoke), ("FONTSIZE", (0, 0), (-1, -1), 9)]))
        els += [t, Spacer(1, 8), _p(summary.get("narrative", ""), styles["BodyText"]), Spacer(1, 10)]

    els.append(Paragraph("Findings", styles["Heading2"]))
    if findings:
        data = [["Employee", "Rule", "Severity", "Classification", "Finding", "Recommendation"]]
        for f in findings:
            data.append([f["employee_id"] or "-", _p(f["rule_id"], small), f["severity"].upper(),
                         "Confirmed" if f["classification"] == "confirmed_violation" else "Potential",
                         _p(f["title"], small), _p(f["recommendation"], small)])
        t = Table(data, repeatRows=1, colWidths=[62, 130, 52, 62, 250, 190])
        style = [("GRID", (0, 0), (-1, -1), 0.3, colors.grey), ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#263238")),
                 ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("FONTSIZE", (0, 0), (-1, -1), 8), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        for i, f in enumerate(findings, start=1):
            style.append(("TEXTCOLOR", (2, i), (2, i), colors.HexColor(SEV_COLORS[f["severity"]])))
        t.setStyle(TableStyle(style))
        els.append(t)
    else:
        els.append(Paragraph("No findings for the audited scope.", styles["BodyText"]))

    if recs or drafts:
        els += [Spacer(1, 12), Paragraph("Recommended actions (require human approval)", styles["Heading2"])]
        for r in recs[:40]:
            els.append(_p(f"[{r['priority'].upper()}] {r['title']}" + (f" - {r['detail']}" if r.get("detail") else ""), small))
        for d in drafts:
            els.append(_p(f"Email draft {d['draft_id']} to {d['recipient_masked']}: {d['subject']} (status: {d['status']})", small))
    doc.build(els)
    return {"pdf": str(pdf_path), "csv": str(csv_path)}
