"""LLM access via LangChain (OpenAI-compatible API or Ollama).

Every caller must work when no LLM is configured: ``invoke_text`` / ``invoke_structured``
return ``None`` on absence or failure and the agent falls back to deterministic logic.
"""
from __future__ import annotations

import logging
import os
from typing import TypeVar

from pydantic import BaseModel

log = logging.getLogger("hr360.llm")
T = TypeVar("T", bound=BaseModel)


class LLMClient:
    def __init__(self, backend: str = "auto"):
        self.backend = backend
        self._model = None
        self._tried = False

    @property
    def model(self):
        if not self._tried:
            self._tried = True
            self._model = self._build()
        return self._model

    @property
    def available(self) -> bool:
        return self.model is not None

    def _build(self):
        backend = self.backend
        if backend == "auto":
            backend = "openai" if os.getenv("OPENAI_API_KEY") else ("ollama" if os.getenv("OLLAMA_MODEL") else "none")
        try:
            if backend == "openai":
                from langchain_openai import ChatOpenAI
                return ChatOpenAI(model=os.getenv("HR360_LLM_MODEL", "gpt-4o-mini"), temperature=0,
                                  base_url=os.getenv("OPENAI_BASE_URL") or None, timeout=30, max_retries=1)
            if backend == "ollama":
                from langchain_ollama import ChatOllama
                return ChatOllama(model=os.getenv("OLLAMA_MODEL", os.getenv("HR360_LLM_MODEL", "llama3.1")), temperature=0)
        except Exception as exc:  # missing package / bad config
            log.warning("LLM backend %s unavailable: %s", backend, exc)
        return None

    def invoke_text(self, system: str, user: str) -> str | None:
        if not self.available:
            return None
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            resp = self.model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
            return (resp.content or "").strip() if isinstance(resp.content, str) else str(resp.content)
        except Exception as exc:
            log.warning("LLM text call failed: %s", exc)
            return None

    def invoke_structured(self, schema: type[T], system: str, user: str) -> T | None:
        if not self.available:
            return None
        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            out = self.model.with_structured_output(schema).invoke(
                [SystemMessage(content=system), HumanMessage(content=user)])
            return schema.model_validate(out) if not isinstance(out, schema) else out
        except Exception as exc:
            log.warning("LLM structured call failed: %s", exc)
            return None
