"""Single-process, restartable arXiv metadata and HTML collector."""
import hashlib
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .arxiv import Client

START = datetime(2026, 11, 11, tzinfo=ZoneInfo('Asia/Seoul')).astimezone(timezone.utc)


def utc_naive(value):
    return value.astimezone(timezone.utc).replace(tzinfo=None)


def storage_key(identifier, version):
    # Encoding makes legacy identifiers with '/' a single safe path component.
    return Path('arxiv') / quote(identifier, safe='') / f'v{version}' / 'original.html'


def store_file(root, key, data):
    path = root / key
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(data).hexdigest()
    if path.exists():
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError('Existing original differs; manual review required')
        return digest
    fd, temporary = tempfile.mkstemp(prefix='.download-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return digest


def connect():
    import mysql.connector
    return mysql.connector.connect(host=os.getenv('MYSQL_HOST', '127.0.0.1'),
        port=int(os.getenv('MYSQL_PORT', '3306')), user=os.environ['MYSQL_USER'],
        password=os.environ.get('MYSQL_PASSWORD', ''), database=os.environ['MYSQL_DATABASE'],
        charset='utf8mb4', autocommit=False)


def register(conn, paper):
    cursor = conn.cursor()
    try:
        # Preserve the first observed version. Existing IDs never get a new job.
        cursor.execute('INSERT INTO papers (arxiv_id,version,title,abstract,authors,categories,published_at,updated_at,source_url) '
                       'VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON DUPLICATE KEY UPDATE id=LAST_INSERT_ID(id)',
                       (paper.arxiv_id, paper.version, paper.title, paper.abstract,
                        json.dumps(paper.authors, ensure_ascii=False), json.dumps(paper.categories, ensure_ascii=False),
                        utc_naive(paper.published), utc_naive(paper.updated), paper.url))
        cursor.execute('SELECT id, version FROM papers WHERE arxiv_id=%s', (paper.arxiv_id,))
        paper_id, existing_version = cursor.fetchone()
        if existing_version == paper.version:
            cursor.execute("INSERT INTO paper_jobs (paper_id,job_type,status) VALUES (%s,'download','pending') "
                           "ON DUPLICATE KEY UPDATE id=id", (paper_id,))
        else:
            logging.info('Skipping later version %s v%s; preserved v%s', paper.arxiv_id, paper.version, existing_version)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        cursor.close()


def collect_downloads(conn, client, root):
    cur = conn.cursor(dictionary=True)
    cur.execute("SELECT p.id,p.arxiv_id,p.version FROM papers p JOIN paper_jobs j ON j.paper_id=p.id "
                "WHERE j.job_type='download' AND j.status IN ('pending','failed','running') ORDER BY p.id")
    jobs = cur.fetchall()
    for job in jobs:
        paper_id, identifier, version = job['id'], job['arxiv_id'], job['version']
        cur.execute("UPDATE paper_jobs SET status='running',attempt_count=attempt_count+1,last_error=NULL "
                    "WHERE paper_id=%s AND job_type='download'", (paper_id,))
        conn.commit()
        try:
            from .arxiv import Paper
            paper = Paper(identifier, version, '', '', [], [], START, START, '')
            data, content_type = client.html(paper)
            if content_type not in ('text/html', 'application/xhtml+xml') or not re.search(br'<(?:html|!doctype\s+html)\b', data[:8192], re.I):
                raise ValueError(f'Unexpected HTML response: {content_type}')
            key = storage_key(identifier, version)
            checksum = store_file(root, key, data)
            url = f'https://arxiv.org/html/{quote(identifier, safe="/")}v{version}'
            cur.execute('INSERT INTO paper_files (paper_id,format,storage_path,source_url,sha256,file_size) '
                        "VALUES (%s,'html',%s,%s,%s,%s) ON DUPLICATE KEY UPDATE "
                        'storage_path=VALUES(storage_path),source_url=VALUES(source_url),sha256=VALUES(sha256),file_size=VALUES(file_size)',
                        (paper_id, str(key), url, checksum, len(data)))
            cur.execute("UPDATE paper_jobs SET status='completed',last_error=NULL WHERE paper_id=%s AND job_type='download'", (paper_id,))
            conn.commit()
            logging.info('Saved %s v%s', identifier, version)
        except HTTPError as exc:
            conn.rollback()
            status = 'unavailable' if exc.code == 404 else 'failed'
            cur.execute("UPDATE paper_jobs SET status=%s,last_error=%s WHERE paper_id=%s AND job_type='download'", (status, str(exc)[:1000], paper_id))
            conn.commit()
            logging.warning('%s v%s: %s', identifier, version, exc)
        except Exception as exc:
            conn.rollback()
            cur.execute("UPDATE paper_jobs SET status='failed',last_error=%s WHERE paper_id=%s AND job_type='download'", (str(exc)[:1000], paper_id))
            conn.commit()
            logging.exception('Download failed for %s v%s', identifier, version)
    cur.close()


def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    category = os.getenv('ARXIV_CATEGORY', 'cs.AI')
    if not re.fullmatch(r'[a-zA-Z-]+\.[a-zA-Z-]+', category):
        raise ValueError('ARXIV_CATEGORY must be a single arXiv category')
    root = Path(os.getenv('RAW_DATA_DIR', 'data/raw')).resolve()
    client, conn = Client(), connect()
    cursor = conn.cursor()
    locked = False
    try:
        cursor.execute("SELECT GET_LOCK('reading_verifier_arxiv_collector', 0)")
        if cursor.fetchone()[0] != 1:
            raise RuntimeError('Another collector is running')
        locked = True
        # Re-scan all fixed daily windows from the start. Slower as history grows,
        # but catches delayed indexing and needs no fragile offset checkpoint.
        now = datetime.now(timezone.utc)
        begin = START
        while begin < now:
            end = min(begin + timedelta(days=1), now)
            logging.info('Scanning %s to %s UTC', begin, end)
            for paper in client.search(category, begin, end):
                if START <= paper.published <= now:
                    register(conn, paper)
            begin = end
        collect_downloads(conn, client, root)
    finally:
        try:
            if locked:
                cursor.execute("SELECT RELEASE_LOCK('reading_verifier_arxiv_collector')")
                cursor.fetchone()
        finally:
            cursor.close()
            conn.close()

if __name__ == '__main__':
    main()
