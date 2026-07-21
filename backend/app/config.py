"""Application configuration, loaded from environment variables / a .env file.

Key settings:
    OPENAI_API_KEY         — required, used by litellm and the embedding model
    LLM_MODEL              — litellm model string, e.g. gpt-4o-mini
    SYSTEM_PROMPT_FILE     — path to base system-prompt markdown file
    CORS_ORIGINS           — comma-separated list of allowed CORS origins
    PORT                   — uvicorn port
    WEAVIATE_URL           — Weaviate URL, self-hosted or Cloud (optional, enables RAG)
    WEAVIATE_API_KEY       — Weaviate Cloud admin API key (leave blank for self-hosted)
    MCP_SERVER_URL         — bucketlistt MCP server URL (optional, enables live catalog tools)
"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the chatbot backend.

    Every field is overridable via an environment variable of the same
    name (case-insensitive) or via a `.env` file in the working directory.
    """

    openai_api_key: str
    llm_model: str = "gpt-4o-mini"
    system_prompt_file: str = "data/knowledge_base.md"
    cors_origins: str = "http://localhost:5173"
    port: int = 8000
    # Weaviate vector DB for RAG — optional; if blank, falls back to flat file KB
    weaviate_url: str = ""
    weaviate_api_key: str = ""
    # bucketlistt MCP server — read-only catalog tools only, see app/mcp_client.py
    mcp_server_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS as a list, split on commas, for use with CORSMiddleware."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

# litellm reads provider credentials straight from os.environ. If the key only
# came from a .env file (not an actual exported env var) it wouldn't be visible
# to litellm otherwise, so mirror it in here.
os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
