"""Shared pytest fixtures.

Sets required env vars *before* app.config is imported anywhere, since
Settings() is instantiated once at module import time. Tests are expected to
run from the backend/ directory so the relative SYSTEM_PROMPT_FILE path
resolves.
"""
import os

os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("LLM_MODEL", "gpt-4o-mini")
os.environ.setdefault("SYSTEM_PROMPT_FILE", "data/knowledge_base.md")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:5173")
