import sys
import threading
import types

from app import retriever


def test_get_collection_concurrent_init_creates_client_once(monkeypatch):
    """Two racing cold-start threads must not both call connect_to_local."""
    monkeypatch.setattr(retriever, "_client", None)
    monkeypatch.setattr(retriever, "_collection", None)
    monkeypatch.setattr(retriever, "_weaviate_available", None)
    monkeypatch.setenv("WEAVIATE_URL", "http://localhost:8080")
    monkeypatch.delenv("WEAVIATE_API_KEY", raising=False)

    connect_calls = []
    start = threading.Event()

    def fake_connect_to_local(**kwargs):
        connect_calls.append(kwargs)
        start.wait(timeout=1)  # widen the race window
        client = type("FakeClient", (), {})()
        client.collections = type("Collections", (), {"get": lambda self, name: "the-collection"})()
        return client

    fake_weaviate = types.ModuleType("weaviate")
    fake_weaviate.connect_to_local = fake_connect_to_local
    fake_classes = types.ModuleType("weaviate.classes")
    fake_classes_init = types.ModuleType("weaviate.classes.init")
    fake_classes_init.Auth = type("Auth", (), {"api_key": staticmethod(lambda k: k)})
    monkeypatch.setitem(sys.modules, "weaviate", fake_weaviate)
    monkeypatch.setitem(sys.modules, "weaviate.classes", fake_classes)
    monkeypatch.setitem(sys.modules, "weaviate.classes.init", fake_classes_init)

    results = []

    def worker():
        results.append(retriever._get_collection())

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    start.set()
    for t in threads:
        t.join()

    assert len(connect_calls) == 1, "only one thread should initialize the Weaviate client"
    assert all(r == "the-collection" for r in results)
