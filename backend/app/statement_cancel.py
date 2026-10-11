from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CancelResult:
    cancelled: bool
    supported: bool
    reason: str


def cancel_statement(connection: Any) -> CancelResult:
    """Best-effort cancellation for SQLAlchemy/driver connections.

    The operation is intentionally conservative: only driver-provided cancel
    methods are called. Unsupported drivers fall back to cooperative cancel.
    """
    raw = getattr(connection, "driver_connection", None)
    raw = raw or getattr(connection, "connection", None) or connection
    for method_name in ("cancel", "cancel_request"):
        method = getattr(raw, method_name, None)
        if callable(method):
            try:
                method()
                return CancelResult(True, True, f"driver method {method_name} invoked")
            except Exception as exc:  # pragma: no cover - driver-specific
                return CancelResult(False, True, f"driver cancel failed: {type(exc).__name__}")
    return CancelResult(False, False, "driver does not expose statement cancellation")
