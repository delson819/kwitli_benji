"""Compatibility entrypoint for uvicorn backend.main:app."""

from backend.app.main import app

__all__ = ["app"]
