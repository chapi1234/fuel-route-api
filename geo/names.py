"""Place-name normalisation shared by the offline data build and request-time lookups.

The fuel price file and the Census Gazetteer spell the same towns differently
("Mc Kees Rocks" vs "McKees Rocks", "St. Louis" vs "Saint Louis", trailing
spaces, apostrophes). Both sides go through ``place_key`` so they meet in the middle.
"""

import re

US_STATES = frozenset(
    "AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV "
    "NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY".split()
)

_ABBREVIATIONS = [
    (re.compile(r"\bst\b\.?"), "saint"),
    (re.compile(r"\bste\b\.?"), "sainte"),
    (re.compile(r"\bft\b\.?"), "fort"),
    (re.compile(r"\bmt\b\.?"), "mount"),
    (re.compile(r"^n\b\.?"), "north"),
    (re.compile(r"^s\b\.?"), "south"),
    (re.compile(r"^e\b\.?"), "east"),
    (re.compile(r"^w\b\.?"), "west"),
]


def place_key(name: str) -> str:
    """Return a comparison key for a place name: lower case, expanded, no spaces or punctuation."""
    text = name.strip().lower().replace("'", "").replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text).strip()
    for pattern, replacement in _ABBREVIATIONS:
        text = pattern.sub(replacement, text)
    return re.sub(r"[^a-z0-9]", "", text)


# Census Gazetteer names carry the legal type ("Abbeville city", "Bow town",
# "Nashville-Davidson metropolitan government (balance)").
_BALANCE = re.compile(r"\s*\(balance\)$", re.I)
_GOVERNMENT = re.compile(
    r"\s+(consolidated government|metropolitan government|metro government|unified government|"
    r"urban county|city and borough)$",
    re.I,
)
_LEGAL_TYPE = re.compile(
    r"\s+(city|town|village|borough|cdp|municipality|township|charter township|plantation|"
    r"comunidad|zona urbana|corporation|grant|purchase|location|gore|reservation|precinct|"
    r"district|unorganized territory|ut)$",
    re.I,
)


def gazetteer_name_variants(name: str) -> list[str]:
    """All plausible plain names for a Gazetteer entry, most specific first.

    Only one legal-type suffix is removed, so "Bay City city" yields "Bay City", not "Bay".
    """
    variants = [name]
    plain = _BALANCE.sub("", name)
    plain = _GOVERNMENT.sub("", plain)
    variants.append(plain)
    if "-" in plain:
        variants.append(plain.split("-")[0])
    for candidate in list(variants):
        stripped = _LEGAL_TYPE.sub("", candidate)
        if stripped != candidate:
            variants.append(stripped)
    seen: dict[str, None] = {}
    for variant in variants:
        seen.setdefault(variant.strip(), None)
    return list(seen)
