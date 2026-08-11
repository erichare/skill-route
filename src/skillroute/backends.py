from __future__ import annotations

import functools
import json
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from skillroute.models import SkillRecord
from skillroute.text import keyword_score, unique_tokens

BACKEND_CHOICES = ("local", "local-token", "fts5", "sqlite-fts5", "astra", "astra-data-api")


class RetrievalBackend(Protocol):
    name: str

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        ...

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        ...

    def status(self, skills: list[SkillRecord] | None = None) -> dict[str, Any]:
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

    def status(self, skills: list[SkillRecord] | None = None) -> dict[str, Any]:
        return {
            "configured": True,
            "status": "ready",
            "search_available": True,
            "write_available": True,
            "mode": "local",
        }


def _probe_fts5() -> bool:
    try:
        connection = sqlite3.connect(":memory:")
    except sqlite3.Error:
        return False
    try:
        connection.execute("CREATE VIRTUAL TABLE skillroute_fts_probe USING fts5(content)")
    except sqlite3.Error:
        return False
    finally:
        connection.close()
    return True


@functools.lru_cache(maxsize=1)
def fts5_available() -> bool:
    """True when this SQLite build ships the FTS5 extension (standard builds do)."""
    return _probe_fts5()


def build_fts_match_query(query: str) -> str | None:
    """Turn an arbitrary query string into a safe FTS5 MATCH expression.

    Every whitespace-separated term is wrapped in double quotes so user input
    is never interpreted as FTS5 query syntax (AND/OR/NEAR, prefixes, columns).
    """
    terms = [term for term in query.split() if term]
    if not terms:
        return None
    return " OR ".join(f'"{term.replace(chr(34), chr(34) * 2)}"' for term in terms)


# Column order must match the CREATE VIRTUAL TABLE statement and the INSERT in
# SqliteFTS5Backend._index(). The leading 0.0 weight keeps the UNINDEXED
# skill_id column out of the ranking.
FTS_BM25_WEIGHTS = (0.0, 2.5, 2.0, 1.5, 1.2, 1.0)


@dataclass(slots=True)
class SqliteFTS5Backend:
    """Local retrieval backed by SQLite FTS5 BM25 ranking.

    Builds an in-memory FTS5 index from the skills handed to ``search`` so the
    backend stays stateless and adds no storage beyond the catalog. BM25 adds
    term-frequency, document-length, and rare-term weighting on top of the
    plain token-overlap scoring of LocalTokenBackend, and scales to much
    larger skill libraries. Field weights mirror the lexical scoring weights
    so name and description matches dominate.
    """

    name: str = "fts5"
    # raw BM25 relevance maps to score = raw / (raw + saturation) in [0, 1).
    bm25_saturation: float = 6.0
    _index_cache: dict[tuple[Any, ...], sqlite3.Connection] = field(default_factory=dict, repr=False)

    def upsert_skills(self, skills: list[SkillRecord]) -> list[dict[str, Any]]:
        return [
            {
                "skill_id": skill.id,
                "backend": self.name,
                "ref": skill.content_hash,
                "status": "indexed",
            }
            for skill in skills
        ]

    def search(self, query: str, skills: list[SkillRecord], limit: int = 10) -> list[dict[str, Any]]:
        if not skills:
            return []
        match = build_fts_match_query(query)
        if match is None:
            return []
        connection = self._index(skills)
        weights = ", ".join(str(weight) for weight in FTS_BM25_WEIGHTS)
        try:
            rows = connection.execute(
                f"""
                SELECT skill_id, bm25(fts, {weights}) AS rank
                FROM fts
                WHERE fts MATCH ?
                ORDER BY rank
                LIMIT ?
                """,
                (match, max(1, limit)),
            ).fetchall()
        except sqlite3.Error:
            return []
        return [
            {"skill_id": skill_id, "backend": self.name, "score": self.normalize_bm25(rank)}
            for skill_id, rank in rows
        ]

    def status(self, skills: list[SkillRecord] | None = None) -> dict[str, Any]:
        available = fts5_available()
        return {
            "configured": available,
            "status": "ready" if available else "fts5_unavailable",
            "search_available": available,
            "write_available": available,
            "mode": "local",
        }

    def normalize_bm25(self, rank: float) -> float:
        """Map SQLite's negative-is-better BM25 rank into a [0, 1) score."""
        raw = max(-float(rank), 0.0)
        return raw / (raw + self.bm25_saturation)

    def _index(self, skills: list[SkillRecord]) -> sqlite3.Connection:
        fingerprint = tuple((skill.id, skill.content_hash) for skill in skills)
        cached = self._index_cache.get(fingerprint)
        if cached is not None:
            return cached
        connection = sqlite3.connect(":memory:")
        connection.execute(
            """
            CREATE VIRTUAL TABLE fts USING fts5(
                skill_id UNINDEXED,
                name,
                description,
                tags,
                facets,
                body
            )
            """
        )
        connection.executemany(
            "INSERT INTO fts (skill_id, name, description, tags, facets, body) VALUES (?, ?, ?, ?, ?, ?)",
            [
                (
                    skill.id,
                    skill.name,
                    skill.description,
                    " ".join(skill.tags),
                    " ".join(value for values in skill.facets.values() for value in values),
                    "\n".join(excerpt.text for excerpt in skill.excerpts),
                )
                for skill in skills
            ],
        )
        # Bounded cache: a long-lived process (UI server) may re-index over
        # time, so evict and close the oldest index when the cache fills up.
        while len(self._index_cache) >= 8:
            evicted_key = next(iter(self._index_cache))
            self._index_cache.pop(evicted_key).close()
        self._index_cache[fingerprint] = connection
        return connection


