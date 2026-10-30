#!/usr/bin/env python3
"""Build a deterministic Skill zip from the source directory, or verify it."""
import argparse
import os
from pathlib import Path
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "fusion360-mcp-cad"
ARCHIVE = ROOT / "fusion360-mcp-cad.zip"


def source_files():
    files = {}
    for path in sorted(SOURCE.rglob("*")):
        if "__pycache__" in path.parts or path.suffix not in {".md", ".py"}:
            continue
        if path.is_symlink():
            raise ValueError("release source must not contain symlinks: %s" % path)
        if path.is_file():
            files[path.relative_to(ROOT).as_posix()] = path.read_bytes()
    if "fusion360-mcp-cad/SKILL.md" not in files:
        raise ValueError("missing SKILL.md")
    return files


def verify(archive, files):
    with zipfile.ZipFile(archive) as package:
        if sorted(package.namelist()) != sorted(files):
            raise ValueError("archive file list differs from source")
        for name, content in files.items():
            if package.read(name) != content:
                raise ValueError("archive content differs: %s" % name)


def build(archive, files):
    # Atomic replace: a failed build leaves the previous release available.
    descriptor, temporary = tempfile.mkstemp(suffix=".zip", dir=archive.parent)
    os.close(descriptor)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as package:
            for name, content in sorted(files.items()):
                info = zipfile.ZipInfo(name, (1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = 0o100644 << 16
                package.writestr(info, content, compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
        verify(temporary, files)
        os.replace(temporary, archive)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify existing zip without modifying it")
    args = parser.parse_args(argv)
    try:
        files = source_files()
        if not args.check:
            build(ARCHIVE, files)
        verify(ARCHIVE, files)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        print("FAIL: %s" % exc)
        return 1
    print("Verified %d source files in %s" % (len(files), ARCHIVE.name))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
