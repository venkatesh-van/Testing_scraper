"""Zip this project folder, leaving out junk and secrets.

Run from inside the project folder:   python make_zip.py
Creates ../<folder name>.zip next to the folder.
"""

import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT.parent / "sothebys_scraper.zip"

SKIP_DIRS = {".venv", "venv", "__pycache__", ".pytest_cache", ".git", "logs", "crawl-state"}
SKIP_FILES = {".env", ".DS_Store", OUTPUT.name}
SKIP_PATHS = ("data/raw/",)          # saved web pages: large, re-creatable
SKIP_SUFFIXES = (".pyc",)

count = 0
with zipfile.ZipFile(OUTPUT, "w", zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(ROOT.rglob("*")):
        relative = path.relative_to(ROOT).as_posix()
        if path.is_dir():
            continue
        if any(part in SKIP_DIRS or part.startswith("crawl-state") for part in path.relative_to(ROOT).parts):
            continue
        if path.name in SKIP_FILES or path.suffix in SKIP_SUFFIXES:
            continue
        if relative.startswith(SKIP_PATHS) and path.name != ".gitkeep":
            continue
        archive.write(path, Path("sothebys_scraper") / relative)
        count += 1

print(f"Zipped {count} files -> {OUTPUT}")