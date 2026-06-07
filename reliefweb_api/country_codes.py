"""
Country name → ISO 3166-1 alpha-3 code mapping.

Used by SITREP pipeline and weekly bulletin to convert
ReliefWeb country names to HDX-compatible ISO codes.

HDX HAPI API uses ISO 3166-1 alpha-3 codes (e.g., "SDN" for Sudan).
ReliefWeb uses full country names (e.g., "Sudan").

This module provides:
- COUNTRY_TO_ISO: dict mapping country name → ISO alpha-3 code
- ISO_TO_COUNTRY: reverse mapping
- get_iso_code(country_name): fuzzy lookup function
"""

from difflib import get_close_matches
from typing import Optional

# ---------------------------------------------------------------------------
# ISO 3166-1 alpha-3 code mapping
# ---------------------------------------------------------------------------
# Covers all countries that appear in ReliefWeb reports + HDX data.
# Priority: countries with active humanitarian crises listed first.

COUNTRY_TO_ISO: dict[str, str] = {
    # --- Active crisis countries (most common in ReliefWeb) ---
    "Sudan": "SDN",
    "South Sudan": "SSD",
    "Ukraine": "UKR",
    "Syria": "SYR",
    "Afghanistan": "AFG",
    "Yemen": "YEM",
    "Myanmar": "MMR",
    "Ethiopia": "ETH",
    "Somalia": "SOM",
    "Nigeria": "NGA",
    "Democratic Republic of the Congo": "COD",
    "Haiti": "HTI",
    "occupied Palestinian territory": "PSE",
    "Iraq": "IRQ",
    "Libya": "LBY",
    "Mali": "MLI",
    "Niger": "NER",
    "Cameroon": "CMR",
    "Burkina Faso": "BFA",
    "Central African Republic": "CAF",
    "Chad": "TCD",
    "Mozambique": "MOZ",
    "Bangladesh": "BGD",
    "Philippines": "PHL",
    "Pakistan": "PAK",
    "India": "IND",
    "Kenya": "KEN",
    "Tanzania": "TZA",
    "Uganda": "UGA",
    "Zimbabwe": "ZWE",
    "Venezuela": "VEN",
    "Colombia": "COL",
    "Ecuador": "ECU",
    "Peru": "PER",
    "Brazil": "BRA",
    "Lebanon": "LBN",
    "Israel": "ISR",
    "Türkiye": "TUR",
    "Turkey": "TUR",
    # --- Other countries with HDX data ---
    "Algeria": "DZA",
    "Angola": "AGO",
    "Argentina": "ARG",
    "Azerbaijan": "AZE",
    "Benin": "BEN",
    "Bolivia": "BOL",
    "Botswana": "BWA",
    "Burundi": "BDI",
    "Cambodia": "KHM",
    "Chile": "CHL",
    "China": "CHN",
    "Costa Rica": "CRI",
    "Cuba": "CUB",
    "Czech Republic": "CZE",
    "Czechia": "CZE",
    "Denmark": "DNK",
    "Dominican Republic": "DOM",
    "Egypt": "EGY",
    "El Salvador": "SLV",
    "Eritrea": "ERI",
    "Eswatini": "SWZ",
    "France": "FRA",
    "Gambia": "GMB",
    "Georgia": "GEO",
    "Ghana": "GHA",
    "Greece": "GRC",
    "Guatemala": "GTM",
    "Guinea": "GIN",
    "Guyana": "GUY",
    "Honduras": "HND",
    "Hungary": "HUN",
    "Indonesia": "IDN",
    "Iran": "IRN",
    "Italy": "ITA",
    "Ivory Coast": "CIV",
    "Côte d'Ivoire": "CIV",
    "Japan": "JPN",
    "Jordan": "JOR",
    "Kazakhstan": "KAZ",
    "Kuwait": "KWT",
    "Kyrgyzstan": "KGZ",
    "Laos": "LAO",
    "Lesotho": "LSO",
    "Liberia": "LBR",
    "Madagascar": "MDG",
    "Malawi": "MWI",
    "Malaysia": "MYS",
    "Mauritania": "MRT",
    "Mexico": "MEX",
    "Moldova": "MDA",
    "Mongolia": "MNG",
    "Morocco": "MAR",
    "Myanmar": "MMR",
    "Namibia": "NAM",
    "Nepal": "NPL",
    "Nicaragua": "NIC",
    "North Korea": "PRK",
    "Oman": "OMN",
    "Panama": "PAN",
    "Papua New Guinea": "PNG",
    "Paraguay": "PRY",
    "Poland": "POL",
    "Republic of Korea": "KOR",
    "South Korea": "KOR",
    "Romania": "ROU",
    "Russia": "RUS",
    "Rwanda": "RWA",
    "Saudi Arabia": "SAU",
    "Senegal": "SEN",
    "Sierra Leone": "SLE",
    "Slovakia": "SVK",
    "Slovenia": "SVN",
    "South Africa": "ZAF",
    "Spain": "ESP",
    "Sri Lanka": "LKA",
    "Sudan": "SDN",
    "Sweden": "SWE",
    "Switzerland": "CHE",
    "Syrian Arab Republic": "SYR",
    "Tajikistan": "TJK",
    "Thailand": "THA",
    "Togo": "TGO",
    "Tunisia": "TUN",
    "Turkmenistan": "TKM",
    "Türkiye": "TUR",
    "Turkey": "TUR",
    "Uganda": "UGA",
    "United Arab Emirates": "ARE",
    "United Kingdom": "GBR",
    "United States": "USA",
    "Uruguay": "URY",
    "Uzbekistan": "UZB",
    "Vanuatu": "VUT",
    "Vietnam": "VNM",
    "West Bank and Gaza": "PSE",
    "Zambia": "ZMB",

    # --- Territories and special entries ---
    "World": None,  # Not a country, no ISO code
    "Guam": "GUM",
    "Cyprus": "CYP",
    "Solomon Islands": "SLB",
}

# Reverse mapping: ISO code → country name
ISO_TO_COUNTRY: dict[str, str] = {v: k for k, v in COUNTRY_TO_ISO.items()}


def get_iso_code(country_name: str) -> Optional[str]:
    """
    Convert a country name to ISO 3166-1 alpha-3 code.

    Uses exact match first, then fuzzy matching with difflib.

    Args:
        country_name: Full country name (e.g., "Sudan", "Democratic Republic of the Congo")

    Returns:
        ISO alpha-3 code (e.g., "SDN") or None if not found.
    """
    if not country_name:
        return None

    # Exact match
    if country_name in COUNTRY_TO_ISO:
        return COUNTRY_TO_ISO[country_name]

    # Case-insensitive match
    lower = country_name.lower()
    for name, code in COUNTRY_TO_ISO.items():
        if name.lower() == lower:
            return code

    # Fuzzy match (close matches)
    matches = get_close_matches(country_name, COUNTRY_TO_ISO.keys(), n=1, cutoff=0.8)
    if matches:
        return COUNTRY_TO_ISO[matches[0]]

    return None


def get_country_name(iso_code: str) -> Optional[str]:
    """
    Convert an ISO 3166-1 alpha-3 code to a country name.

    Args:
        iso_code: ISO alpha-3 code (e.g., "SDN")

    Returns:
        Country name (e.g., "Sudan") or None if not found.
    """
    if not iso_code:
        return None
    return ISO_TO_COUNTRY.get(iso_code.upper())