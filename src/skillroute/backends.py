from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Protocol

from skillroute.models import SkillRecord
from skillroute.text import keyword_score, unique_tokens


class RetrievalBackend(Protocol):
    name: str

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        ...

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        ...


@dataclass(slots=True)
class LocalTokenBackend:
    name: str = "local-token"

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        return [{"skill_id": skill.id, "backend": self.name, "ref": skill.content_hash} for skill in skills]

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        query_tokens = unique_tokens(query)
        rows: list[dict[str, Any]] = []
        for skill in skills:
            fields = [
                (skill.name, 2.5),
                (skill.description, 2.0),
                (" ".join(skill.tags), 1.5),
                (" ".join(value for values in skill.facets.values() for value in values), 1.2),
                (" ".join(excerpt.text for excerpt in skill.excerpts), 0.9),
            ]
            score = keyword_score(query_tokens, fields)
            if score > 0:
                rows.append({"skill_id": skill.id, "backend": self.name, "score": score})
        rows.sort(key=lambda row: row["score"], reverse=True)
        return rows[:limit]


@dataclass(slots=True)
class AstraDataAPIBackend:
    collection: str = "skillroute_skills"
    endpoint: str | None = None
    token: str | None = None
    name: str = "astra-data-api"

    @classmethod
    def from_env(cls) -> "AstraDataAPIBackend":
        return cls(
            endpoint=os.environ.get("ASTRA_DB_API_ENDPOINT"),
            token=os.environ.get("ASTRA_DB_APPLICATION_TOKEN"),
            collection=os.environ.get("SKILLROUTE_ASTRA_COLLECTION", "skillroute_skills"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.token)

    def build_documents(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        documents = []
        for skill in skills:
            text = "\n".join(
                [
                    skill.name,
                    skill.description,
                    " ".join(skill.tags),
                    *[excerpt.text for excerpt in skill.excerpts],
                ]
            )
            documents.append(
                {
                    "_id": skill.id,
                    "content": text,
                    "metadata": {
                        "name": skill.name,
                        "skill_path": skill.skill_path,
                        "content_hash": skill.content_hash,
                        "tags": skill.tags,
                        "facets": skill.facets,
                    },
                }
            )
        return documents

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        if not self.is_configured:
            return [
                {
                    "skill_id": skill.id,
                    "backend": self.name,
                    "ref": self.collection,
                    "status": "not_configured",
                }
                for skill in skills
            ]
        raise NotImplementedError(
            "Astra Data API network writes are intentionally adapter-only in V1; "
            "wire this method to the Data API client when credentials are provided."
        )

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        if not self.is_configured:
            return []
        raise NotImplementedError(
            "Astra Data API search is a provider adapter contract in V1 and is not invoked by default."
        )


@dataclass(slots=True)
class LangChainBackendAdapter:
    vectorstore: Any
    name: str = "langchain"

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        documents = [
            {
                "page_content": "\n".join([skill.name, skill.description, *[e.text for e in skill.excerpts]]),
                "metadata": {"skill_id": skill.id, "name": skill.name, "skill_path": skill.skill_path},
            }
            for skill in skills
        ]
        add_documents = getattr(self.vectorstore, "add_documents", None)
        if add_documents is None:
            raise TypeError("LangChain vectorstore must expose add_documents")
        refs = add_documents(documents)
        return [
            {"skill_id": skill.id, "backend": self.name, "ref": str(ref)}
            for skill, ref in zip(skills, refs, strict=False)
        ]

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        search = getattr(self.vectorstore, "similarity_search_with_score", None)
        if search is None:
            raise TypeError("LangChain vectorstore must expose similarity_search_with_score")
        rows = []
        for document, score in search(query, k=limit):
            metadata = getattr(document, "metadata", {}) or {}
            rows.append({"skill_id": metadata.get("skill_id"), "backend": self.name, "score": float(score)})
        return [row for row in rows if row["skill_id"]]

