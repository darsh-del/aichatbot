#!/usr/bin/env python3
"""
Weaviate Upsert Script for Bucketlistt Knowledge Base
Reads scraped JSON, chunks content, embeds with OpenAI, and upserts to Weaviate
(Weaviate Cloud if WEAVIATE_API_KEY is set, otherwise a self-hosted instance).

Usage:
    cd backend
    pip install weaviate-client openai
    python scripts/upsert_to_weaviate.py

Idempotent: safe to re-run; deterministic UUIDs prevent duplicates.
"""

import json
import os
import sys
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Load backend/.env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)

# ── Verify env vars before importing heavy deps ──────────────────────────────
WEAVIATE_URL = os.environ.get("WEAVIATE_URL", "")
WEAVIATE_API_KEY = os.environ.get("WEAVIATE_API_KEY", "")
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

if not WEAVIATE_URL:
    sys.exit("❌  WEAVIATE_URL is not set. Add it to backend/.env")
if not OPENAI_API_KEY:
    sys.exit("❌  OPENAI_API_KEY is not set. Add it to backend/.env")

import weaviate
import weaviate.classes as wvc
from weaviate.classes.init import Auth
from weaviate.classes.config import Configure, Property, DataType
from openai import OpenAI

# ── Constants ─────────────────────────────────────────────────────────────────
COLLECTION_NAME = "BucketlisttKB"
EMBEDDING_MODEL = "text-embedding-3-small"
CHUNK_SIZE = 500          # characters (≈ 100-150 tokens)
CHUNK_OVERLAP = 100       # characters overlap between consecutive chunks
BATCH_SIZE = 50           # objects per Weaviate batch

DATA_FILE = Path(__file__).parent.parent / "data" / "bucketlistt_scraped.json"

openai_client = OpenAI(api_key=OPENAI_API_KEY)


# ── Chunking ──────────────────────────────────────────────────────────────────
def chunk_text(text: str, chunk_size: int = CHUNK_SIZE, overlap: int = CHUNK_OVERLAP) -> list[str]:
    """Split text into overlapping character-level chunks."""
    if not text or len(text) <= chunk_size:
        return [text] if text.strip() else []
    chunks = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = end - overlap
    return chunks


def deterministic_uuid(namespace: str, text: str) -> str:
    """Generate a deterministic UUID5 from a namespace + content hash."""
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"{namespace}::{text[:200]}"))


# ── Embedding ─────────────────────────────────────────────────────────────────
def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts using OpenAI text-embedding-3-small."""
    response = openai_client.embeddings.create(
        input=texts,
        model=EMBEDDING_MODEL,
    )
    return [item.embedding for item in response.data]


# ── Main ──────────────────────────────────────────────────────────────────────
def ensure_collection(client: weaviate.WeaviateClient) -> None:
    """Create the BucketlisttKB collection if it doesn't exist."""
    if client.collections.exists(COLLECTION_NAME):
        print(f"✓ Collection '{COLLECTION_NAME}' already exists.")
        return

    client.collections.create(
        name=COLLECTION_NAME,
        description="Bucketlistt.com adventure activities knowledge base for RAG chatbot",
        # We supply our own vectors (BYOV) so we don't need a vectorizer module
        vectorizer_config=Configure.Vectorizer.none(),
        properties=[
            Property(name="url", data_type=DataType.TEXT),
            Property(name="page_type", data_type=DataType.TEXT),
            Property(name="title", data_type=DataType.TEXT),
            Property(name="chunk_index", data_type=DataType.INT),
            Property(name="content", data_type=DataType.TEXT),
        ],
    )
    print(f"✓ Created collection '{COLLECTION_NAME}'.")


