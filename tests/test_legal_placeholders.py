"""
Audit test: Verify legal documents (TERMS_OF_SERVICE.md, PRIVACY_POLICY.md)
for unresolved bracketed placeholders.
"""

import re
from pathlib import Path
import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def find_bracketed_placeholders(filepath: Path) -> list[str]:
    """Extract unresolved [bracketed placeholder] tokens from a markdown document."""
    if not filepath.exists():
        return [f"File missing: {filepath.name}"]
    text = filepath.read_text(encoding="utf-8")
    placeholders = []
    for line in text.splitlines():
        # Ignore markdown alert tags like > [!NOTE] or > [!IMPORTANT]
        if line.strip().startswith("> [!"):
            continue
        # Find bracketed patterns not followed by '(' (markdown links)
        for m in re.finditer(r"\[([^\]\n]+)\](?!\()", line):
            cand = m.group(1).strip()
            # Catch known placeholder markers or text with "pending" / "review"
            if any(k in cand.lower() for k in ("pending", "legal review", "legal name", "jurisdiction", "contact email", "address", "operator")):
                placeholders.append(f"[{cand}]")
    return placeholders


@pytest.mark.xfail(
    reason="User instruction: Keep the bracketed placeholders until real legal values are supplied.",
    strict=False,
)
def test_no_bracketed_placeholders_in_legal_docs():
    """Fails if any unresolved [bracketed placeholder] remains in TERMS_OF_SERVICE.md or PRIVACY_POLICY.md.

    Fails with an explicit AssertionError listing all unresolved placeholders when real values are missing.
    """
    terms_placeholders = find_bracketed_placeholders(REPO_ROOT / "TERMS_OF_SERVICE.md")
    privacy_placeholders = find_bracketed_placeholders(REPO_ROOT / "PRIVACY_POLICY.md")
    all_placeholders = terms_placeholders + privacy_placeholders

    assert not all_placeholders, (
        f"Unresolved bracketed placeholders remain in legal docs awaiting operator review: {all_placeholders}"
    )
