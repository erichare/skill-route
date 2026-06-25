from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from skillroute.models import SkillRecord
from skillroute.text import keyword_score, unique_tokens


class RetrievalBackend(Protocol):
    name: str

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        ...

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        ...


class AstraDataAPIError(RuntimeError):
    def __init__(self, message: str, status_code: int | None = None, response: Any = None) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.response = response


AstraTransport = Callable[[str, dict[str, str], dict[str, Any], float], dict[str, Any]]


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
    keyspace: str = "default_keyspace"
    timeout_seconds: float = 30.0
    use_vectorize: bool = True
    use_lexical: bool = False
    embedding_api_key: str | None = field(default=None, repr=False)
    transport: AstraTransport | None = field(default=None, repr=False)
    name: str = "astra-data-api"

    @classmethod
    def from_env(cls) -> "AstraDataAPIBackend":
        return cls(
            endpoint=os.environ.get("ASTRA_DB_API_ENDPOINT"),
            token=os.environ.get("ASTRA_DB_APPLICATION_TOKEN"),
            keyspace=os.environ.get("SKILLROUTE_ASTRA_KEYSPACE", "default_keyspace"),
            collection=os.environ.get("SKILLROUTE_ASTRA_COLLECTION", "skillroute_skills"),
            timeout_seconds=float(os.environ.get("SKILLROUTE_ASTRA_TIMEOUT_SECONDS", "30")),
            use_vectorize=env_bool("SKILLROUTE_ASTRA_USE_VECTORIZE", default=True),
            use_lexical=env_bool("SKILLROUTE_ASTRA_USE_LEXICAL", default=False),
            embedding_api_key=os.environ.get("SKILLROUTE_ASTRA_EMBEDDING_API_KEY"),
        )

    @property
    def is_configured(self) -> bool:
        return bool(self.endpoint and self.token)

    def build_documents(self, skills: list[SkillRecord], *, include_id: bool = True) -> list[dict[str, Any]]:
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
            document: dict[str, Any] = {
                "content": text,
                "metadata": {
                    "skill_id": skill.id,
                    "name": skill.name,
                    "skill_path": skill.skill_path,
                    "content_hash": skill.content_hash,
                    "tags": skill.tags,
                    "facets": skill.facets,
                },
            }
            if self.use_vectorize:
                document["$vectorize"] = text
            if self.use_lexical:
                document["$lexical"] = text
            if include_id:
                document["_id"] = skill.id
            documents.append(document)
        return documents

    def create_collection(self, options: dict[str, Any] | None = None) -> dict[str, Any]:
        self._require_configured()
        return self._post(
            self.keyspace_url(),
            {
                "createCollection": {
                    "name": self.collection,
                    **({"options": options} if options is not None else {}),
                }
            },
        )

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
        documents = self.build_documents(skills, include_id=False)
        if not documents:
            return []
        refs = []
        for skill, document in zip(skills, documents, strict=True):
            self._post(
                self.collection_url(),
                {
                    "findOneAndReplace": {
                        "filter": {"_id": skill.id},
                        "replacement": document,
                        "projection": {"_id": True},
                        "options": {"upsert": True, "returnDocument": "after"},
                    }
                },
            )
            refs.append(
                {
                    "skill_id": skill.id,
                    "backend": self.name,
                    "ref": skill.id,
                    "status": "indexed",
                }
            )
        return refs

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        if not self.is_configured:
            return []
        if not self.use_vectorize:
            raise AstraDataAPIError(
                "Astra search requires vectorize because SkillRoute sends sort.$vectorize queries. "
                "Set SKILLROUTE_ASTRA_USE_VECTORIZE=true and use a vectorize-enabled collection."
            )
        response = self._post(
            self.collection_url(),
            {
                "find": {
                    "sort": {"$vectorize": query},
                    "options": {"limit": limit, "includeSimilarity": True},
                    "projection": {"_id": 1, "metadata": 1, "$similarity": 1},
                }
            },
        )
        documents = response.get("data", {}).get("documents", [])
        rows: list[dict[str, Any]] = []
        for document in documents:
            metadata = document.get("metadata", {}) if isinstance(document, dict) else {}
            skill_id = document.get("_id") or metadata.get("skill_id")
            if not skill_id:
                continue
            rows.append(
                {
                    "skill_id": str(skill_id),
                    "backend": self.name,
                    "score": float(document.get("$similarity", 0.0)),
                }
            )
        return rows[:limit]

    def keyspace_url(self) -> str:
        endpoint = (self.endpoint or "").rstrip("/")
        return f"{endpoint}/api/json/v1/{quote_path(self.keyspace)}"

    def collection_url(self) -> str:
        return f"{self.keyspace_url()}/{quote_path(self.collection)}"

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise AstraDataAPIError(
                "Astra Data API backend is not configured. Set ASTRA_DB_API_ENDPOINT "
                "and ASTRA_DB_APPLICATION_TOKEN."
            )

    def _post(self, url: str, payload: dict[str, Any]) -> dict[str, Any]:
        self._require_configured()
        headers = {
            "Token": self.token or "",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.embedding_api_key:
            headers["x-embedding-api-key"] = self.embedding_api_key
        transport = self.transport or urlopen_transport
        response = transport(url, headers, payload, self.timeout_seconds)
        if "errors" in response:
            raise AstraDataAPIError(
                f"Astra Data API returned errors: {truncate(json.dumps(response['errors']))}",
                response=response,
            )
        return response


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


def urlopen_transport(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout_seconds: float,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise AstraDataAPIError(
            f"Astra Data API request failed with HTTP {exc.code}: {truncate(body)}",
            status_code=exc.code,
            response=parse_json_object(body),
        ) from exc
    except urllib.error.URLError as exc:
        raise AstraDataAPIError(f"Astra Data API request failed: {exc.reason}") from exc

    parsed = parse_json_object(body)
    if not isinstance(parsed, dict):
        raise AstraDataAPIError("Astra Data API returned a non-object JSON response.")
    if "errors" in parsed:
        raise AstraDataAPIError(f"Astra Data API returned errors: {truncate(json.dumps(parsed['errors']))}", response=parsed)
    return parsed


def parse_json_object(text: str) -> Any:
    try:
        return json.loads(text) if text else {}
    except json.JSONDecodeError:
        return {"raw": truncate(text)}


def truncate(text: str, limit: int = 500) -> str:
    return text if len(text) <= limit else f"{text[:limit]}..."


def quote_path(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
