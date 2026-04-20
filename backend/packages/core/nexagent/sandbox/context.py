"""Runtime sandbox context shared by middleware and tools."""

from __future__ import annotations

from contextvars import ContextVar

from nexagent.sandbox.sandbox import Sandbox

_current_sandbox: ContextVar[Sandbox | None] = ContextVar("nexagent_current_sandbox", default=None)


def get_current_sandbox() -> Sandbox | None:
    return _current_sandbox.get()


def set_current_sandbox(sandbox: Sandbox | None):
    return _current_sandbox.set(sandbox)


def reset_current_sandbox(token) -> None:
    _current_sandbox.reset(token)