def build_objects_from_json(data_file: Path) -> list[dict]:
    """Load scraped JSON, chunk each page's content, return list of objects."""
    with open(data_file, encoding="utf-8") as f:
        data = json.load(f)

    objects = []
    pages = data.get("pages", [])
    print(f"  Loaded {len(pages)} pages from {data_file.name}")

    for page in pages:
        url = page.get("url", "")
        page_type = page.get("page_type", "")
        title = page.get("title", "")
        content = page.get("content", "")

        if not content.strip():
            continue

        chunks = chunk_text(content)
        for idx, chunk in enumerate(chunks):
            objects.append({
                "url": url,
                "page_type": page_type,
                "title": title,
                "chunk_index": idx,
                "content": chunk,
                "_uuid": deterministic_uuid(url, chunk),
            })

    print(f"  Total chunks to upsert: {len(objects)}")
    return objects


def upsert_all(client: weaviate.WeaviateClient, objects: list[dict]) -> None:
    """Upsert all objects into Weaviate in batches."""
    collection = client.collections.get(COLLECTION_NAME)
    total = len(objects)
    upserted = 0
    errors = 0

    for batch_start in range(0, total, BATCH_SIZE):
        batch = objects[batch_start : batch_start + BATCH_SIZE]
        texts = [obj["content"] for obj in batch]

        # Embed this batch
        try:
            vectors = embed_texts(texts)
        except Exception as e:
            print(f"  ✗ Embedding error on batch {batch_start}-{batch_start+len(batch)}: {e}")
            errors += len(batch)
            continue

        # Upsert into Weaviate
        weaviate_objects = []
        for obj, vector in zip(batch, vectors):
            weaviate_objects.append(
                wvc.data.DataObject(
                    uuid=obj["_uuid"],
                    properties={
                        "url": obj["url"],
                        "page_type": obj["page_type"],
                        "title": obj["title"],
                        "chunk_index": obj["chunk_index"],
                        "content": obj["content"],
                    },
                    vector=vector,
                )
            )

        response = collection.data.insert_many(weaviate_objects)
        batch_errors = len(response.errors) if hasattr(response, "errors") else 0
        batch_success = len(batch) - batch_errors
        upserted += batch_success
        errors += batch_errors

        end_idx = min(batch_start + BATCH_SIZE, total)
        print(f"  [{end_idx:03d}/{total}] ✓ {batch_success} upserted, {batch_errors} errors")

    print(f"\n{'='*50}")
    print(f"✅ Done: {upserted} chunks upserted, {errors} errors")


def main():
    if not DATA_FILE.exists():
        sys.exit(
            f"❌  Data file not found: {DATA_FILE}\n"
            "    Run 'python scripts/scrape_bucketlistt.py' first."
        )

    print(f"\n{'='*50}")
    print("Bucketlistt → Weaviate Upsert")
    print(f"{'='*50}")
    print(f"Weaviate URL:    {WEAVIATE_URL}")
    print(f"Collection:      {COLLECTION_NAME}")
    print(f"Embedding model: {EMBEDDING_MODEL}")
    print(f"Chunk size:      {CHUNK_SIZE} chars (overlap: {CHUNK_OVERLAP})")
    print(f"{'='*50}\n")

    # Connect to Weaviate Cloud, or a self-hosted instance if no API key is set
    if WEAVIATE_API_KEY:
        client = weaviate.connect_to_weaviate_cloud(
            cluster_url=WEAVIATE_URL,
            auth_credentials=Auth.api_key(WEAVIATE_API_KEY),
            headers={"X-OpenAI-Api-Key": OPENAI_API_KEY},
        )
    else:
        from urllib.parse import urlparse

        parsed = urlparse(WEAVIATE_URL)
        client = weaviate.connect_to_local(
            host=parsed.hostname or "localhost",
            port=parsed.port or 8080,
            headers={"X-OpenAI-Api-Key": OPENAI_API_KEY},
        )

    try:
        assert client.is_ready(), "Weaviate is not ready!"
        print(f"✓ Connected to Weaviate at {WEAVIATE_URL}")

        ensure_collection(client)

        print("\nLoading and chunking scraped data...")
        objects = build_objects_from_json(DATA_FILE)

        print("\nEmbedding and upserting to Weaviate...")
        upsert_all(client, objects)

    finally:
        client.close()


if __name__ == "__main__":
    main()
