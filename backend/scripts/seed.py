"""저장소에 포함된 목데이터 JSON을 로컬 SQLite 데이터베이스에 적재한다.

저장소 루트 폴더에서 다음 명령으로 실행한다.
    python -m backend.scripts.seed

기본 키를 기준으로 기존 레코드를 갱신하고, 목데이터에 포함된 논문에서 사라진
문장과 claim은 DB에서 제거한다. 목데이터에 없는 다른 논문 데이터는 건드리지 않는다.
"""

from __future__ import annotations

import json
from contextlib import closing
from pathlib import Path
from typing import Any

from backend.app.database import connect, initialize_database


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
MOCK_DIRECTORY = REPOSITORY_ROOT / "mock"


def load_json(filename: str) -> list[dict]:
    return json.loads((MOCK_DIRECTORY / filename).read_text(encoding="utf-8"))


def dumps(value: Any) -> str:
    """유니코드를 이스케이프하지 않고 JSON 문자열로 변환한다."""
    return json.dumps(value, ensure_ascii=False)


def sentence_numbers(value: Any) -> list[int]:
    """중첩된 리스트·딕셔너리에서 문장 번호를 모은다."""
    if isinstance(value, bool):
        raise ValueError(f"문장 번호 자리에 참/거짓 값이 있습니다: {value!r}")
    if isinstance(value, int):
        return [value]
    if isinstance(value, list):
        return [number for item in value for number in sentence_numbers(item)]
    if isinstance(value, dict):
        return [number for item in value.values() for number in sentence_numbers(item)]
    raise ValueError(f"문장 번호가 아닌 값이 있습니다: {value!r}")


def validate_claim_references(
    papers: list[dict], sentences: list[dict], claims: list[dict]
) -> None:
    """claim ID와 claim의 모든 문장 참조가 유효한지 적재 전에 확인한다."""
    known_sentences = {
        (sentence["paper_id"], sentence["idx"]) for sentence in sentences
    }
    paper_ids = {paper["paper_id"] for paper in papers}
    for claim in claims:
        paper_id = claim["paper_id"]
        if paper_id not in paper_ids:
            raise ValueError(f"claim의 논문이 papers.json에 없습니다: {paper_id}")

        expected_id = f"{paper_id}#{claim['claim_sentence']}"
        if claim["claim_id"] != expected_id:
            raise ValueError(
                f"claim_id 형식이 올바르지 않습니다: {claim['claim_id']} (기대값 {expected_id})"
            )

        referenced_indexes = [claim["claim_sentence"]]
        for field in ("evidence", "hedge", "conditions"):
            referenced_indexes.extend(sentence_numbers(claim[field]))
        missing = sorted(
            {
                index
                for index in referenced_indexes
                if (paper_id, index) not in known_sentences
            }
        )
        if missing:
            raise ValueError(
                f"claim {claim['claim_id']}이 존재하지 않는 문장 번호를 참조합니다: {missing}"
            )


def delete_stale_records(
    connection, papers: list[dict], sentences: list[dict], claims: list[dict]
) -> None:
    """목데이터 논문에서 현재 JSON에 없는 문장과 claim만 제거한다."""
    kept_sentences = {
        (sentence["paper_id"], sentence["idx"]) for sentence in sentences
    }
    kept_claim_ids = {claim["claim_id"] for claim in claims}
    for paper in papers:
        paper_id = paper["paper_id"]
        old_claims = connection.execute(
            "SELECT claim_id FROM claims WHERE paper_id = ?", (paper_id,)
        ).fetchall()
        for row in old_claims:
            if row["claim_id"] not in kept_claim_ids:
                connection.execute(
                    "DELETE FROM claims WHERE claim_id = ?", (row["claim_id"],)
                )

        old_sentences = connection.execute(
            "SELECT idx FROM sentences WHERE paper_id = ?", (paper_id,)
        ).fetchall()
        for row in old_sentences:
            if (paper_id, row["idx"]) not in kept_sentences:
                connection.execute(
                    "DELETE FROM sentences WHERE paper_id = ? AND idx = ?",
                    (paper_id, row["idx"]),
                )


def seed() -> tuple[int, int, int]:
    papers = load_json("papers.json")
    sentences = load_json("sentences.json")
    claims = load_json("claims.json")
    validate_claim_references(papers, sentences, claims)
    initialize_database()

    with closing(connect()) as connection:
        with connection:
            connection.executemany(
                """INSERT INTO papers (
                       paper_id, version, title, authors_json, abstract,
                       categories_json, published_at, source_url, source_format,
                       fulltext_path, fetched_at, status, error
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(paper_id) DO UPDATE SET
                       version = excluded.version,
                       title = excluded.title,
                       authors_json = excluded.authors_json,
                       abstract = excluded.abstract,
                       categories_json = excluded.categories_json,
                       published_at = excluded.published_at,
                       source_url = excluded.source_url,
                       source_format = excluded.source_format,
                       fulltext_path = excluded.fulltext_path,
                       fetched_at = excluded.fetched_at,
                       status = excluded.status,
                       error = excluded.error""",
                [
                    (
                        paper["paper_id"],
                        paper["version"],
                        paper["title"],
                        dumps(paper["authors"]),
                        paper["abstract"],
                        dumps(paper["categories"]),
                        paper["published_at"],
                        paper["source_url"],
                        paper.get("source_format"),
                        paper.get("fulltext_path"),
                        paper.get("fetched_at"),
                        paper["status"],
                        paper.get("error"),
                    )
                    for paper in papers
                ],
            )
            connection.executemany(
                """INSERT INTO sentences (
                       paper_id, idx, text, section, role, parser_version
                   ) VALUES (?, ?, ?, ?, ?, ?)
                   ON CONFLICT(paper_id, idx) DO UPDATE SET
                       text = excluded.text,
                       section = excluded.section,
                       role = excluded.role,
                       parser_version = excluded.parser_version""",
                [
                    (
                        sentence["paper_id"],
                        sentence["idx"],
                        sentence["text"],
                        sentence["section"],
                        sentence["role"],
                        sentence["parser_version"],
                    )
                    for sentence in sentences
                ],
            )
            connection.executemany(
                """INSERT INTO claims (
                       claim_id, paper_id, claim_sentence, evidence_json,
                       conditions_json, hedge_json, strength, confidence, checks_json
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(claim_id) DO UPDATE SET
                       paper_id = excluded.paper_id,
                       claim_sentence = excluded.claim_sentence,
                       evidence_json = excluded.evidence_json,
                       conditions_json = excluded.conditions_json,
                       hedge_json = excluded.hedge_json,
                       strength = excluded.strength,
                       confidence = excluded.confidence,
                       checks_json = excluded.checks_json""",
                [
                    (
                        claim["claim_id"],
                        claim["paper_id"],
                        claim["claim_sentence"],
                        dumps(claim["evidence"]),
                        dumps(claim["conditions"]),
                        dumps(claim["hedge"]),
                        claim["strength"],
                        claim["confidence"],
                        dumps(claim["checks"]),
                    )
                    for claim in claims
                ],
            )
            delete_stale_records(connection, papers, sentences, claims)

    return len(papers), len(sentences), len(claims)


if __name__ == "__main__":
    paper_count, sentence_count, claim_count = seed()
    print(
        "목데이터 적재 완료: "
        f"papers {paper_count}, sentences {sentence_count}, claims {claim_count}"
    )
