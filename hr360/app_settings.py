"""Admin-editable runtime settings (key/value table). Only whitelisted keys with validated values."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy import delete, insert, select

from hr360.data.schema import OPS_METADATA, app_settings

EMAIL_MODES = ("env", "off", "redirect", "live")  # env = follow environment variables
_EMAIL_RX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

DEFAULTS = {"email_mode": "env", "email_redirect_to": ""}


def validate(key: str, value: str) -> str:
    if key == "email_mode":
        if value not in EMAIL_MODES:
            raise ValueError(f"email_mode must be one of {EMAIL_MODES}")
    elif key == "email_redirect_to":
        if value and not _EMAIL_RX.match(value):
            raise ValueError("email_redirect_to must be a valid email address (or empty)")
    else:
        raise ValueError(f"Unknown setting '{key}'")
    return value


def get_all(engine) -> dict[str, str]:
    OPS_METADATA.create_all(engine)
    with engine.connect() as c:
        stored = {r.key: r.value for r in c.execute(select(app_settings))}
    return {**DEFAULTS, **{k: v for k, v in stored.items() if k in DEFAULTS}}


def set_value(engine, key: str, value: str, updated_by: str) -> None:
    value = validate(key, value.strip())
    with engine.begin() as c:
        c.execute(delete(app_settings).where(app_settings.c.key == key))
        c.execute(insert(app_settings).values(key=key, value=value, updated_by=updated_by,
                                              updated_at=datetime.now(timezone.utc).isoformat(timespec="seconds")))
