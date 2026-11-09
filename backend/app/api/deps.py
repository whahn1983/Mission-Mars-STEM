from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import APIKeyHeader

from ..runtime import Runtime
from ..services.pin import verify_pin

_pin_header = APIKeyHeader(name="X-Operator-Pin", auto_error=False)


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def require_operator(
    rt: Runtime = Depends(get_runtime),
    header_pin: str | None = Depends(_pin_header),
    pin: str | None = Query(default=None, description="Operator PIN (for download links)"),
) -> None:
    supplied = header_pin or pin or ""
    stored = rt.store.get("operator_pin_hash")
    if stored:
        # A PIN changed on the dashboard replaces OPERATOR_PIN from .env.
        if not verify_pin(supplied, stored):
            raise HTTPException(status_code=401, detail="Operator PIN required")
        return
    expected = rt.env.operator_pin
    if not expected:
        return
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Operator PIN required")


def pin_source(rt: Runtime) -> str:
    if rt.store.get("operator_pin_hash"):
        return "dashboard"
    return "env" if rt.env.operator_pin else "disabled"
