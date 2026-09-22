"""Decide whether a feed item matters to the owner. Pure: no network, no clock, no state.

Feeds carry a title and a ~300-character summary and almost never name the origin city, so the
rules are tolerant on purpose (the owner's choice): anything that may be a sale from Belo
Horizonte passes, labelled with what is actually known.
"""
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache

import config
from promos.feeds import FeedItem

_PRICE = re.compile(r"r\$\s?\d")


@dataclass(frozen=True)
class Classification:
    kind: str                       # "fare" | "miles"
    destinations: tuple[str, ...]   # display labels, in the order the text cites them
    programs: tuple[str, ...]       # display labels, in the order the text cites them
    from_bh: bool
    origin_unknown: bool            # fare posts only


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


@lru_cache(maxsize=None)
def _word(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(normalize(term)) + r"(?!\w)")


def _first(terms, text: str) -> str | None:
    return next((t for t in terms if _word(t).search(text)), None)


def _labels_in_order(table: dict[str, str], text: str) -> tuple[str, ...]:
    """Labels of the terms present, ordered by where each first shows up, without repeats."""
    hits = []
    for term, label in table.items():
        found = _word(term).search(text)
        if found:
            hits.append((found.start(), label))
    ordered = []
    for _pos, label in sorted(hits):
        if label not in ordered:
            ordered.append(label)
    return tuple(ordered)


def _places(text: str) -> dict[str, tuple[str, ...]]:
    """Home, destination and other places cited. Longest names are matched first and blanked
    out, so "Porto Alegre" and "Porto Seguro" are never also counted as "Porto"."""
    table: list[tuple[str, str, str]] = [(t, "home", t) for t in config.PROMO_HOME_TERMS]
    table += [(a.cidade, "dest", a.cidade) for code, a in config.AIRPORTS.items() if code != config.AZUL_HUB]
    table += [(t, "dest", label) for t, label in config.PROMO_DESTINATION_ALIASES.items()]
    table += [(t, "other", t) for t in config.PROMO_OTHER_PLACES]
    table.sort(key=lambda row: len(normalize(row[0])), reverse=True)

    hits: dict[str, list[tuple[int, str]]] = {"home": [], "dest": [], "other": []}
    for term, kind, label in table:
        pattern = _word(term)
        found = pattern.search(text)
        if not found:
            continue
        hits[kind].append((found.start(), label))
        text = pattern.sub(lambda m: " " * len(m.group()), text)

    out = {}
    for kind, found in hits.items():
        ordered = []
        for _pos, label in sorted(found):
            if label not in ordered:
                ordered.append(label)
        out[kind] = tuple(ordered)
    return out


def classify(item: FeedItem) -> tuple[Classification | None, str]:
    """(classification or None, the rule that decided)."""
    text = normalize(f"{item.title} {item.summary}")
    places = _places(text)

    programs = _labels_in_order(config.PROMO_MILES_PROGRAMS, text)
    if programs and any(re.search(signal, text) for signal in config.PROMO_MILES_SIGNALS):
        return (Classification("miles", places["dest"], programs, from_bh=False, origin_unknown=False),
                f"miles:{programs[0]}")

    if _first(config.PROMO_FARE_WORDS, text) is None:
        return None, "rejected:no-fare-word"
    if not _PRICE.search(text) and _first(config.PROMO_OFFER_WORDS, text) is None:
        return None, "rejected:no-offer-signal"

    from_bh = bool(places["home"])
    if from_bh or places["dest"]:
        reason = "fare:home" if from_bh else f"fare:destination:{places['dest'][0]}"
        return Classification("fare", places["dest"], (), from_bh, origin_unknown=not from_bh), reason

    generic = _first(config.PROMO_GENERIC_TERMS, text)
    if generic:
        return Classification("fare", (), (), False, True), f"fare:generic:{generic}"
    if places["other"]:
        return None, f"rejected:other-place:{places['other'][0]}"
    return Classification("fare", (), (), False, True), "fare:no-place"
