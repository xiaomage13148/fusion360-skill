import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("release", ROOT / "scripts/build_skill.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_reproducible_archive_matches_source(self):
        files = release.source_files()
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / "skill.zip"
            release.build(archive, files)
            release.verify(archive, files)
            first = archive.read_bytes()
            release.build(archive, files)
            self.assertEqual(archive.read_bytes(), first)
            changed = dict(files)
            changed["fusion360-mcp-cad/SKILL.md"] += b"changed"
            with self.assertRaises(ValueError):
                release.verify(archive, changed)
