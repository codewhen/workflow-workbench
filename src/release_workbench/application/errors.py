"""Application control failures; cancellation remains asyncio.CancelledError."""

import asyncio

from release_workbench.domain.values import ContractError


class SkipRequested(asyncio.CancelledError):
    """Cancel owned work while allowing its enclosing card to continue."""


class ExecutionFailure(ContractError):
    """A failed card with its original attempt retained in evidence."""


class EvidenceRequired(ExecutionFailure):
    """An unattended run reached a manual intervention."""
