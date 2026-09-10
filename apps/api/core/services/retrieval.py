"""Fail-closed hybrid retrieval over approved, published legal chunks."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
import math

from django.conf import settings
from django.contrib.postgres.search import SearchQuery, SearchRank, SearchVector
from django.db import connection, transaction
from django.db.models import Q, QuerySet
from pgvector.django import CosineDistance

from core.models import DocumentChunk, Embedding, SourceDocumentVersion
from core.services.ai_policy import validated_context
from core.services.ai_transport import AIUnavailable, localai_json
from rest_framework.exceptions import Throttled


def _published_chunks(context: dict) -> QuerySet[DocumentChunk]:
    context = validated_context(context)
    queryset = DocumentChunk.objects.select_related(
        "document_version__document", "document_version__document__source_registry"
    ).filter(document_version__state=SourceDocumentVersion.PipelineState.PUBLISHED)
    if jurisdiction := str(context.get("jurisdiction", "")).strip():
        queryset = queryset.filter(
            document_version__document__jurisdiction=jurisdiction
        )
    if document_type := str(context.get("document_type", "")).strip():
        queryset = queryset.filter(
            document_version__document__document_type=document_type
        )
    if source_type := str(context.get("source_type", "")).strip():
        queryset = queryset.filter(
            document_version__document__source_registry__source_type=source_type
        )
    if reference_date := _parse_reference_date(context.get("reference_date")):
        queryset = queryset.filter(
            Q(document_version__valid_from__isnull=True)
            | Q(document_version__valid_from__lte=reference_date),
            Q(document_version__valid_to__isnull=True)
            | Q(document_version__valid_to__gte=reference_date),
        )
    return queryset


def _parse_reference_date(value: object) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def _query_embedding(question: str) -> list[float] | None:
    try:
        response = localai_json(
            "/v1/embeddings",
            {
                "model": settings.LOCALAI_EMBEDDING_MODEL,
                "input": f"query: {question[:4000]}",
            },
        )
        vector = response["data"][0]["embedding"]
        if not isinstance(vector, list) or len(vector) != 384:
            return None
        vector = [float(value) for value in vector]
        return vector if all(math.isfinite(value) for value in vector) else None
    except (AIUnavailable, Throttled, KeyError, IndexError, TypeError, ValueError):
        return None


def hybrid_retrieve(
    *, question: str, context: dict, limit: int = 6
) -> list[DocumentChunk]:
    """Reciprocal-rank fusion of Portuguese full text and 384-d cosine search."""

    base = _published_chunks(context)
    if connection.vendor == "postgresql":
        vector = (
            SearchVector("text", weight="A", config="portuguese")
            + SearchVector("article", weight="B", config="portuguese")
            + SearchVector("section", weight="B", config="portuguese")
            + SearchVector("source_locator", weight="C", config="portuguese")
        )
        query = SearchQuery(
            question[:1000], config="portuguese", search_type="websearch"
        )
        lexical = list(
            base.annotate(rank=SearchRank(vector, query))
            .filter(rank__gt=0)
            .order_by("-rank")[:18]
        )
    else:
        lexical = list(
            base.filter(
                Q(text__icontains=question[:160])
                | Q(article__icontains=question[:160])
                | Q(section__icontains=question[:160])
                | Q(source_locator__icontains=question[:160])
            )[:18]
        )

    semantic: list[DocumentChunk] = []
    query_vector = (
        _query_embedding(question) if connection.vendor == "postgresql" else None
    )
    if query_vector is not None:
        semantic = list(
            base.filter(embedding__isnull=False)
            .annotate(distance=CosineDistance("embedding__vector", query_vector))
            .order_by("distance")[:18]
        )

    scores: dict[object, float] = defaultdict(float)
    objects: dict[object, DocumentChunk] = {}
    for ranked in (lexical, semantic):
        for position, chunk in enumerate(ranked, start=1):
            objects[chunk.pk] = chunk
            scores[chunk.pk] += 1.0 / (60 + position)
    ordered = sorted(scores, key=scores.get, reverse=True)
    return [objects[pk] for pk in ordered[: max(1, min(limit, 12))]]


def index_published_version(version: SourceDocumentVersion) -> int:
    """Create immutable-model embeddings only for an already published version."""

    if version.state != SourceDocumentVersion.PipelineState.PUBLISHED:
        raise ValueError("only published document versions may be indexed")
    chunks = list(version.chunks.order_by("ordinal"))
    if not chunks:
        return 0
    vectors = []
    for start in range(0, len(chunks), 4):
        batch = chunks[start : start + 4]
        response = localai_json(
            "/v1/embeddings",
            {
                "model": settings.LOCALAI_EMBEDDING_MODEL,
                "input": [f"passage: {chunk.text[:8000]}" for chunk in batch],
            },
        )
        items = response["data"]
        if len(items) != len(batch):
            raise ValueError("embedding result count mismatch")
        for item in items:
            vector = [float(value) for value in item["embedding"]]
            if len(vector) != 384 or not all(math.isfinite(value) for value in vector):
                raise ValueError("invalid embedding")
            vectors.append(vector)
    with transaction.atomic():
        for chunk, vector in zip(chunks, vectors, strict=True):
            existing, created = Embedding.objects.get_or_create(
                chunk=chunk,
                defaults={
                    "model": settings.LOCALAI_EMBEDDING_MODEL,
                    "dimensions": 384,
                    "vector": vector,
                },
            )
            if not created and existing.model != settings.LOCALAI_EMBEDDING_MODEL:
                raise ValueError("embedding model change requires versioned reindex")
    return len(chunks)