@dataclass(slots=True)
class AstraDataAPIBackend:
    collection: str = "skillroute_skills"
    endpoint: str | None = None
    token: str | None = field(default=None, repr=False)
    keyspace: str = "default_keyspace"
    timeout_seconds: float = 30.0
    use_vectorize: bool = True
    use_lexical: bool = False
    embedding_api_key: str | None = field(default=None, repr=False)
    transport: AstraTransport | None = field(default=None, repr=False)
    name: str = "astra-data-api"

    @classmethod
    def from_env(cls) -> AstraDataAPIBackend:
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

    def status(self, skills: list[SkillRecord] | None = None) -> dict[str, Any]:
        if not self.is_configured:
            status = "not_configured"
        elif not self.use_vectorize:
            status = "vectorize_disabled"
        else:
            status = "ready"
        return {
            "configured": self.is_configured,
            "status": status,
            "search_available": self.is_configured and self.use_vectorize,
            "write_available": self.is_configured,
            "endpoint_configured": bool(self.endpoint),
            "token_configured": bool(self.token),
            "embedding_api_key_configured": bool(self.embedding_api_key),
            "keyspace": self.keyspace,
            "collection": self.collection,
            "use_vectorize": self.use_vectorize,
            "use_lexical": self.use_lexical,
            "timeout_seconds": self.timeout_seconds,
        }

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

    def status(self, skills: list[SkillRecord] | None = None) -> dict[str, Any]:
        return {
            "configured": self.vectorstore is not None,
            "status": "ready" if self.vectorstore is not None else "not_configured",
            "search_available": hasattr(self.vectorstore, "similarity_search_with_score"),
            "write_available": hasattr(self.vectorstore, "add_documents"),
            "mode": "langchain",
        }


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


def backend_from_name(name: str | None) -> RetrievalBackend:
    """Resolve a retrieval backend by name.

    Single source of truth shared by the CLI, the bridge, and the UI server so
    they agree on the SKILLROUTE_BACKEND fallback and the set of valid names.
    """
    configured = (name or os.environ.get("SKILLROUTE_BACKEND") or "local").strip().lower()
    if configured in {"local", "local-token"}:
        return LocalTokenBackend()
    if configured in {"fts5", "sqlite-fts5"}:
        if not fts5_available():
            raise ValueError(
                "The fts5 backend needs SQLite's FTS5 extension, which this sqlite3 build "
                "does not provide. Use the local-token backend instead."
            )
        return SqliteFTS5Backend()
    if configured in {"astra", "astra-data-api"}:
        return AstraDataAPIBackend.from_env()
    valid = ", ".join(BACKEND_CHOICES)
    raise ValueError(f"Unsupported SkillRoute backend {configured!r}; expected one of: {valid}")
