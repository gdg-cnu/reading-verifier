"""Read-only database and local HTML integrity checks."""
import hashlib
import os
import sys
from pathlib import Path
from .main import connect


def verify(conn, root):
    errors = []
    cur = conn.cursor(dictionary=True)
    try:
        cur.execute('SELECT COUNT(*) AS n, COUNT(DISTINCT arxiv_id) AS ids FROM papers')
        counts = cur.fetchone()
        print(f"papers={counts['n']} unique_arxiv_ids={counts['ids']}")
        if counts['n'] != counts['ids']:
            errors.append('duplicate arxiv_id')
        cur.execute('SELECT status, COUNT(*) AS n FROM paper_jobs GROUP BY status ORDER BY status')
        for row in cur.fetchall():
            print(f"jobs.{row['status']}={row['n']}")
        cur.execute("SELECT p.arxiv_id FROM papers p LEFT JOIN paper_jobs j ON p.id=j.paper_id AND j.job_type='download' WHERE j.id IS NULL")
        errors.extend(f"missing download job: {row['arxiv_id']}" for row in cur.fetchall())
        cur.execute("SELECT p.arxiv_id FROM paper_jobs j JOIN papers p ON p.id=j.paper_id LEFT JOIN paper_files f ON f.paper_id=p.id AND f.format='html' WHERE j.job_type='download' AND j.status='completed' AND f.id IS NULL")
        errors.extend(f"completed without file record: {row['arxiv_id']}" for row in cur.fetchall())
        cur.execute('SELECT p.arxiv_id, f.storage_path, f.sha256, f.file_size FROM paper_files f JOIN papers p ON p.id=f.paper_id')
        rows = cur.fetchall()
        for row in rows:
            path = (root / row['storage_path']).resolve()
            if not path.is_relative_to(root):
                errors.append(f"invalid path: {row['arxiv_id']}")
            elif not path.is_file():
                errors.append(f"missing file: {row['arxiv_id']}")
            else:
                data = path.read_bytes()
                if len(data) != row['file_size'] or hashlib.sha256(data).hexdigest() != row['sha256']:
                    errors.append(f"file mismatch: {row['arxiv_id']}")
        print(f'files_checked={len(rows)}')
    finally:
        cur.close()
    for error in errors:
        print('ERROR:', error, file=sys.stderr)
    print(f'integrity_errors={len(errors)}')
    return not errors


def main():
    conn = connect()
    try:
        return 0 if verify(conn, Path(os.getenv('RAW_DATA_DIR', 'data/raw')).resolve()) else 1
    finally:
        conn.close()

if __name__ == '__main__':
    sys.exit(main())
