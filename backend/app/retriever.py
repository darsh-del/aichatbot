"""Weaviate-based semantic retriever for the chatbot RAG pipeline.

Loaded lazily so the backend still starts even if Weaviate is not configured
(useful for local dev without a Weaviate instance).
"""

import os
from typing import Optional

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
        return None

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
        return _collection
    except Exception as exc:
        _weaviate_available = False
        # Don't crash – log and degrade gracefully
        print(f"[retriever] Weaviate init failed: {exc}. RAG disabled, using flat KB only.")
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

    try:
        # Embed the query using OpenAI
        oai = openai.OpenAI(api_key=os.environ.get("OPENAI_API_KEY", ""))
        embedding_response = oai.embeddings.create(
            input=query,
            model="text-embedding-3-small",
        )
        query_vector = embedding_response.data[0].embedding

        # Query Weaviate
        result = collection.query.near_vector(
            near_vector=query_vector,
            limit=top_k,
            return_properties=["content", "url", "title", "page_type"],
        )

        if not result.objects:
            return ""

        # Format chunks into a clean context block
        chunks = []
        for obj in result.objects:
            props = obj.properties
            source = f"[{props.get('page_type', 'page')}] {props.get('title', '')} ({props.get('url', '')})"
            chunks.append(f"Source: {source}\n{props.get('content', '')}")

        return "\n\n---\n\n".join(chunks)

    except Exception as exc:
        print(f"[retriever] Query failed: {exc}")
        return ""
