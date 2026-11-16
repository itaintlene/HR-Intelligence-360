"""Agent 3 - Document Intelligence Agent.

PDF (PyMuPDF) / DOCX (python-docx) / scanned images + image-only PDF pages (Tesseract OCR)
-> text -> prompt-injection stripping -> classification -> field extraction (regex + spaCy
PhraseMatcher) -> Pydantic-validated ExtractedEmployeeRecord.

No LLM is used here: document text is untrusted, so it never reaches a prompt.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from hr360.agents.base import AgentContext
from hr360.config import configure_tesseract
from hr360.models import ExtractedEmployeeRecord
from hr360.security.rbac import mask_id
from hr360.security.sanitize import strip_injection

log = logging.getLogger("hr360.docintel")

MAX_FILE_BYTES = 15 * 1024 * 1024
SUPPORTED = {".pdf", ".docx", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".txt"}

DOC_KEYWORDS: dict[str, list[str]] = {
    "offer_letter": ["offer of employment", "pleased to offer", "offer letter", "date of joining", "annual ctc", "compensation"],
    "id_proof": ["passport", "identity card", "driving licence", "driving license", "national id", "id card", "id proof", "date of birth"],
    "address_proof": ["address proof", "proof of address", "utility bill", "rental agreement", "residential address"],
    "tax_form": ["tax declaration", "form 12bb", "tax form", "income tax", "tax withholding"],
    "nda": ["non-disclosure", "nda", "confidential information", "confidentiality agreement"],
    "bank_details": ["bank account", "ifsc", "account number", "bank details", "cancelled cheque"],
    "education_certificate": ["degree", "university", "certificate of", "graduation", "bachelor", "master of"],
    "leave_request": ["leave request", "leave application", "reason for leave", "leave from"],
}

_DATE_FORMATS = ["%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y"]
_LABELS = {
    "joining_date": r"(?:date of joining|joining date|date of commencement|start date|doj)",
    "expiry_date": r"(?:expiry date|date of expiry|valid until|valid till|expires(?: on)?)",
    "issue_date": r"(?:issue date|date of issue|issued on|dated)",
    "department": r"(?:department|dept\.?)",
    "designation": r"(?:designation|job title|position|role)",
    "employee_id": r"(?:employee id|emp(?:loyee)? (?:no|number|code)|staff id)",
}
EMP_ID_RX = re.compile(r"\bEMP[-\s_]?(\d{3,6})\b", re.IGNORECASE)
NATIONAL_ID_RX = re.compile(r"\b(?:SYN\d{7,10}|[A-Z]{1,2}\d{7,9})\b")


def parse_date(raw: str) -> str | None:
    raw = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", raw.strip().strip(".,;")).strip()
    for chunk in (raw, " ".join(raw.split()[:3]), " ".join(raw.split()[:4])):
        for fmt in _DATE_FORMATS:
            try:
                return datetime.strptime(chunk, fmt).date().isoformat()
            except ValueError:
                continue
    return None


class DocumentIntelligenceAgent:
    name = "document_intelligence"

    def __init__(self, ctx: AgentContext):
        self.ctx = ctx
        self.rs = ctx.ruleset
        self.min_conf = float(self.rs.settings.get("extraction_min_confidence", 0.70))
        self._nlp = None
        self._matcher = None
        self.ocr_available = configure_tesseract()

    # ------------------------------------------------------------------ spaCy
    def _ensure_nlp(self):
        if self._nlp is not None:
            return
        try:
            import spacy
            from spacy.matcher import PhraseMatcher
        except ImportError:  # slim/serverless install: fall back to plain vocabulary matching
            self._nlp, self.has_ner = "fallback", False
            return
        try:
            nlp = spacy.load("en_core_web_sm", disable=["lemmatizer"])
            self.has_ner = True
        except Exception:
            nlp = spacy.blank("en")
            self.has_ner = False
        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        for label, key in (("DEPARTMENT", "departments"), ("DESIGNATION", "designations")):
            terms = self.rs.vocab.get(key, [])
            if terms:
                matcher.add(label, [nlp.make_doc(t) for t in terms])
        self._nlp, self._matcher = nlp, matcher

    def _phrase_hits(self, text: str) -> dict[str, list[str]]:
        self._ensure_nlp()
        if self._nlp == "fallback":
            hits = {"DEPARTMENT": [], "DESIGNATION": []}
            for label, key in (("DEPARTMENT", "departments"), ("DESIGNATION", "designations")):
                for term in sorted(self.rs.vocab.get(key, []), key=len, reverse=True):
                    m = re.search(rf"{re.escape(term)}", text, re.IGNORECASE)
                    if m:
                        hits[label].append(term)
            return hits
        doc = self._nlp.make_doc(text) if not self.has_ner else self._nlp(text)
        hits: dict[str, list[str]] = {"DEPARTMENT": [], "DESIGNATION": []}
        for mid, s, e in self._matcher(doc):
            hits[self._nlp.vocab.strings[mid]].append(doc[s:e].text)
        return hits

    # ------------------------------------------------------------------ loading
    def load_text(self, path: Path) -> tuple[str, int, bool, float]:
        """-> (text, pages, ocr_used, ocr_confidence in 0..1; 1.0 when no OCR was needed)"""
        suffix = path.suffix.lower()
        if suffix not in SUPPORTED:
            raise ValueError(f"Unsupported file type: {suffix}")
        if path.stat().st_size > MAX_FILE_BYTES:
            raise ValueError("File too large (limit 15 MB)")
        if suffix == ".txt":
            return path.read_text(encoding="utf-8", errors="ignore"), 1, False, 1.0
        if suffix == ".docx":
            import docx
            d = docx.Document(str(path))
            parts = [p.text for p in d.paragraphs]
            for t in d.tables:
                for row in t.rows:
                    parts.append(" | ".join(c.text.strip() for c in row.cells))
            return "\n".join(parts), 1, False, 1.0
        if suffix == ".pdf":
            try:
                import pymupdf as fitz
            except ImportError:  # slim install (serverless): text-layer PDFs only, no page rendering/OCR
                from pypdf import PdfReader
                pages = [(p.extract_text() or "").strip() for p in PdfReader(str(path)).pages]
                if any(len(t) < 30 for t in pages):
                    raise RuntimeError("PDF has scanned (image-only) pages; OCR is not available in this deployment")
                return "\n".join(pages), len(pages), False, 1.0
            texts, confs, ocr_used = [], [], False
            with fitz.open(str(path)) as pdf:
                for page in pdf:
                    txt = page.get_text().strip()
                    if len(txt) >= 30:
                        texts.append(txt)
                        continue
                    pix = page.get_pixmap(dpi=200)  # image-only page -> OCR
                    from PIL import Image
                    import io
                    img = Image.open(io.BytesIO(pix.tobytes("png")))
                    otxt, conf = self._ocr(img)
                    texts.append(otxt)
                    confs.append(conf)
                    ocr_used = True
                pages = len(pdf)
            return "\n".join(texts), pages, ocr_used, (sum(confs) / len(confs) if confs else 1.0)
        from PIL import Image
        with Image.open(path) as img:
            txt, conf = self._ocr(img.convert("RGB"))
        return txt, 1, True, conf

    def _ocr(self, img) -> tuple[str, float]:
        if not self.ocr_available:
            raise RuntimeError("Tesseract OCR is not installed/configured")
        import pytesseract
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
        confs = [float(c) for c, w in zip(data["conf"], data["text"]) if str(c) != "-1" and w.strip()]
        text = pytesseract.image_to_string(img)
        return text, (sum(confs) / len(confs) / 100.0 if confs else 0.0)

    # ------------------------------------------------------------------ NLP
    def classify(self, text: str) -> tuple[str, float]:
        low, head = text.lower(), text[:250].lower()
        scores = {}
        for dtype, kws in DOC_KEYWORDS.items():
            s = sum((2 if kw in head else 1) for kw in kws if kw in low)
            if s:
                scores[dtype] = s
        if not scores:
            return "other", 0.30
        best = max(scores, key=lambda k: scores[k])
        return best, min(0.95, 0.40 + 0.15 * scores[best])

    def _labeled(self, text: str, key: str) -> str | None:
        m = re.search(rf"(?im)^\s*{_LABELS[key]}\s*[:\-]\s*(.+?)\s*$", text)
        return m.group(1).strip() if m else None

    def extract_fields(self, text: str, ocr_conf: float) -> tuple[dict, dict]:
        """-> (values, confidences). Labeled values score higher than inferred ones; OCR scales both."""
        scale = 1.0 if ocr_conf >= 0.999 else max(0.4, min(1.0, ocr_conf + 0.15))
        vals: dict = {}
        conf: dict = {}

        def put(k, v, c):
            if v:
                vals[k], conf[k] = v, round(c * scale, 2)

        raw = self._labeled(text, "employee_id")
        m = EMP_ID_RX.search(raw or "") or EMP_ID_RX.search(text)
        if m:
            put("employee_id", f"EMP-{m.group(1)}", 0.95 if raw and EMP_ID_RX.search(raw) else 0.75)

        for key in ("joining_date", "expiry_date", "issue_date"):
            raw = self._labeled(text, key)
            iso = parse_date(raw) if raw else None
            if iso:
                put(key, iso, 0.95)
            elif raw:
                conf[key] = 0.3  # label found, value unparseable -> low confidence, no value
                vals[key] = None

        hits = self._phrase_hits(text)
        for key, label in (("department", "DEPARTMENT"), ("designation", "DESIGNATION")):
            raw = self._labeled(text, key)
            if raw:
                canon = next((h for h in self._phrase_hits(raw)[label]), None)
                put(key, canon or raw.title(), 0.95 if canon else 0.6)
            elif hits[label]:
                put(key, hits[label][0], 0.70)

        nid = NATIONAL_ID_RX.search(text)
        if nid:
            put("national_id_masked", mask_id(nid.group(0)), 0.8)
        return vals, conf

    # ------------------------------------------------------------------ pipeline
    def process_file(self, path: str | Path) -> tuple[ExtractedEmployeeRecord, dict]:
        p = Path(path)
        text, pages, ocr_used, ocr_conf = self.load_text(p)
        clean, removed = strip_injection(text)
        dtype, dconf = self.classify(clean)
        vals, conf = self.extract_fields(clean, ocr_conf)
        if ocr_used:
            dconf = round(dconf * max(0.4, min(1.0, ocr_conf + 0.15)), 2)

        required = self.rs.required_fields_by_doc_type.get(dtype, ["employee_id"])
        missing = [f for f in required if not vals.get(f)]
        low = sorted(k for k, c in conf.items() if c < self.min_conf)
        if dconf < self.min_conf:
            low.append("document_type")
        rec = ExtractedEmployeeRecord(
            source_file=p.name, document_type=dtype, document_type_confidence=dconf,
            employee_id=vals.get("employee_id"), department=vals.get("department"),
            designation=vals.get("designation"), joining_date=vals.get("joining_date"),
            issue_date=vals.get("issue_date"), expiry_date=vals.get("expiry_date"),
            national_id_masked=vals.get("national_id_masked"), field_confidence=conf,
            missing_fields=missing, low_confidence_fields=low, ocr_used=ocr_used, page_count=pages,
            injection_flags=removed)
        meta = {"file": p.name, "size_bytes": p.stat().st_size, "pages": pages, "ocr_used": ocr_used,
                "ocr_confidence": round(ocr_conf, 2), "document_type": dtype,
                "injection_suspected": bool(removed), "status": "processed"}
        return rec, meta

    # ------------------------------------------------------------------ graph node
    def run(self, state: dict) -> dict:
        records, metas, errors, ids = [], [], [], []
        for f in state.get("uploaded_files") or []:
            try:
                rec, meta = self.process_file(f)
                records.append(rec.model_dump())
                metas.append(meta)
                if rec.employee_id:
                    ids.append(rec.employee_id)
            except Exception as exc:  # per-file isolation: one bad file must not kill the batch
                log.warning("Failed to process %s: %s", f, exc)
                metas.append({"file": Path(f).name, "status": "failed", "error": str(exc)})
                errors.append(f"document_intelligence: {Path(f).name}: {exc}")
        return {"extracted_employee_data": records, "document_metadata": metas,
                "employee_ids": ids, "errors": errors}
