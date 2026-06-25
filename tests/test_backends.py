from __future__ import annotations

import pytest

from skillroute.backends import AstraDataAPIBackend, AstraDataAPIError, LocalTokenBackend
from skillroute.catalog import Catalog


class RecordingTransport:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def __call__(self, url, headers, payload, timeout_seconds):
        self.calls.append(
            {
                "url": url,
                "headers": headers,
                "payload": payload,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.response


def test_local_token_backend_contract(indexed_catalog: Catalog) -> None:
    skills = indexed_catalog.list_skills()
    backend = LocalTokenBackend()

    refs = backend.upsert_skills(skills)
    hits = backend.search("pytest golden eval", skills)

    assert refs[0]["backend"] == "local-token"
    assert hits[0]["skill_id"] == indexed_catalog.get_skill("python-testing").id


def test_astra_backend_builds_documents_without_credentials(indexed_catalog: Catalog) -> None:
    skills = indexed_catalog.list_skills()
    backend = AstraDataAPIBackend(collection="skills", endpoint=None, token=None)

    documents = backend.build_documents(skills)
    refs = backend.upsert_skills(skills)

    assert documents[0]["_id"]
    assert "metadata" in documents[0]
    assert "$vectorize" in documents[0]
    assert {ref["status"] for ref in refs} == {"not_configured"}


def test_astra_backend_reads_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ASTRA_DB_API_ENDPOINT", "https://db.apps.astra.datastax.com/")
    monkeypatch.setenv("ASTRA_DB_APPLICATION_TOKEN", "secret-token")
    monkeypatch.setenv("SKILLROUTE_ASTRA_KEYSPACE", "skills")
    monkeypatch.setenv("SKILLROUTE_ASTRA_COLLECTION", "catalog")
    monkeypatch.setenv("SKILLROUTE_ASTRA_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("SKILLROUTE_ASTRA_USE_LEXICAL", "true")
    monkeypatch.setenv("SKILLROUTE_ASTRA_EMBEDDING_API_KEY", "embedding-secret")

    backend = AstraDataAPIBackend.from_env()

    assert backend.endpoint == "https://db.apps.astra.datastax.com/"
    assert backend.token == "secret-token"
    assert backend.keyspace == "skills"
    assert backend.collection == "catalog"
    assert backend.timeout_seconds == 12
    assert backend.use_lexical is True
    assert backend.embedding_api_key == "embedding-secret"


def test_astra_create_collection_posts_to_keyspace_endpoint() -> None:
    transport = RecordingTransport({"status": {"ok": 1}})
    backend = AstraDataAPIBackend(
        endpoint="https://db.apps.astra.datastax.com",
        token="secret-token",
        embedding_api_key="embedding-secret",
        keyspace="default_keyspace",
        collection="skillroute_skills",
        transport=transport,
    )

    backend.create_collection({"vector": {"dimension": 1536}})

    call = transport.calls[0]
    assert call["url"] == "https://db.apps.astra.datastax.com/api/json/v1/default_keyspace"
    assert call["headers"]["Token"] == "secret-token"
    assert call["headers"]["x-embedding-api-key"] == "embedding-secret"
    assert call["payload"] == {
        "createCollection": {
            "name": "skillroute_skills",
            "options": {"vector": {"dimension": 1536}},
        }
    }


def test_astra_upsert_posts_find_one_and_replace_with_upsert(indexed_catalog: Catalog) -> None:
    skills = indexed_catalog.list_skills()
    transport = RecordingTransport({"data": {"document": {"_id": skills[0].id}}})
    backend = AstraDataAPIBackend(
        endpoint="https://db.apps.astra.datastax.com",
        token="secret-token",
        keyspace="skills",
        collection="catalog",
        transport=transport,
    )

    refs = backend.upsert_skills(skills)

    call = transport.calls[0]
    assert len(transport.calls) == len(skills)
    assert call["url"] == "https://db.apps.astra.datastax.com/api/json/v1/skills/catalog"
    replacement = call["payload"]["findOneAndReplace"]["replacement"]
    assert call["payload"] == {
        "findOneAndReplace": {
            "filter": {"_id": skills[0].id},
            "replacement": replacement,
            "projection": {"_id": True},
            "options": {"upsert": True, "returnDocument": "after"},
        }
    }
    assert "_id" not in replacement
    assert "$vectorize" in replacement
    assert replacement["metadata"]["skill_id"] == skills[0].id
    assert refs[0] == {
        "skill_id": skills[0].id,
        "backend": "astra-data-api",
        "ref": skills[0].id,
        "status": "indexed",
    }


def test_astra_search_posts_vectorize_find(indexed_catalog: Catalog) -> None:
    skill = indexed_catalog.get_skill("mcp-server-patterns")
    assert skill is not None
    transport = RecordingTransport(
        {
            "data": {
                "documents": [
                    {"_id": skill.id, "metadata": {"skill_id": skill.id}, "$similarity": 0.91}
                ]
            }
        }
    )
    backend = AstraDataAPIBackend(
        endpoint="https://db.apps.astra.datastax.com",
        token="secret-token",
        keyspace="skills",
        collection="catalog",
        transport=transport,
    )

    rows = backend.search("mcp server", indexed_catalog.list_skills(), limit=3)

    call = transport.calls[0]
    assert call["payload"] == {
        "find": {
            "sort": {"$vectorize": "mcp server"},
            "options": {"limit": 3, "includeSimilarity": True},
            "projection": {"_id": 1, "metadata": 1, "$similarity": 1},
        }
    }
    assert rows == [{"skill_id": skill.id, "backend": "astra-data-api", "score": 0.91}]


def test_astra_search_requires_vectorize_when_configured(indexed_catalog: Catalog) -> None:
    backend = AstraDataAPIBackend(
        endpoint="https://db.apps.astra.datastax.com",
        token="secret-token",
        use_vectorize=False,
        transport=RecordingTransport({"data": {"documents": []}}),
    )

    with pytest.raises(AstraDataAPIError, match="requires vectorize"):
        backend.search("mcp server", indexed_catalog.list_skills())


def test_astra_backend_raises_sanitized_error_on_data_api_errors() -> None:
    backend = AstraDataAPIBackend(
        endpoint="https://db.apps.astra.datastax.com",
        token="secret-token",
        transport=RecordingTransport({"errors": [{"message": "bad request"}]}),
    )

    with pytest.raises(AstraDataAPIError) as exc_info:
        backend.create_collection()

    assert "bad request" in str(exc_info.value)
    assert "secret-token" not in str(exc_info.value)
