"""Conservative comparisons: unknown eligibility is kept for human review."""
import re

COUNTRIES = {
    "US": ("united states", "usa", "us", "u.s."),
    "GB": ("united kingdom", "uk", "great britain", "england", "scotland", "wales"),
    "KE": ("kenya",), "DE": ("germany", "deutschland"),
    "FR": ("france",), "NL": ("netherlands",), "IE": ("ireland",),
    "ES": ("spain",), "IT": ("italy",), "PL": ("poland",),
    "CA": ("canada",), "AU": ("australia",), "NZ": ("new zealand",),
    "ZA": ("south africa",), "NG": ("nigeria",), "GH": ("ghana",),
    "UG": ("uganda",), "TZ": ("tanzania",), "EG": ("egypt",),
    "AE": ("united arab emirates", "uae",), "IN": ("india",),
    "SG": ("singapore",), "BR": ("brazil",), "MX": ("mexico",),
}
REGIONS = {
    "africa": {"KE", "ZA", "NG", "GH", "UG", "TZ", "EG"},
    "europe": {"GB", "DE", "FR", "NL", "IE", "ES", "IT", "PL"},
    "eu": {"DE", "FR", "NL", "IE", "ES", "IT", "PL"},
    "north america": {"US", "CA", "MX"},
    "latam": {"BR", "MX"},
    "asia": {"IN", "SG", "AE"},
}
REGIONS["emea"] = REGIONS["europe"] | REGIONS["africa"] | {"AE"}


def _contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.IGNORECASE))


def remote_location_fit(candidate: str, restriction: str) -> bool | None:
    """True: supported location; False: known conflict; None: needs review.

    Country/region coverage is deliberately limited. Unrecognised locations
    are never guessed from a desired destination or an employer's name.
    """
    if any(_contains(restriction, term) for term in ("except", "excluding", "not", "outside")):
        return None
    candidate_countries = {code for code, names in COUNTRIES.items()
                           if any(_contains(candidate, name) for name in names)}
    allowed = {code for code, names in COUNTRIES.items()
               if any(_contains(restriction, name) for name in names)}
    for name, countries in REGIONS.items():
        if _contains(restriction, name):
            allowed.update(countries)
    if candidate_countries and allowed:
        return bool(candidate_countries & allowed)
    if not allowed and any(_contains(restriction, term) for term in ("worldwide", "anywhere", "global")):
        return True
    # Exact city/location correspondence is useful when neither country is known.
    if candidate.strip() and candidate.strip().casefold() == restriction.strip().casefold():
        return True
    return None


def currencies_match(left: str, right: str) -> bool:
    return bool(left and right and left.strip().upper() == right.strip().upper())


ADZUNA_CURRENCIES = {
    "gb": "GBP", "us": "USD", "au": "AUD", "nz": "NZD", "ca": "CAD",
    "de": "EUR", "fr": "EUR", "nl": "EUR", "it": "EUR", "es": "EUR",
    "at": "EUR", "be": "EUR", "pl": "PLN", "za": "ZAR", "in": "INR",
    "br": "BRL", "mx": "MXN", "sg": "SGD", "ch": "CHF",
}
