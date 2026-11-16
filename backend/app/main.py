"""논문, 파싱된 문장, 추출된 claim을 조회하는 REST API."""

from __future__ import annotations

from contextlib import asynccontextmanager, closing
from datetime import date

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from backend.app.database import connect, initialize_database
from backend.app.records import claim_response, paper_response, sentence_response


# 내부 열인 fulltext_path를 쿼리 단계부터 제외한다.
PAPER_COLUMNS = """paper_id, version, title, authors_json, abstract,
                   categories_json, published_at, source_url, status, error"""
CLAIM_COLUMNS = """claim_id, paper_id, claim_sentence, evidence_json,
                   conditions_json, hedge_json, strength, confidence, checks_json"""


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="Reading Verifier API",
    version="0.1.0",
    lifespan=lifespan,
)


def not_found() -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "paper_not_found"})


@app.get("/papers", response_model=None)
def list_papers(
    category: str | None = None,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
) -> dict:
    # 날짜 형식 오류는 FastAPI가 표준 422 응답으로 반환한다.
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(status_code=422, detail="from must not be after to")

    sql = f"SELECT {PAPER_COLUMNS} FROM papers WHERE 1 = 1"
    parameters: list[str] = []
    if from_date is not None:
        sql += " AND published_at >= ?"
        parameters.append(from_date.isoformat())
    if to_date is not None:
        sql += " AND published_at <= ?"
        parameters.append(to_date.isoformat())
    if category is not None:
        sql += (
            " AND EXISTS (SELECT 1 FROM json_each(papers.categories_json)"
            " WHERE json_each.value = ?)"
        )
        parameters.append(category)
    sql += " ORDER BY published_at DESC, paper_id ASC"

    with closing(connect()) as connection:
        rows = connection.execute(sql, parameters).fetchall()
    return {"papers": [paper_response(row) for row in rows]}


@app.get("/papers/{paper_id}", response_model=None)
def get_paper(paper_id: str) -> dict | JSONResponse:
    with closing(connect()) as connection:
        paper = connection.execute(
            f"SELECT {PAPER_COLUMNS} FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if paper is None:
            return not_found()

        sentences = connection.execute(
            """SELECT idx, text, section, role, parser_version
               FROM sentences WHERE paper_id = ? ORDER BY idx""",
            (paper_id,),
        ).fetchall()
    return {
        "paper": paper_response(paper),
        "sentences": [sentence_response(row) for row in sentences],
    }


@app.get("/papers/{paper_id}/claims", response_model=None)
def get_paper_claims(paper_id: str) -> dict | JSONResponse:
    with closing(connect()) as connection:
        paper = connection.execute(
            "SELECT paper_id, status FROM papers WHERE paper_id = ?", (paper_id,)
        ).fetchone()
        if paper is None:
            return not_found()

        claims = connection.execute(
            f"SELECT {CLAIM_COLUMNS} FROM claims WHERE paper_id = ? "
            "ORDER BY claim_sentence",
            (paper_id,),
        ).fetchall()
    return {
        "paper_id": paper["paper_id"],
        "status": paper["status"],
        "claims": [claim_response(row) for row in claims],
    }
