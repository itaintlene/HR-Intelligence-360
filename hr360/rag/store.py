"""FAISS-backed policy vector store with on-disk caching keyed by corpus + embedder."""
from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

import faiss
import numpy as np

from hr360.rag.chunker import Chunk, load_corpus
from hr360.rag.embeddings import distinctive_terms, get_embedder

log = logging.getLogger("hr360.rag")

# minimum cosine similarity for a chunk to count as relevant, per embedder
MIN_SCORE = {"sbert": 0.30, "hash": 0.12}


class PolicyVectorStore:
    def __init__(self, policy_dir: Path, index_dir: Path, backend: str = "auto"):
        self.policy_dir, self.index_dir = Path(policy_dir), Path(index_dir)
        self.embedder = get_embedder(backend)
        self.chunks: list[Chunk] = []
        self.index: faiss.Index | None = None
        self._build_or_load()

    @property
    def min_score(self) -> float:
        return MIN_SCORE[self.embedder.name]

    def _fingerprint(self) -> str:
        h = hashlib.sha256(self.embedder.name.encode())
        for p in sorted(self.policy_dir.iterdir()):
            if p.is_file():
                h.update(p.name.encode())
                h.update(p.read_bytes())
        return h.hexdigest()[:16]

    def _build_or_load(self) -> None:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        fp = self._fingerprint()
        idx_path, meta_path = self.index_dir / f"policy_{fp}.faiss", self.index_dir / f"policy_{fp}.json"
        if idx_path.exists() and meta_path.exists():
            self.index = faiss.read_index(str(idx_path))
            self.chunks = [Chunk(**c) for c in json.loads(meta_path.read_text(encoding="utf-8"))]
            return
        self.chunks = load_corpus(self.policy_dir)
        if not self.chunks:
            raise RuntimeError(f"No policy documents found in {self.policy_dir}")
        vecs = self.embedder.encode([f"{c.doc_title} {c.section}. {c.text}" for c in self.chunks])
        self.index = faiss.IndexFlatIP(vecs.shape[1])  # cosine via normalised inner product
        self.index.add(vecs)
        faiss.write_index(self.index, str(idx_path))
        meta_path.write_text(json.dumps([c.to_dict() for c in self.chunks]), encoding="utf-8")
        log.info("Built policy index: %d chunks (%s)", len(self.chunks), self.embedder.name)

    def search(self, query: str, k: int = 4) -> list[dict]:
        qv = self.embedder.encode([query])
        scores, ids = self.index.search(qv, min(k, len(self.chunks)))
        q_terms = distinctive_terms(query)
        out = []
        for s, i in zip(scores[0], ids[0]):
            if i < 0:
                continue
            c = self.chunks[int(i)]
            overlap = len(q_terms & distinctive_terms(c.text + " " + c.section + " " + c.doc_title))
            out.append({**c.to_dict(), "score": round(float(s), 4), "term_overlap": overlap,
                        "term_ratio": round(overlap / len(q_terms), 2) if q_terms else 0.0})
        return out
