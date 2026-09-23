"""Geographic search matching, separate from eligibility to work in a country."""
import re
import unicodedata

AFRICAN_COUNTRIES = {
    "DZ": ("algeria",), "AO": ("angola",), "BJ": ("benin",),
    "BW": ("botswana",), "BF": ("burkina faso",), "BI": ("burundi",),
    "CV": ("cabo verde", "cape verde"), "CM": ("cameroon",),
    "CF": ("central african republic",), "TD": ("chad",),
    "KM": ("comoros",), "CG": ("republic of the congo", "congo brazzaville"),
    "CD": ("democratic republic of the congo", "dr congo", "drc", "congo kinshasa"),
    "CI": ("cote d'ivoire", "ivory coast"), "DJ": ("djibouti",),
    "EG": ("egypt",), "GQ": ("equatorial guinea",), "ER": ("eritrea",),
    "SZ": ("eswatini", "swaziland"), "ET": ("ethiopia",), "GA": ("gabon",),
    "GM": ("gambia",), "GH": ("ghana",), "GN": ("guinea",),
    "GW": ("guinea bissau",), "KE": ("kenya",), "LS": ("lesotho",),
    "LR": ("liberia",), "LY": ("libya",), "MG": ("madagascar",),
    "MW": ("malawi",), "ML": ("mali",), "MR": ("mauritania",),
    "MU": ("mauritius",), "MA": ("morocco",), "MZ": ("mozambique",),
    "NA": ("namibia",), "NE": ("niger",), "NG": ("nigeria",),
    "RW": ("rwanda",), "ST": ("sao tome and principe",), "SN": ("senegal",),
    "SC": ("seychelles",), "SL": ("sierra leone",), "SO": ("somalia",),
    "ZA": ("south africa",), "SS": ("south sudan",), "SD": ("sudan",),
    "TZ": ("tanzania",), "TG": ("togo",), "TN": ("tunisia",),
    "UG": ("uganda",), "ZM": ("zambia",), "ZW": ("zimbabwe",),
}
CITY_COUNTRIES = {
    "nairobi": "KE", "mombasa": "KE", "kisumu": "KE", "eldoret": "KE",
    "kampala": "UG", "entebbe": "UG", "dar es salaam": "TZ", "arusha": "TZ",
    "dodoma": "TZ", "kigali": "RW", "addis ababa": "ET", "djibouti": "DJ",
    "accra": "GH", "kumasi": "GH", "lagos": "NG", "abuja": "NG",
    "johannesburg": "ZA", "cape town": "ZA", "durban": "ZA", "pretoria": "ZA",
    "cairo": "EG", "alexandria": "EG", "casablanca": "MA", "rabat": "MA",
    "tunis": "TN", "algiers": "DZ", "dakar": "SN", "abidjan": "CI",
    "lusaka": "ZM", "harare": "ZW", "maputo": "MZ", "gaborone": "BW",
    "windhoek": "NA", "luanda": "AO", "kinshasa": "CD", "juba": "SS",
    "mogadishu": "SO", "lilongwe": "MW", "port louis": "MU",
    "dubai": "AE", "abu dhabi": "AE", "sharjah": "AE", "ajman": "AE",
    "fujairah": "AE", "ras al khaimah": "AE", "umm al quwain": "AE", "al ain": "AE",
    "riyadh": "SA", "jeddah": "SA", "dammam": "SA", "al khobar": "SA",
    "khobar": "SA", "jubail": "SA", "makkah": "SA", "mecca": "SA", "madinah": "SA",
    "medina": "SA", "neom": "SA",
    "doha": "QA", "al wakrah": "QA", "lusail": "QA",
    "kuwait city": "KW", "ahmadi": "KW", "hawalli": "KW",
    "muscat": "OM", "sohar": "OM", "salalah": "OM", "duqm": "OM", "nizwa": "OM",
    "manama": "BH", "muharraq": "BH", "riffa": "BH",
}

#: The six Gulf Cooperation Council states, as used by the Gulf search preset,
#: the Gulf job boards and the Jooble key list.
GULF_CODES = frozenset(("AE", "SA", "QA", "KW", "OM", "BH"))

#: Every region word a job's location may contain and a search may ask for.
#: ``location_matches`` expands these into country codes on both sides.
REGION_WORDS = ("africa", "emea", "europe", "eu", "north america", "asia", "latam",
                "gulf", "gcc", "middle east", "mena")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c)).lower().replace("-", " ")


def contains(text: str, term: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(normalise(term)) + r"(?!\w)", normalise(text)))


def country_codes(text: str) -> set[str]:
    from .eligibility import COUNTRIES
    countries = {**COUNTRIES, **AFRICAN_COUNTRIES, "AE": ("united arab emirates", "uae", "u.a.e.")}
    codes = {code for code, names in countries.items() if any(contains(text, n) for n in names)}
    codes.update(code for city, code in CITY_COUNTRIES.items() if contains(text, city))
    if text.strip().upper() in countries:
        codes.add(text.strip().upper())
    return codes


def region_codes(text: str) -> set[str]:
    from .eligibility import REGIONS
    regions = {**REGIONS, "africa": set(AFRICAN_COUNTRIES)}
    regions["emea"] = regions["europe"] | set(AFRICAN_COUNTRIES) | set(GULF_CODES)
    # "South Africa" is a country, not a request for every African country.
    return set(regions.get(normalise(text).strip(), set()))


def gulf_codes(text: str) -> set[str]:
    """Gulf (GCC) country codes named by a location: "Gulf", "Dubai", "GCC; UAE"…"""
    codes: set[str] = set()
    for part in re.split(r"[;,|]|\s+(?:and|or|&)\s+", text or "", flags=re.I):
        if part.strip():
            codes |= GULF_CODES & (country_codes(part) | region_codes(part))
    return codes


def location_matches(wanted: str, actual: str, remote: bool = False) -> bool:
    if not wanted.strip():
        return True
    if remote and any(contains(actual, value) for value in ("worldwide", "anywhere", "global")):
        return True
    targets = [p.strip() for p in re.split(r"[;,|]|\s+(?:and|or|&)\s+", wanted, flags=re.I) if p.strip()]
    actual_codes = country_codes(actual)
    for region in REGION_WORDS:
        if contains(actual, region) and not (region == "africa" and contains(actual, "south africa")):
            actual_codes.update(region_codes(region))
    for target in targets:
        if contains(actual, target):
            return True
        target_cities = [city for city in CITY_COUNTRIES if contains(target, city)]
        if target_cities:
            if any(contains(actual, city) for city in target_cities):
                return True
            # Remote country-wide roles can include a searched city.
            if not remote:
                continue
        if (region_codes(target) | country_codes(target)) & actual_codes:
            return True
    # Unknown remote restrictions remain reviewable; do not invent eligibility.
    return remote and not actual_codes
