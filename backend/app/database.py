"""API와 목데이터 적재기가 함께 사용하는 SQLite 설정."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATABASE_PATH = REPOSITORY_ROOT / "data" / "reading_verifier.sqlite3"


def database_path() -> Path:
    """설정된 SQLite 파일 경로를 부작용 없이 반환한다."""
    return Path(os.environ.get("READING_VERIFIER_DB", DEFAULT_DATABASE_PATH))


def connect() -> sqlite3.Connection:
    # timeout은 다른 프로세스의 쓰기가 끝날 때까지 최대 10초 기다린다.
    connection = sqlite3.connect(database_path(), timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout = 10000")
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def initialize_database() -> None:
    """상위 폴더와 논문, 문장, claim 테이블 및 검증 규칙을 준비한다."""
    database_path().parent.mkdir(parents=True, exist_ok=True)
    connection = connect()
    try:
        # WAL 설정은 파일에 저장되므로 연결마다 반복할 필요가 없다.
        connection.execute("PRAGMA journal_mode = WAL")
        with connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS papers (
                    paper_id TEXT PRIMARY KEY,
                    version TEXT NOT NULL,
                    title TEXT NOT NULL,
                    authors_json TEXT NOT NULL,
                    abstract TEXT NOT NULL,
                    categories_json TEXT NOT NULL,
                    published_at TEXT NOT NULL,
                    source_url TEXT NOT NULL,
                    source_format TEXT,
                    fulltext_path TEXT,
                    fetched_at TEXT,
                    status TEXT NOT NULL CHECK (
                        status IN ('fetched', 'parsed', 'extracted', 'failed')
                    ),
                    error TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_papers_published_at
                    ON papers(published_at);

                CREATE TABLE IF NOT EXISTS sentences (
                    paper_id TEXT NOT NULL,
                    idx INTEGER NOT NULL CHECK (idx >= 0),
                    text TEXT NOT NULL,
                    section TEXT NOT NULL,
                    role TEXT NOT NULL CHECK (
                        role IN (
                            'Background', 'Contribution', 'Method', 'Setup',
                            'Result', 'Analysis', 'Limitation', 'Caption', 'Other'
                        )
                    ),
                    parser_version TEXT NOT NULL,
                    PRIMARY KEY (paper_id, idx),
                    FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
                        ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS claims (
                    claim_id TEXT PRIMARY KEY,
                    paper_id TEXT NOT NULL,
                    claim_sentence INTEGER NOT NULL CHECK (claim_sentence >= 0),
                    evidence_json TEXT NOT NULL,
                    conditions_json TEXT NOT NULL,
                    hedge_json TEXT NOT NULL,
                    strength TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK (confidence BETWEEN 0 AND 1),
                    checks_json TEXT NOT NULL,
                    CHECK (claim_id = paper_id || '#' || claim_sentence),
                    FOREIGN KEY (paper_id) REFERENCES papers(paper_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (paper_id, claim_sentence)
                        REFERENCES sentences(paper_id, idx)
                );

                CREATE INDEX IF NOT EXISTS idx_claims_paper_sentence
                    ON claims(paper_id, claim_sentence);

                -- 이미 생성된 로컬 DB에도 동일한 제약을 적용한다.
                CREATE TRIGGER IF NOT EXISTS validate_paper_status_insert
                BEFORE INSERT ON papers
                WHEN NEW.status NOT IN ('fetched', 'parsed', 'extracted', 'failed')
                BEGIN
                    SELECT RAISE(ABORT, 'invalid paper status');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_paper_status_update
                BEFORE UPDATE OF status ON papers
                WHEN NEW.status NOT IN ('fetched', 'parsed', 'extracted', 'failed')
                BEGIN
                    SELECT RAISE(ABORT, 'invalid paper status');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_sentence_role_insert
                BEFORE INSERT ON sentences
                WHEN NEW.role NOT IN (
                    'Background', 'Contribution', 'Method', 'Setup', 'Result',
                    'Analysis', 'Limitation', 'Caption', 'Other'
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid sentence role');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_sentence_role_update
                BEFORE UPDATE OF role ON sentences
                WHEN NEW.role NOT IN (
                    'Background', 'Contribution', 'Method', 'Setup', 'Result',
                    'Analysis', 'Limitation', 'Caption', 'Other'
                )
                BEGIN
                    SELECT RAISE(ABORT, 'invalid sentence role');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_claim_confidence_insert
                BEFORE INSERT ON claims
                WHEN NEW.confidence < 0 OR NEW.confidence > 1
                BEGIN
                    SELECT RAISE(ABORT, 'confidence must be between 0 and 1');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_claim_confidence_update
                BEFORE UPDATE OF confidence ON claims
                WHEN NEW.confidence < 0 OR NEW.confidence > 1
                BEGIN
                    SELECT RAISE(ABORT, 'confidence must be between 0 and 1');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_claim_id_insert
                BEFORE INSERT ON claims
                WHEN NEW.claim_id != NEW.paper_id || '#' || NEW.claim_sentence
                BEGIN
                    SELECT RAISE(ABORT, 'claim_id does not match paper and sentence');
                END;

                CREATE TRIGGER IF NOT EXISTS validate_claim_id_update
                BEFORE UPDATE OF claim_id, paper_id, claim_sentence ON claims
                WHEN NEW.claim_id != NEW.paper_id || '#' || NEW.claim_sentence
                BEGIN
                    SELECT RAISE(ABORT, 'claim_id does not match paper and sentence');
                END;
                """
            )
    finally:
        connection.close()
