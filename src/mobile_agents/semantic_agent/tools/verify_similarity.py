"""Verify image descriptions against vision-generated captions."""

from __future__ import annotations

from typing import Any

from sentence_transformers import SentenceTransformer

DEFAULT_SIMILARITY_THRESHOLD = 0.75
EMBEDDING_MODEL_NAME = "paraphrase-multilingual-MiniLM-L12-v2"
_EMBEDDING_MODEL = SentenceTransformer(EMBEDDING_MODEL_NAME)


def verify_similarity(
    images_inventory: list[dict[str, Any]],
    captions: list[dict[str, Any]],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> dict[str, Any]:
    """Return semantic similarity statuses for an image inventory."""
    captions_by_index = {caption.get("index"): caption for caption in captions}
    issues = [
        _verification_issue(index, image, captions_by_index.get(index, {}), threshold)
        for index, image in enumerate(images_inventory)
    ]
    return {"issues": issues, "summary": _summarize_issues(issues)}


def _verification_issue(
    index: int,
    image: dict[str, Any],
    caption_data: dict[str, Any],
    threshold: float,
) -> dict[str, Any]:
    """Build the verification result for one inventory image."""
    content_description = _text_value(image.get("content_description"))
    caption = _text_value(caption_data.get("caption"))
    issue = {
        "index": index,
        "resource_id": _text_value(image.get("resource_id")),
        "content_description": content_description,
        "caption": caption,
        "similarity_score": None,
        "status": "missing",
    }
    if not content_description:
        return issue

    similarity_score = _cosine_similarity(content_description, caption)
    issue["similarity_score"] = similarity_score
    issue["status"] = "pass" if similarity_score >= threshold else "mismatch"
    return issue


def _cosine_similarity(content_description: str, caption: str) -> float:
    """Calculate cosine similarity from normalized multilingual embeddings."""
    embeddings = _EMBEDDING_MODEL.encode(
        [content_description, caption],
        convert_to_numpy=True,
        normalize_embeddings=True,
    )
    return float(embeddings[0].dot(embeddings[1]))


def _summarize_issues(issues: list[dict[str, Any]]) -> dict[str, int]:
    """Count verification statuses for the report summary."""
    return {
        "total": len(issues),
        "pass": sum(issue["status"] == "pass" for issue in issues),
        "missing": sum(issue["status"] == "missing" for issue in issues),
        "mismatch": sum(issue["status"] == "mismatch" for issue in issues),
    }


def _text_value(value: Any) -> str:
    """Convert optional metadata values to text suitable for embeddings."""
    return value if isinstance(value, str) else ""
