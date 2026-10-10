"""Doc check for swarm's Markdown (standard library only).

Three checks, on the Markdown sources:

1. Every relative link in README.md and under docs/ resolves to a file or
   directory that exists. External links (http, https, mailto) and in-page
   anchors are not checked.
2. No Markdown file carries a second front-matter block: a `---` line, then
   only `key: value` lines, then `---`, anywhere but at the very top. That
   is what a stray fragment left by a merge looks like.
3. What the README and the ADR index count or list matches the disk: the
   ADR index names every ADR file in docs/adr/ once and nothing else; the
   README's repository layout names only paths that exist and every module
   in episteme/; and every module has its tests/test_<module>.py, as the
   layout's "unit tests for all modules" says.

The shape follows architecture-definition-model's .github/scripts/check_docs.py.
The README-proof convention it backs was Dermot's decision of 10 October
2026: every capability bullet in the README names the test that proves it,
or says "no test yet" or "not yet implemented".

Run from anywhere: python .github/scripts/check_docs.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKIP = {"node_modules", "build", "dist"}
INLINE_CODE = re.compile(r"`[^`\n]*`")
LINK = re.compile(r"\]\(\s*<?([^)\s>]+)>?(?:\s+\"[^\"]*\")?\s*\)")
REF = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*<?([^\s>]+)>?")
SCHEME = re.compile(r"^[a-z][a-z0-9+.-]*:", re.IGNORECASE)
KEY = re.compile(r"^[A-Za-z_][\w-]*\s*:(\s|$)")
FENCE = re.compile(r"^\s*(```|~~~)")


def markdown_files() -> list[Path]:
    found = []
    for path in sorted(ROOT.rglob("*.md")):
        parts = path.relative_to(ROOT).parts
        if any(p.startswith(".") or p in SKIP or p.endswith(".egg-info") for p in parts[:-1]):
            continue
        found.append(path)
    return found


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def read(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").split("\n")


def prose(lines: list[str]) -> list[tuple[int, str]]:
    """Lines outside fenced code blocks, with inline code removed."""
    kept, fenced = [], False
    for number, line in enumerate(lines, start=1):
        if FENCE.match(line):
            fenced = not fenced
            continue
        if not fenced:
            kept.append((number, INLINE_CODE.sub("", line)))
    return kept


def front_matter(path: Path, errors: list[str]) -> None:
    lines, fenced, i = read(path), False, 0
    while i < len(lines):
        if FENCE.match(lines[i]):
            fenced = not fenced
        elif not fenced and lines[i].strip() == "---":
            j = i + 1
            while j < len(lines) and KEY.match(lines[j]):
                j += 1
            if j > i + 1 and j < len(lines) and lines[j].strip() == "---":
                if i > 0:
                    errors.append(f"{rel(path)}:{i + 1}: a front-matter block below the top")
                i = j
        i += 1


def links(path: Path, errors: list[str]) -> None:
    for number, line in prose(read(path)):
        targets = [m.group(1) for m in LINK.finditer(line)]
        ref = REF.match(line)
        if ref:
            targets.append(ref.group(1))
        for target in targets:
            if SCHEME.match(target) or target.startswith("#"):
                continue
            bare = target.split("#", 1)[0].split("?", 1)[0]
            if not bare:
                continue
            base = ROOT if bare.startswith("/") else path.parent
            if not (base / bare.lstrip("/")).exists():
                errors.append(f"{rel(path)}:{number}: link {target!r} resolves to nothing")


def section(lines: list[str], heading: str) -> list[str]:
    """The lines under a `## heading`, up to the next heading of any level."""
    out, inside = [], False
    for line in lines:
        if line.startswith("#"):
            if inside:
                break
            inside = line.lstrip("#").strip() == heading
            continue
        if inside:
            out.append(line)
    return out


def disk(errors: list[str]) -> None:
    adr_dir = ROOT / "docs" / "adr"
    on_disk = sorted(p.name for p in adr_dir.glob("[0-9][0-9][0-9][0-9]-*.md"))
    indexed = [m.group(1) for line in read(adr_dir / "README.md") for m in LINK.finditer(line)]
    indexed = [t for t in indexed if re.match(r"^\d{4}-", t)]
    for name in on_disk:
        if indexed.count(name) != 1:
            errors.append(f"docs/adr/README.md: lists {name} {indexed.count(name)} times, not once")
    for name in indexed:
        if name not in on_disk:
            errors.append(f"docs/adr/README.md: lists {name}, which is not in docs/adr/")

    layout = section(read(ROOT / "README.md"), "Repository layout")
    named = {m.group(1).rstrip("/") for line in layout for m in re.finditer(r"^- `([^`]+)`", line)}
    if not named:
        errors.append("README.md: no Repository layout list found")
    for name in sorted(named):
        if not (ROOT / name).exists():
            errors.append(f"README.md: the layout names {name}, which does not exist")
    for module in sorted((ROOT / "episteme").glob("*.py")):
        if module.name == "__init__.py":
            continue
        if f"episteme/{module.name}" not in named:
            errors.append(f"README.md: the layout does not name episteme/{module.name}")
        if not (ROOT / "tests" / f"test_{module.name}").exists():
            errors.append(f"tests/test_{module.name}: missing, and the README says all modules")


def main() -> int:
    errors: list[str] = []
    files = markdown_files()
    checked = [p for p in files if rel(p) == "README.md" or rel(p).startswith("docs/")]
    for path in files:
        front_matter(path, errors)
    for path in checked:
        links(path, errors)
    disk(errors)
    for error in errors:
        print(error)
    print(f"{len(files)} Markdown files, {len(checked)} link-checked, {len(errors)} problem(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
