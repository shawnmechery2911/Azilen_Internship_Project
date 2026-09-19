"""Fail when a className in the UI has no CSS rule behind it.

This has bitten three times: thirteen classes that were never defined at all,
`.status`, and `.banner` - which the component rendered while the stylesheet
still called it `.result-banner`. Nothing catches it, because an unstyled
element renders perfectly happily as unstyled text and the build stays green.

    python scripts/check_styles.py

Exits non-zero and names the offenders, so it can sit in CI.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "frontend" / "src"

# Class names that come from somewhere other than this stylesheet.
IGNORED = {"sr-only"}

# Stands in for a `${...}` while a template literal is being read.
RUNTIME = "@RUNTIME@"


def used_classes() -> dict[str, set[Path]]:
    """Every literal class name in the components, and where it came from."""
    found: dict[str, set[Path]] = {}
    for file in SRC.rglob("*.tsx"):
        text = file.read_text(encoding="utf-8")
        chunks = re.findall(r'className="([^"]*)"', text)
        # A template literal builds part of the name at runtime:
        # `banner banner-${status}` yields a whole class `banner` and a prefix
        # `banner-` that nobody wrote a rule for and nobody should. Swapping
        # the interpolation for a marker keeps the two apart.
        for template in re.findall(r"className=\{`([^`]*)`\}", text):
            chunks.append(re.sub(r"\$\{[^}]*\}", RUNTIME, template))
        for chunk in chunks:
            for name in chunk.split():
                if RUNTIME in name:
                    continue
                if re.fullmatch(r"[a-z][a-z0-9_-]*", name):
                    found.setdefault(name, set()).add(file)
    return found


def defined_classes() -> set[str]:
    names: set[str] = set()
    for file in SRC.glob("*.css"):
        text = re.sub(r"/\*.*?\*/", "", file.read_text(encoding="utf-8"), flags=re.S)
        names |= set(re.findall(r"\.([a-zA-Z][a-zA-Z0-9_-]*)", text))
    return names


def main() -> int:
    used = used_classes()
    defined = defined_classes()
    missing = {
        name: files
        for name, files in used.items()
        if name not in defined and name not in IGNORED
    }
    if not missing:
        print(f"{len(used)} class names used, all defined.")
        return 0

    print(f"{len(missing)} class name(s) used in the UI with no CSS rule:\n")
    for name in sorted(missing):
        where = ", ".join(sorted(f.relative_to(SRC).as_posix() for f in missing[name]))
        print(f"  .{name:26} {where}")
    print("\nThese render as unstyled elements. The build will not complain.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
