from __future__ import annotations

from typing import Dict, List, Set
import re

_HC_NUM_SUFFIX = re.compile(r"\s+\d+\s*$")


def strip_angle_tag(phrase: str) -> str:
    """
    Return the bare phrase before any '<...>' tag.
      'Liquid <Pool fire 1>' -> 'Liquid'
    """
    if "<" in phrase:
        return phrase.split("<", 1)[0].strip()
    return phrase.strip()


def _normalize_hazard_base(name: str) -> str:
    """
    Remove trailing numeric suffix:
      'Confined explosion 1' -> 'Confined explosion'
    """
    return _HC_NUM_SUFFIX.sub("", name.strip()).strip()


def is_condition_label(phrase: str, conditions: Dict[str, List[str]]) -> bool:
    """
    CONDITION_LABEL:
    - Match is done STRICTLY on bare phrase (ignoring any '<...>' tag).
    """
    base = strip_angle_tag(phrase)
    cond_set: Set[str] = {x for items in conditions.values() for x in items}
    return base in cond_set


def is_hazard_consequence(phrase: str, hazard_consequence: List[str]) -> bool:
    """
    HAZARD_CONSEQUENCE:
    - Ignore '<...>' tag completely.
    - Match only on bare phrase.
    - Normalize numeric suffix on the bare phrase before matching.
    """
    base = strip_angle_tag(phrase)          # ignore tag
    base = _normalize_hazard_base(base)     # handle '... 1'

    hc_set: Set[str] = {_normalize_hazard_base(h) for h in hazard_consequence}
    return base in hc_set
