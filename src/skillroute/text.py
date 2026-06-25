from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable


TOKEN_RE = re.compile(r"[a-zA-Z][a-zA-Z0-9_+-]{1,}")

STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "any",
    "are",
    "build",
    "can",
    "for",
    "from",
    "have",
    "into",
    "that",
    "the",
    "this",
    "tool",
    "use",
    "user",
    "when",
    "with",
    "you",
    "your",
}


def normalize_token(token: str) -> str:
    return token.strip().lower().replace("_", "-")


def tokenize(text: str) -> list[str]:
    return [
        normalize_token(match.group(0))
        for match in TOKEN_RE.finditer(text)
        if normalize_token(match.group(0)) not in STOP_WORDS
    ]


def unique_tokens(text: str) -> set[str]:
    return set(tokenize(text))


def top_terms(chunks: Iterable[str], limit: int = 12) -> list[str]:
    counter: Counter[str] = Counter()
    for chunk in chunks:
        counter.update(tokenize(chunk))
    return [term for term, _ in counter.most_common(limit)]


def keyword_score(query_tokens: set[str], fields: list[tuple[str, float]]) -> float:
    if not query_tokens:
        return 0.0
    score = 0.0
    for text, weight in fields:
        field_tokens = unique_tokens(text)
        if not field_tokens:
            continue
        overlap = query_tokens & field_tokens
        score += weight * (len(overlap) / len(query_tokens))
    return score


def best_snippets(query_tokens: set[str], snippets: Iterable[str], limit: int = 3) -> list[str]:
    ranked: list[tuple[int, str]] = []
    for snippet in snippets:
        overlap = len(query_tokens & unique_tokens(snippet))
        if overlap:
            ranked.append((overlap, snippet))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [snippet for _, snippet in ranked[:limit]]

