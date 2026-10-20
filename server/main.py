"""Entry point kept for `uvicorn main:app` (run from the server/ directory)."""

from nexus.api import app

__all__ = ["app"]
