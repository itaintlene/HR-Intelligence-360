"""Agent 2 - HR Policy Agent (RAG).

retrieve (FAISS) -> relevance gate (refuse if unsupported) -> grounded generation (LLM, or extractive
fallback) -> citation validation (tags must reference retrieved chunks; numbers must appear in them)
-> citation formatting.
"""
from __future__ import annotations

import logging
import re

from hr360.agents.base import AgentContext
from hr360.llm import prompts
from hr360.rag.chunker import format_citation
from hr360.rag.embeddings import distinctive_terms
from hr360.rag.store import PolicyVectorStore
from hr360.security.sanitize import detect_injection, wrap_untrusted

log = logging.getLogger("hr360.policy")

REFUSAL = ("I could not find a supported answer to that in the HR policy documents, so I won't guess. "
           "Please contact HR directly or rephrase your question.")
MIN_TERM_RATIO = 0.4  # share of the question's distinctive terms a passage must cover
_TAG = re.compile(r"\[S(\d+)\]")


class HRPolicyAgent:
    name = "policy"

    def __init__(self, ctx: AgentContext, store: PolicyVectorStore | None = None):
        self.ctx = ctx
        self._store = store

    @property
    def store(self) -> PolicyVectorStore:
        if self._store is None:  # lazy: building the index/model is expensive
            s = self.ctx.settings
            self._store = PolicyVectorStore(s.policy_dir, s.index_dir, s.embeddings_backend)
        return self._store

    # ---- tools ----
    def retrieve(self, query: str) -> list[dict]:
        hits = self.store.search(query, self.ctx.settings.policy_top_k)
        return [h for h in hits if h["score"] >= self.store.min_score and h["term_overlap"] >= 1
                and h["term_ratio"] >= MIN_TERM_RATIO]

    @staticmethod
    def validate_citations(answer: str, chunks: list[dict]) -> tuple[bool, str]:
        tags = [int(t) for t in _TAG.findall(answer)]
        if not tags:
            return False, "no citations"
        if any(t < 1 or t > len(chunks) for t in tags):
            return False, "citation to a passage that was not retrieved"
        context = " ".join(c["text"] for c in chunks)
        context_nums = set(re.findall(r"\d+(?:\.\d+)?", context))
        body = _TAG.sub("", answer)
        unsupported = [n for n in re.findall(r"\d+(?:\.\d+)?", body) if n not in context_nums]
        if unsupported:
            return False, f"numbers not found in sources: {unsupported[:3]}"
        return True, "ok"

    @staticmethod
    def format_citations(answer: str, chunks: list[dict]) -> tuple[str, list[dict]]:
        used = sorted({int(t) for t in _TAG.findall(answer)})
        text = _TAG.sub(lambda m: f"[{format_citation(chunks[int(m.group(1)) - 1])}]", answer)
        cites = [{"tag": f"S{i}", "doc_title": chunks[i - 1]["doc_title"], "section": chunks[i - 1]["section"],
                  "doc_file": chunks[i - 1]["doc_file"], "chunk_id": chunks[i - 1]["chunk_id"],
                  "citation": format_citation(chunks[i - 1])} for i in used]
        return text, cites

    @staticmethod
    def extractive_answer(query: str, chunks: list[dict]) -> str:
        q = distinctive_terms(query)
        scored = []
        for ci, c in enumerate(chunks[:3], start=1):
            for sent in re.split(r"(?<=[.!?])\s+", c["text"]):
                ov = len(q & distinctive_terms(sent))
                if ov:
                    scored.append((ov + c["score"] - 0.1 * (ci - 1), ci, sent.strip()))
        if not scored:
            return f"{chunks[0]['text'].split('. ')[0].strip().rstrip('.')}. [S1]"
        scored.sort(key=lambda x: -x[0])
        best = scored[0][0]
        picked = sorted([s for s in scored if s[0] >= 0.75 * best][:2], key=lambda x: x[1])
        return " ".join(f"{s.rstrip('.')}. [S{ci}]" for _, ci, s in picked)

    def generate(self, query: str, chunks: list[dict]) -> tuple[str | None, str]:
        """-> (answer_with_S_tags | None if the LLM says insufficient, method)"""
        context = "\n\n".join(f"[S{i}] ({format_citation(c)}) {c['text']}" for i, c in enumerate(chunks, 1))
        user = f"Context passages:\n{context}\n\nQuestion:\n{wrap_untrusted(query, 'QUESTION')}"
        for _ in range(2):  # one retry if the draft fails citation validation
            draft = self.ctx.llm.invoke_text(prompts.POLICY_ANSWER, user)
            if draft is None:
                break
            if "INSUFFICIENT_CONTEXT" in draft:
                return None, "llm"
            ok, why = self.validate_citations(draft, chunks)
            if ok:
                return draft, "llm"
            log.info("LLM answer rejected: %s", why)
        return self.extractive_answer(query, chunks), "extractive"

    # ---- graph node ----
    def run(self, state: dict) -> dict:
        query = state.get("policy_query") or state.get("user_query", "")
        flags = detect_injection(query)
        chunks = self.retrieve(query)
        base = {"query": query, "injection_flags": flags}
        if not chunks:
            return {"retrieved_policy_chunks": [], "policy_answer": {**base, "answer": REFUSAL, "refused": True,
                                                                      "citations": [], "method": "refusal", "validated": True}}
        answer, method = self.generate(query, chunks)
        if answer is None:
            return {"retrieved_policy_chunks": chunks, "policy_answer": {**base, "answer": REFUSAL, "refused": True,
                                                                          "citations": [], "method": method, "validated": True}}
        ok, why = self.validate_citations(answer, chunks)  # final gate - applies to extractive too
        if not ok:
            return {"retrieved_policy_chunks": chunks, "policy_answer": {**base, "answer": REFUSAL, "refused": True,
                                                                          "citations": [], "method": method, "validated": False,
                                                                          "reason": why}}
        text, cites = self.format_citations(answer, chunks)
        return {"retrieved_policy_chunks": chunks,
                "policy_answer": {**base, "answer": text, "refused": False, "citations": cites,
                                  "method": method, "validated": True}}
