"""Shared dependencies handed to every agent (explicit injection, no global state)."""
from __future__ import annotations

from dataclasses import dataclass, field

from hr360.config import Settings
from hr360.data.db import HRDatabase
from hr360.llm.provider import LLMClient
from hr360.rules.engine import RuleSet, RulesEngine, load_ruleset
from hr360.security.audit_log import AuditLog


@dataclass
class AgentContext:
    settings: Settings
    db: HRDatabase
    llm: LLMClient
    ruleset: RuleSet
    engine: RulesEngine
    audit_log: AuditLog
    extras: dict = field(default_factory=dict)

    @classmethod
    def build(cls, settings: Settings | None = None, llm: LLMClient | None = None) -> "AgentContext":
        settings = settings or Settings()
        settings.ensure_dirs()
        ruleset = load_ruleset(settings.rules_path)
        return cls(settings=settings, db=HRDatabase(settings.db_path),
                   llm=llm or LLMClient(settings.llm_backend), ruleset=ruleset,
                   engine=RulesEngine(ruleset), audit_log=AuditLog(settings.ops_db_path))
