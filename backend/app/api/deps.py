from __future__ import annotations

import hmac

from fastapi import Depends, HTTPException, Query, Request
from fastapi.security import APIKeyHeader

from ..runtime import Runtime

_pin_header = APIKeyHeader(name="X-Operator-Pin", auto_error=False)


def get_runtime(request: Request) -> Runtime:
    return request.app.state.runtime


def require_operator(
    rt: Runtime = Depends(get_runtime),
    header_pin: str | None = Depends(_pin_header),
    pin: str | None = Query(default=None, description="Operator PIN (for download links)"),
) -> None:
    expected = rt.env.operator_pin
    if not expected:
        return
    supplied = header_pin or pin or ""
    if not hmac.compare_digest(supplied.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Operator PIN required")
