"""Weaviate-based semantic retriever for the chatbot RAG pipeline.

Loaded lazily so the backend still starts even if Weaviate is not configured
(useful for local dev without a Weaviate instance).
"""

import logging
import os
import time
from typing import Optional

logger = logging.getLogger(__name__)

_client = None
_collection = None
_weaviate_available: Optional[bool] = None


def _get_collection():
    """Lazy-initialize the Weaviate client and return the KB collection."""
    global _client, _collection, _weaviate_available

    if _weaviate_available is False:
        return None

    if _collection is not None:
        return _collection

    weaviate_url = os.environ.get("WEAVIATE_URL", "")
    weaviate_api_key = os.environ.get("WEAVIATE_API_KEY", "")
    openai_api_key = os.environ.get("OPENAI_API_KEY", "")

    # weaviate_api_key is only required for Weaviate Cloud; a self-hosted
    # instance (docker-compose `weaviate` service) runs with anonymous access.
    if not weaviate_url:
        _weaviate_available = False
        logger.info("WEAVIATE_URL not set — RAG disabled, using flat KB only")
        return None

    t0 = time.perf_counter()
    try:
        import weaviate
        from urllib.parse import urlparse
        from weaviate.classes.init import Auth

        if weaviate_api_key:
            _client = weaviate.connect_to_weaviate_cloud(
                cluster_url=weaviate_url,
                auth_credentials=Auth.api_key(weaviate_api_key),
                headers={"X-OpenAI-Api-Key": openai_api_key},
            )
        else:
            # Self-hosted Weaviate (e.g. the `weaviate` service in docker-compose.yml)
            parsed = urlparse(weaviate_url)
            _client = weaviate.connect_to_local(
                host=parsed.hostname or "localhost",
                port=parsed.port or 8080,
                headers={"X-OpenAI-Api-Key": openai_api_key},
            )
        _collection = _client.collections.get("BucketlisttKB")
        _weaviate_available = True
        logger.info("Weaviate connected in %.3fs — %s", time.perf_counter() - t0, weaviate_url)
        return _collection
    except Exception as exc:
        _weaviate_available = False
        logger.error("Weaviate init failed after %.3fs: %s — RAG disabled, using flat KB only", time.perf_counter() - t0, exc)
        return None


def retrieve(query: str, top_k: int = 6) -> str:
    """Semantic-search the Weaviate KB and return formatted context chunks.

    Returns an empty string if Weaviate is unavailable, so the caller can fall
    back to the flat knowledge-base file gracefully.
    """
    import openai
    import os

    collection = _get_collection()
    if collection is None:
        return ""

    t_total = time.perf_counter()
    try:
        # Embed the query using OpenAI
        t_embed = time.perf_counter()
        oai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        embedding_response = oai.embeddings.create(
            input=query,
            model="text-embedding-3-small",
        )
        query_vector = embedding_response.data[0].embedding
        logger.info("Embedding took %.3fs for query: %s", time.perf_counter() - t_embed, query[:100])

        # Query Weaviate
        t_search = time.perf_counter()
        result = collection.query.near_vector(
            near_vector=query_vector,
            limit=top_k,
            return_properties=["content", "url", "title", "page_type"],
        )
        logger.info("Weaviate search took %.3fs — %d results", time.perf_counter() - t_search, len(result.objects) if result.objects else 0)

        if not result.objects:
            logger.info("RAG retrieval: no results (total %.3fs)", time.perf_counter() - t_total)
            return ""

        # Format chunks into a clean context block
        chunks = []
        for obj in result.objects:
            props = obj.properties
            source = f"[{props.get('page_type', 'page')}] {props.get('title', '')} ({props.get('url', '')})"
            chunks.append(f"Source: {source}\n{props.get('content', '')}")

        logger.info("RAG retrieval complete: %d chunks in %.3fs", len(chunks), time.perf_counter() - t_total)
        return "\n\n---\n\n".join(chunks)

    except Exception as exc:
        logger.exception("RAG retrieval failed after %.3fs", time.perf_counter() - t_total)
        # retrieve() runs off the event loop (called via asyncio.to_thread from
        # llm.py), so there's no running loop here for asyncio.create_task —
        # use the sync notifier entrypoint directly instead.
        from app.notifier import send_critical_alert_sync
        send_critical_alert_sync("weaviate_down", str(exc), f"Failed to retrieve context for query: {query}")
        return ""
