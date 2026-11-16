"""Prompt-injection defences for untrusted text (uploaded documents, user input).

Strategy (defence in depth):
1. Uploaded document text is NEVER placed into an LLM prompt by this system - extraction
   is regex/spaCy based. Detection here is a second layer and a signal for reviewers.
2. Suspicious lines are flagged and stripped before any downstream use.
3. LLM prompts wrap untrusted input in delimiters and instruct the model to treat it as data.
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"ignore (all |any |the )?(previous|prior|above) (instructions|prompts?|rules)",
    r"disregard (all |any |the )?(previous|prior|above)",
    r"forget (everything|all|your) (above|previous|instructions)",
    r"you are now\b",
    r"system prompt",
    r"act as (an? )?(admin|administrator|hr manager|system)",
    r"(reveal|print|show|leak) (your|the) (instructions|prompt|secrets?|system)",
    r"mark (this|the) (employee|record) as compliant",
    r"approve (this|the) (request|leave|payroll)",
    r"<\s*/?\s*(system|assistant|instructions?)\s*>",
    r"\bBEGIN (SYSTEM|INSTRUCTIONS)\b",
]
_COMPILED = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def detect_injection(text: str) -> list[str]:
    """Return the matched snippets (empty if clean)."""
    hits: list[str] = []
    for rx in _COMPILED:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0))
    return hits


def strip_injection(text: str) -> tuple[str, list[str]]:
    """Remove whole lines containing injection phrases. Returns (clean_text, removed_lines)."""
    clean, removed = [], []
    for line in (text or "").splitlines():
        if any(rx.search(line) for rx in _COMPILED):
            removed.append(line.strip()[:200])
        else:
            clean.append(line)
    return "\n".join(clean), removed


def wrap_untrusted(text: str, label: str = "USER_INPUT") -> str:
    """Delimit untrusted text so the model can be told to treat it as data only."""
    safe = (text or "").replace("<<", "< <").replace(">>", "> >")
    return f"<<{label}>>\n{safe}\n<</{label}>>"
