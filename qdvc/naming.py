"""Project keys: the stable identifiers that tie log rows to projects."""

from __future__ import annotations

import unicodedata

MAX_KEY_LENGTH = 40


def slug(text: str) -> str:
    """Lower-case ASCII letters, digits and hyphens, at most 40 characters,
    made from ``text`` (accents dropped: "Café Réview: Phase 2!" becomes
    ``cafe-review-phase-2``). ``project`` if nothing is left."""
    decomposed = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()
    out = ""
    pending_hyphen = False
    for ch in folded:
        if ("a" <= ch <= "z") or ("0" <= ch <= "9"):
            if pending_hyphen and out:
                out += "-"
            pending_hyphen = False
            out += ch
        else:
            pending_hyphen = True
        if len(out) >= MAX_KEY_LENGTH:
            break
    out = out.rstrip("-")
    return out or "project"
