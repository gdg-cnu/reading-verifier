import tempfile
import unittest
from pathlib import Path
from xml.etree import ElementTree as ET
from collector.arxiv import parse_entry
from collector.main import storage_key, store_file

class CollectorTests(unittest.TestCase):
    def test_atom_entry(self):
        entry = ET.fromstring('''<entry xmlns="http://www.w3.org/2005/Atom">
          <id>http://arxiv.org/abs/2402.08954v2</id><title> A title </title><summary>A\nsummary</summary>
          <published>2026-11-11T00:00:00Z</published><updated>2026-11-12T00:00:00Z</updated>
          <author><name>Author</name></author><category term="cs.AI"/></entry>''')
        p = parse_entry(entry)
        self.assertEqual((p.arxiv_id, p.version, p.abstract), ('2402.08954', 2, 'A summary'))
        self.assertEqual(p.categories, ['cs.AI'])

    def test_original_is_idempotent_and_not_overwritten(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            key = storage_key('hep-th/9901001', 1)
            self.assertIn('%2F', str(key))
            self.assertEqual(store_file(root, key, b'one'), store_file(root, key, b'one'))
            with self.assertRaises(ValueError):
                store_file(root, key, b'two')
            self.assertEqual((root / key).read_bytes(), b'one')

if __name__ == '__main__':
    unittest.main()

class VerificationTests(unittest.TestCase):
    def test_verify_detects_duplicate_and_missing_file(self):
        from collector.verify import verify
        from contextlib import redirect_stdout, redirect_stderr
        import io
        class Cursor:
            def execute(self, query): self.query = query
            def fetchone(self): return {'n': 2, 'ids': 1}
            def fetchall(self):
                if self.query.startswith('SELECT p.arxiv_id, f.storage_path'):
                    return [{'arxiv_id': 'x', 'storage_path': 'missing.html', 'sha256': '0', 'file_size': 1}]
                return []
            def close(self): pass
        class Connection:
            def cursor(self, **kwargs): return Cursor()
        with tempfile.TemporaryDirectory() as folder, redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()) as error:
            self.assertFalse(verify(Connection(), Path(folder).resolve()))
            self.assertIn('duplicate arxiv_id', error.getvalue())
            self.assertIn('missing file', error.getvalue())
