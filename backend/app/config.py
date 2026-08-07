"""Application configuration, loaded from environment variables / a .env file.

Key settings:
    ANTHROPIC_API_KEY      — required, used by litellm (Claude) and web search
    OPENAI_API_KEY         — required for RAG embeddings (text-embedding-3-small)
    LLM_MODEL              — litellm model string, default anthropic/claude-sonnet-5
    WEB_SEARCH_MODEL       — Anthropic model for web search, default claude-haiku-4-5
    SYSTEM_PROMPT_FILE     — path to base system-prompt markdown file
    CORS_ORIGINS           — comma-separated list of allowed CORS origins
    PORT                   — uvicorn port
    WEAVIATE_URL           — Weaviate URL, self-hosted or Cloud (optional, enables RAG)
    WEAVIATE_API_KEY       — Weaviate Cloud admin API key (leave blank for self-hosted)
    MCP_SERVER_URL         — bucketlistt MCP server URL (optional, enables live catalog tools)
    REDIS_URL              — Redis URL (optional, caches read-only MCP catalog results)
"""
import os

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """All runtime configuration for the chatbot backend.

    Every field is overridable via an environment variable of the same
    name (case-insensitive) or via a `.env` file in the working directory.
    """

    anthropic_api_key: str
    openai_api_key: str = ""
    llm_model: str = "anthropic/claude-sonnet-5"
    web_search_model: str = "claude-haiku-4-5"
    system_prompt_file: str = "data/knowledge_base.md"
    cors_origins: str = "http://localhost:5173"
    port: int = 8000
    # Weaviate vector DB for RAG — optional; if blank, falls back to flat file KB
    weaviate_url: str = ""
    weaviate_api_key: str = ""
    # bucketlistt MCP server — read-only catalog tools only, see app/mcp_client.py
    mcp_server_url: str = ""
    # Redis cache for read-only MCP catalog results — optional, see app/cache.py
    redis_url: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origins_list(self) -> list[str]:
        """CORS_ORIGINS as a list, split on commas, for use with CORSMiddleware."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]


settings = Settings()

# litellm and the Anthropic SDK read credentials from os.environ. If a key
# only came from a .env file (not an actual exported env var) it wouldn't be
# visible otherwise, so mirror them here.
os.environ.setdefault("ANTHROPIC_API_KEY", settings.anthropic_api_key)
if settings.openai_api_key:
    os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)
