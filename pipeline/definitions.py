from __future__ import annotations
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _p in [str(_HERE), str(_ROOT / 'registry'), str(_ROOT / 'audit')]:
    if _p not in _sys.path:
        _sys.path.insert(0, _p)


import hashlib
import math
import os
import re
from typing import Any

import numpy as np

from metric_registry_seed import REGISTRY

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from openai import OpenAI
except ImportError:
    OpenAI = None

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None


MODEL_NAME = "all-MiniLM-L6-v2"
OPENAI_EMBEDDING_MODEL = "text-embedding-3-small"
FALLBACK_DIMENSIONS = 512
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the",
    "a",
    "an",
    "of",
    "and",
    "or",
    "to",
    "for",
    "in",
    "on",
    "by",
    "with",
    "within",
    "from",
    "that",
    "this",
    "is",
    "are",
    "be",
    "as",
    "at",
    "into",
    "during",
    "across",
}

_MODEL: SentenceTransformer | None = None
_OPENAI_CLIENT: OpenAI | None = None
_ACTIVE_REGISTRY: list[dict[str, Any]] = []
_ACTIVE_BY_ID: dict[str, dict[str, Any]] = {}
_CANONICAL_VECTORS: dict[str, np.ndarray] = {}
_IDF_WEIGHTS: dict[str, float] = {}
_TEXT_VECTOR_CACHE: dict[str, np.ndarray] = {}
_BACKEND: str | None = None
_BACKEND_WARNING: str | None = None
_VECTOR_DIMENSIONS = FALLBACK_DIMENSIONS

if load_dotenv is not None:
    load_dotenv()


def _normalize_text(text: str | None) -> str:
    return " ".join(str(text or "").strip().lower().split())


def _tokenize(text: str | None) -> list[str]:
    normalized = _normalize_text(text)
    tokens = [token for token in _TOKEN_RE.findall(normalized) if token not in _STOPWORDS]
    bigrams = [f"{left}_{right}" for left, right in zip(tokens, tokens[1:])]
    return tokens + bigrams


def _hash_index(token: str) -> int:
    digest = hashlib.md5(token.encode("utf-8")).hexdigest()
    return int(digest, 16) % FALLBACK_DIMENSIONS


def _compute_idf_weights(registry: list[dict[str, Any]]) -> dict[str, float]:
    doc_freq: dict[str, int] = {}
    total_docs = max(1, len(registry))
    for entry in registry:
        text = str(entry.get("canonical_definition") or entry.get("canonical_name") or entry.get("canonical_id") or "")
        seen = set(_tokenize(text))
        for token in seen:
            doc_freq[token] = doc_freq.get(token, 0) + 1
    return {
        token: math.log((1 + total_docs) / (1 + freq)) + 1.0
        for token, freq in doc_freq.items()
    }


def _encode_with_fallback(text: str | None) -> np.ndarray:
    vector = np.zeros(FALLBACK_DIMENSIONS, dtype=float)
    tokens = _tokenize(text)
    if not tokens:
        return vector
    for token in tokens:
        vector[_hash_index(token)] += _IDF_WEIGHTS.get(token, 1.0)
    norm = float(np.linalg.norm(vector))
    if norm > 0:
        vector /= norm
    return vector


def _get_sentence_transformer_model() -> SentenceTransformer | None:
    global _MODEL
    if SentenceTransformer is None:
        return None
    if _MODEL is None:
        _MODEL = SentenceTransformer(MODEL_NAME, local_files_only=True)
    return _MODEL


def _get_openai_client() -> OpenAI | None:
    global _OPENAI_CLIENT
    if OpenAI is None or not os.getenv("OPENAI_API_KEY"):
        return None
    if _OPENAI_CLIENT is None:
        _OPENAI_CLIENT = OpenAI(api_key=os.getenv("OPENAI_API_KEY"), timeout=60, max_retries=1)
    return _OPENAI_CLIENT


