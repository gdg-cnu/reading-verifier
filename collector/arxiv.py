"""Small arXiv Atom client. Network requests are serialized and rate limited."""
import logging
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen
from xml.etree import ElementTree as ET

ATOM = '{http://www.w3.org/2005/Atom}'
ARXIV = '{http://arxiv.org/schemas/atom}'
OPEN = '{http://a9.com/-/spec/opensearch/1.1/}'
ID_RE = re.compile(r'^(?P<id>(?:\d{4}\.\d{4,}|[a-z-]+(?:\.[A-Z]{2})?/\d{7}))v(?P<version>[1-9]\d*)$')

@dataclass(frozen=True)
class Paper:
    arxiv_id: str
    version: int
    title: str
    abstract: str
    authors: list[str]
    categories: list[str]
    published: datetime
    updated: datetime
    url: str


def parse_entry(entry):
    url = (entry.findtext(ATOM + 'id') or '').strip()
    identifier = url.split('/abs/', 1)[-1]
    match = ID_RE.fullmatch(identifier)
    if not match:
        raise ValueError(f'Unexpected arXiv identifier: {url}')
    def dt(name):
        return datetime.fromisoformat(entry.findtext(ATOM + name).replace('Z', '+00:00')).astimezone(timezone.utc)
    def clean(value):
        return ' '.join((value or '').split())
    return Paper(match['id'], int(match['version']), clean(entry.findtext(ATOM + 'title')),
                 clean(entry.findtext(ATOM + 'summary')),
                 [clean(a.findtext(ATOM + 'name')) for a in entry.findall(ATOM + 'author')],
                 [c.get('term') for c in entry.findall(ATOM + 'category') if c.get('term')],
                 dt('published'), dt('updated'), url)

class Client:
    def __init__(self, delay=3.1, attempts=4):
        self.delay, self.attempts, self.last = max(delay, 3.0), attempts, 0.0

    def get(self, url):
        from urllib.error import HTTPError, URLError
        for attempt in range(self.attempts):
            time.sleep(max(0, self.delay - (time.monotonic() - self.last)))
            self.last = time.monotonic()
            try:
                with urlopen(Request(url, headers={'User-Agent': 'reading-verifier/0.1 (research project)'}), timeout=45) as response:
                    return response.read(), response.headers.get_content_type()
            except HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt + 1 == self.attempts:
                    raise
                retry = exc.headers.get('Retry-After', '')
                wait = float(retry) if retry.isdigit() else 2 ** (attempt + 1)
            except (URLError, TimeoutError):
                if attempt + 1 == self.attempts:
                    raise
                wait = 2 ** (attempt + 1)
            logging.warning('Temporary network error; retrying in %.1fs', wait)
            time.sleep(wait)

    def search(self, category, start, end):
        # A fixed one-day UTC window limits mutable offset pagination and backfill size.
        query = f'cat:{category} AND submittedDate:[{start:%Y%m%d%H%M} TO {end:%Y%m%d%H%M}]'
        offset, page_size = 0, 100
        while True:
            params = urlencode({'search_query': query, 'start': offset, 'max_results': page_size,
                                'sortBy': 'submittedDate', 'sortOrder': 'ascending'})
            data, _ = self.get('https://export.arxiv.org/api/query?' + params)
            root = ET.fromstring(data)
            if root.tag != ATOM + 'feed':
                raise ValueError('Invalid arXiv feed')
            total_text = root.findtext(OPEN + 'totalResults')
            if total_text is None:
                raise ValueError('arXiv feed missing totalResults')
            total = int(total_text)
            entries = root.findall(ATOM + 'entry')
            if total > 1000:
                raise ValueError('More than 1000 results in one day; narrow the query')
            if not entries and offset < total:
                raise ValueError('arXiv returned an incomplete page')
            for entry in entries:
                yield parse_entry(entry)
            offset += len(entries)
            if offset >= total:
                return

    def html(self, paper):
        identifier = quote(paper.arxiv_id, safe='/') + 'v' + str(paper.version)
        return self.get('https://arxiv.org/html/' + identifier)
