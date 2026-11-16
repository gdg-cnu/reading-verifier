"""데이터베이스 행을 공개 API 응답 형식으로 변환한다."""

import json
import sqlite3
from typing import Any


def paper_response(row: sqlite3.Row) -> dict[str, Any]:
    """논문 공개 필드만 반환하며 로컬 파일 경로는 응답에서 제외한다."""
    return {
        "paper_id": row["paper_id"],
        "version": row["version"],
        "title": row["title"],
        "authors": json.loads(row["authors_json"]),
        "abstract": row["abstract"],
        "categories": json.loads(row["categories_json"]),
        "published_at": row["published_at"],
        "source_url": row["source_url"],
        "status": row["status"],
        "error": row["error"],
    }


def sentence_response(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "idx": row["idx"],
        "text": row["text"],
        "section": row["section"],
        "role": row["role"],
        "parser_version": row["parser_version"],
    }


def claim_response(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "claim_id": row["claim_id"],
        "paper_id": row["paper_id"],
        "claim_sentence": row["claim_sentence"],
        "evidence": json.loads(row["evidence_json"]),
        "conditions": json.loads(row["conditions_json"]),
        "hedge": json.loads(row["hedge_json"]),
        "strength": row["strength"],
        "confidence": row["confidence"],
        "checks": json.loads(row["checks_json"]),
    }
