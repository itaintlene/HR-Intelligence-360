"""Document Intelligence Agent."""
import pytest

from hr360.agents.document_agent import DocumentIntelligenceAgent, parse_date


@pytest.fixture(scope="module")
def agent(ctx):
    return DocumentIntelligenceAgent(ctx)


def rec(agent, docs, name):
    return agent.process_file(docs[name])[0]


def test_pdf_offer_letter_extraction(agent, sample_docs):
    r = rec(agent, sample_docs, "offer_letter_EMP-1033.pdf")
    assert (r.document_type, r.employee_id, r.joining_date) == ("offer_letter", "EMP-1033", "2026-11-13")
    assert r.department and r.designation and not r.missing_fields and not r.ocr_used


def test_docx_with_alternate_date_format(agent, sample_docs):
    r = rec(agent, sample_docs, "offer_letter_EMP-1034.docx")
    assert r.employee_id == "EMP-1034" and r.joining_date == "2026-11-11"


def test_scanned_png_uses_ocr(agent, sample_docs):
    r = rec(agent, sample_docs, "id_proof_EMP-1008_scan.png")
    assert r.ocr_used and r.document_type == "id_proof" and r.employee_id == "EMP-1008"
    assert r.expiry_date == "2026-10-27"
    assert "*" in r.national_id_masked


def test_image_only_pdf_falls_back_to_ocr(agent, sample_docs):
    r = rec(agent, sample_docs, "id_proof_EMP-1011_scanned.pdf")
    assert r.ocr_used and r.employee_id == "EMP-1011" and r.expiry_date == "2026-12-01"


def test_missing_employee_id_is_reported(agent, sample_docs):
    r = rec(agent, sample_docs, "nda_unsigned_no_id.docx")
    assert r.document_type == "nda" and r.employee_id is None and "employee_id" in r.missing_fields


def test_prompt_injection_text_is_flagged_and_stripped(agent, sample_docs):
    r = rec(agent, sample_docs, "address_proof_EMP-1031_injection.pdf")
    assert len(r.injection_flags) == 2 and r.employee_id == "EMP-1031"


def test_low_confidence_when_label_value_unparseable(agent, tmp_path):
    p = tmp_path / "x.txt"
    p.write_text("Offer Letter\nEmployee ID: EMP-1040\nDate of Joining: sometime soon\n")
    r = agent.process_file(p)[0]
    assert "joining_date" in r.low_confidence_fields and "joining_date" in r.missing_fields


def test_sensitive_values_never_stored_raw(agent, sample_docs, ctx):
    r = rec(agent, sample_docs, "id_proof_EMP-1008_scan.png")
    raw = ctx.db.get_employee("EMP-1008")["national_id"]
    assert raw not in r.model_dump_json()


def test_bad_file_does_not_abort_batch(agent, sample_docs, tmp_path):
    bad = tmp_path / "evil.exe"
    bad.write_bytes(b"MZ")
    out = agent.run({"uploaded_files": [str(bad), sample_docs["offer_letter_EMP-1033.pdf"]]})
    assert len(out["extracted_employee_data"]) == 1 and len(out["errors"]) == 1
    assert [m["status"] for m in out["document_metadata"]] == ["failed", "processed"]


@pytest.mark.parametrize("raw,iso", [("2026-11-13", "2026-11-13"), ("13/11/2026", "2026-11-13"),
                                     ("13 November 2026", "2026-11-13"), ("Nov 13, 2026", "2026-11-13"),
                                     ("1st November 2026", "2026-11-01"), ("garbage", None)])
def test_date_parsing(raw, iso):
    assert parse_date(raw) == iso
