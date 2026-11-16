"""Load policy documents (.md / .txt / .pdf / .docx) and split into section-aware chunks."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

MAX_CHARS = 900
_HEADING_MD = re.compile(r"^##\s+(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>.+?)\s*$")
_HEADING_PLAIN = re.compile(r"^(?P<num>\d+(?:\.\d+)*)\.?\s+(?P<title>[A-Z][^.]{2,80})$")


@dataclass
class Chunk:
    chunk_id: str
    doc_title: str
    doc_file: str
    section: str          # e.g. "4 Earned Leave"
    section_number: str   # e.g. "4"
    text: str

    def to_dict(self) -> dict:
        return asdict(self)


def _read(path: Path) -> str:
    s = path.suffix.lower()
    if s in (".md", ".txt"):
        return path.read_text(encoding="utf-8")
    if s == ".docx":
        import docx
        return "\n".join(p.text for p in docx.Document(str(path)).paragraphs)
    if s == ".pdf":
        try:
            import pymupdf as fitz
        except ImportError:  # slim install
            from pypdf import PdfReader
            return "\n".join((p.extract_text() or "") for p in PdfReader(str(path)).pages)
        with fitz.open(str(path)) as pdf:
            return "\n".join(page.get_text() for page in pdf)
    raise ValueError(f"Unsupported policy file: {path.name}")


def _split_long(text: str) -> list[str]:
    if len(text) <= MAX_CHARS:
        return [text]
    parts, cur = [], ""
    for sent in re.split(r"(?<=[.!?])\s+", text):
        if cur and len(cur) + len(sent) > MAX_CHARS:
            parts.append(cur.strip())
            cur = ""
        cur += sent + " "
    if cur.strip():
        parts.append(cur.strip())
    return parts


def chunk_document(path: Path) -> list[Chunk]:
    raw = _read(path)
    lines = raw.splitlines()
    title = path.stem.replace("_", " ").title()
    for ln in lines:
        if ln.startswith("# "):
            title = ln[2:].strip()
            break
    sections: list[tuple[str, str, list[str]]] = [("0", "Introduction", [])]
    for ln in lines:
        m = _HEADING_MD.match(ln) or _HEADING_PLAIN.match(ln.strip())
        if m:
            sections.append((m.group("num"), m.group("title"), []))
        elif not ln.startswith("# "):
            sections[-1][2].append(ln)
    chunks: list[Chunk] = []
    for num, sec_title, body_lines in sections:
        body = " ".join(l.strip() for l in body_lines if l.strip())
        if not body:
            continue
        for i, piece in enumerate(_split_long(body)):
            cid = f"{path.stem}:{num}" + (f".{i}" if i else "")
            chunks.append(Chunk(cid, title, path.name, f"{num} {sec_title}", num, piece))
    return chunks


def load_corpus(policy_dir: Path) -> list[Chunk]:
    chunks: list[Chunk] = []
    for p in sorted(Path(policy_dir).iterdir()):
        if p.suffix.lower() in (".md", ".txt", ".pdf", ".docx"):
            chunks.extend(chunk_document(p))
    return chunks


def format_citation(c: dict) -> str:
    return f"{c['doc_title']} §{c['section']}"
