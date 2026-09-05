"""Prohibited-parts screening.

Runs on the customer's own description at intake, before any quote exists. A match does not
silently drop the order — it declines with a reason, because most matches are innocent wording
and the customer deserves to know why. See docs/PLAN.md section 10 and config/shop.yaml.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import shop_config


@dataclass(frozen=True)
class SafetyVerdict:
    allowed: bool
    matched: tuple[str, ...] = ()
    message: str | None = None


DECLINE_MESSAGE = (
    "We can't take this one on. Our terms exclude firearm components, implantable or "
    "tissue-contacting medical parts, and safety-critical structural or life-support parts, "
    "because a printed part's strength depends on orientation and process in ways we can't "
    "certify. If we've misread your description, reply and tell us more about the part — this "
    "is a keyword check, and it gets innocent wording wrong sometimes."
)


def screen(text: str | None) -> SafetyVerdict:
    if not text:
        return SafetyVerdict(allowed=True)

    keywords = shop_config().get("prohibited", {}).get("keywords", [])
    haystack = text.lower()
    matched = []
    for keyword in keywords:
        # Word-boundary match so "brake" does not fire on "breakfast" and "gun" does not fire
        # on "gunwale". The parenthetical qualifiers in the config are stripped first.
        term = re.sub(r"\s*\(.*?\)", "", str(keyword)).strip().lower()
        if not term:
            continue
        if re.search(rf"\b{re.escape(term)}\b", haystack):
            matched.append(term)

    if matched:
        return SafetyVerdict(allowed=False, matched=tuple(matched), message=DECLINE_MESSAGE)
    return SafetyVerdict(allowed=True)