def _resolve_backend() -> str:
    global _BACKEND, _BACKEND_WARNING, _VECTOR_DIMENSIONS
    if _BACKEND is not None:
        return _BACKEND

    if os.getenv("FORCE_FALLBACK_EMBEDDINGS", "").strip() == "1":
        _BACKEND = "fallback_hashing"
        _BACKEND_WARNING = "Using numpy hash-vector fallback for definition similarity."
        return _BACKEND

    if SentenceTransformer is not None:
        try:
            model = _get_sentence_transformer_model()
            if model is not None:
                sample = np.array(model.encode(["semantic backend probe"], normalize_embeddings=True)[0], dtype=float)
                _VECTOR_DIMENSIONS = int(sample.shape[0])
                _TEXT_VECTOR_CACHE["semantic backend probe"] = sample
                _BACKEND = "sentence_transformers"
                _BACKEND_WARNING = None
                return _BACKEND
        except Exception as exc:
            _BACKEND_WARNING = f"sentence_transformers unavailable at runtime ({exc!r}); trying OpenAI embeddings."

    client = _get_openai_client()
    if client is not None:
        try:
            response = client.embeddings.create(
                model=OPENAI_EMBEDDING_MODEL,
                input=["semantic backend probe"],
            )
            sample = np.array(response.data[0].embedding, dtype=float)
            norm = float(np.linalg.norm(sample))
            if norm > 0:
                sample /= norm
            _VECTOR_DIMENSIONS = int(sample.shape[0])
            _TEXT_VECTOR_CACHE["semantic backend probe"] = sample
            _BACKEND = "openai_embeddings"
            if _BACKEND_WARNING:
                _BACKEND_WARNING += " Switched to OpenAI embeddings."
            else:
                _BACKEND_WARNING = None
            return _BACKEND
        except Exception as exc:
            warning = f"OpenAI embeddings unavailable ({exc!r}); using numpy hash-vector fallback."
            _BACKEND_WARNING = f"{_BACKEND_WARNING} {warning}".strip() if _BACKEND_WARNING else warning

    _BACKEND = "fallback_hashing"
    if _BACKEND_WARNING is None:
        _BACKEND_WARNING = "Using numpy hash-vector fallback for definition similarity."
    return _BACKEND


def _encode_text(text: str | None) -> np.ndarray:
    normalized = _normalize_text(text)
    if normalized in _TEXT_VECTOR_CACHE:
        return _TEXT_VECTOR_CACHE[normalized]

    backend = _resolve_backend()
    if not normalized:
        vector = np.zeros(_VECTOR_DIMENSIONS, dtype=float)
        _TEXT_VECTOR_CACHE[normalized] = vector
        return vector

    if backend == "sentence_transformers":
        model = _get_sentence_transformer_model()
        vector = np.array(model.encode([normalized], normalize_embeddings=True)[0], dtype=float)
        _TEXT_VECTOR_CACHE[normalized] = vector
        return vector

    if backend == "openai_embeddings":
        client = _get_openai_client()
        response = client.embeddings.create(
            model=OPENAI_EMBEDDING_MODEL,
            input=[normalized],
        )
        vector = np.array(response.data[0].embedding, dtype=float)
        norm = float(np.linalg.norm(vector))
        if norm > 0:
            vector /= norm
        _TEXT_VECTOR_CACHE[normalized] = vector
        return vector

    vector = _encode_with_fallback(normalized)
    _TEXT_VECTOR_CACHE[normalized] = vector
    return vector


def set_registry(registry: list[dict[str, Any]] | None = None) -> None:
    global _ACTIVE_REGISTRY, _ACTIVE_BY_ID, _CANONICAL_VECTORS, _IDF_WEIGHTS
    _ACTIVE_REGISTRY = [dict(entry) for entry in (registry or REGISTRY)]
    _ACTIVE_BY_ID = {
        str(entry.get("canonical_id") or ""): entry
        for entry in _ACTIVE_REGISTRY
        if str(entry.get("canonical_id") or "")
    }
    _IDF_WEIGHTS = _compute_idf_weights(_ACTIVE_REGISTRY)
    _CANONICAL_VECTORS = {}
    for canonical_id, entry in _ACTIVE_BY_ID.items():
        definition = str(
            entry.get("canonical_definition")
            or entry.get("canonical_name")
            or canonical_id.replace("_", " ")
        )
        _CANONICAL_VECTORS[canonical_id] = _encode_text(definition)


def _ensure_registry() -> None:
    if not _CANONICAL_VECTORS:
        set_registry(REGISTRY)


def definition_similarity(fact_definition: str | None, canonical_id: str) -> float:
    if not fact_definition:
        return 0.0
    _ensure_registry()
    canonical_vector = _CANONICAL_VECTORS.get(str(canonical_id or ""))
    if canonical_vector is None:
        return 0.0
    fact_vector = _encode_text(fact_definition)
    if not np.any(fact_vector) or not np.any(canonical_vector):
        return 0.0
    score = float(np.dot(fact_vector, canonical_vector))
    return max(0.0, min(1.0, score))


def top_definition_matches(fact_definition: str | None, k: int = 5) -> list[tuple[str, float]]:
    if not fact_definition:
        return []
    _ensure_registry()
    matches = [
        (canonical_id, definition_similarity(fact_definition, canonical_id))
        for canonical_id in _ACTIVE_BY_ID
    ]
    matches = [item for item in matches if item[1] > 0.0]
    matches.sort(key=lambda item: item[1], reverse=True)
    return matches[:k]


def text_vector(text: str | None) -> np.ndarray:
    return _encode_text(text)


def text_similarity(left: str | None, right: str | None) -> float:
    left_vector = _encode_text(left)
    right_vector = _encode_text(right)
    if not np.any(left_vector) or not np.any(right_vector):
        return 0.0
    score = float(np.dot(left_vector, right_vector))
    return max(0.0, min(1.0, score))


def get_backend_status() -> tuple[str, str | None]:
    return _resolve_backend(), _BACKEND_WARNING


EMBEDDING_BACKEND, EMBEDDING_WARNING = get_backend_status()
