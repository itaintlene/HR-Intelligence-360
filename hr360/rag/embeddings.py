"""Embedding backends. ``sbert`` (sentence-transformers) is preferred; ``hash`` is a deterministic,
dependency-free fallback (hashed unigram+bigram TF vectors) used when the model cannot be loaded
(offline machines, CI)."""
from __future__ import annotations

import hashlib
import logging
import re

import numpy as np

log = logging.getLogger("hr360.rag")
SBERT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
STOPWORDS = set("a an the and or of to in on for is are be am was were do does did can i my me we our you your it its "
                "this that these those with as at by from how what when where who which will would should may must "
                "per any all not no if then than so such".split())


GENERIC_TERMS = {"company", "employee", "hr", "policy", "many", "much", "get", "need", "please", "tell", "know",
                 "allowed", "applicable", "document"}


def _stem(t: str) -> str:
    if len(t) <= 4:
        return t
    if t.endswith("ies"):
        return t[:-3] + "y"
    if t.endswith("ied"):
        return t[:-3] + "y"
    for suf in ("sses", "ches", "shes", "xes"):
        if t.endswith(suf):
            return t[:-2]
    for suf in ("ing", "ly", "ed", "s"):
        if t.endswith(suf) and not t.endswith("ss"):
            return t[: -len(suf)]
    return t


def tokenize(text: str) -> list[str]:
    return [_stem(t) for t in re.findall(r"[a-z0-9]+", text.lower()) if t not in STOPWORDS]


def distinctive_terms(text: str) -> set[str]:
    return {t for t in tokenize(text) if t not in GENERIC_TERMS and not t.isdigit()}


class HashEmbedder:
    name = "hash"

    def __init__(self, dim: int = 1024):
        self.dim = dim

    def _idx(self, tok: str) -> int:
        return int(hashlib.md5(tok.encode()).hexdigest()[:8], 16) % self.dim

    def encode(self, texts: list[str]) -> np.ndarray:
        mat = np.zeros((len(texts), self.dim), dtype="float32")
        for i, t in enumerate(texts):
            toks = tokenize(t)
            for tok in toks:
                mat[i, self._idx(tok)] += 1.0
            for a, b in zip(toks, toks[1:]):
                mat[i, self._idx(a + "_" + b)] += 0.7
            mat[i] = np.log1p(mat[i])
        norms = np.linalg.norm(mat, axis=1, keepdims=True)
        return mat / np.maximum(norms, 1e-9)


class SbertEmbedder:
    name = "sbert"

    def __init__(self):
        from sentence_transformers import SentenceTransformer
        self.model = SentenceTransformer(SBERT_MODEL)

    def encode(self, texts: list[str]) -> np.ndarray:
        return np.asarray(self.model.encode(texts, normalize_embeddings=True, show_progress_bar=False), dtype="float32")


def get_embedder(backend: str = "auto"):
    if backend in ("auto", "sbert"):
        try:
            return SbertEmbedder()
        except Exception as exc:
            if backend == "sbert":
                raise
            log.warning("sentence-transformers unavailable (%s); using hash embedder", exc)
    return HashEmbedder()
