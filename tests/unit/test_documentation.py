from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import unquote

_ROOT = Path(__file__).parents[2]
_ROOT_DOCS = (
    "README.md",
    "DEPLOYMENT.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "WORKLOG.md",
)
_MARKDOWN_LINK = re.compile(r"\[[^]]*]\(([^)]+)\)")


def _maintained_documents() -> list[Path]:
    documents = [_ROOT / name for name in _ROOT_DOCS]
    documents.extend(
        path
        for path in (_ROOT / "docs").rglob("*.md")
        if "archive/packs" not in path.as_posix() or path.name == "README.md"
    )
    return documents


def test_maintained_documentation_has_no_broken_local_links() -> None:
    broken: list[str] = []
    for document in _maintained_documents():
        for target in _MARKDOWN_LINK.findall(document.read_text()):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                continue
            relative_path = unquote(target.split("#", 1)[0])
            if relative_path and not (document.parent / relative_path).exists():
                broken.append(f"{document.relative_to(_ROOT)} -> {target}")
    assert broken == []


def test_historical_packs_live_in_the_archive() -> None:
    assert list(_ROOT.glob("*_PACK_V1.md")) == []
    assert (_ROOT / "docs/archive/packs/README.md").is_file()
    assert len(list((_ROOT / "docs/archive/packs").glob("*_PACK_V1.md"))) >= 20
