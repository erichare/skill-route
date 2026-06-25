from __future__ import annotations

from skillroute.backends import AstraDataAPIBackend, LocalTokenBackend
from skillroute.catalog import Catalog


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
    assert {ref["status"] for ref in refs} == {"not_configured"}

