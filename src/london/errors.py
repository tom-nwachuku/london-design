"""Shared London-facing exception types."""

from __future__ import annotations


class LondonError(RuntimeError):
    """Base class for authored product errors that should not print tracebacks."""


class LondonUsageError(LondonError):
    """User-correctable library error raised before a CLI boundary formats it."""
