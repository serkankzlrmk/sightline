"""
Shared country data: coordinates, aliases, and ISO3 mappings.

All country-related constants should be imported from this module
instead of being duplicated across blueprints and sitrep modules.
"""

# ── Country coordinates (for map markers and crisis cards) ──────────────────
COUNTRY_COORDS: dict[str, dict] = {
    "Sudan": {"lat": 15.5, "lng": 32.5},
    "South Sudan": {"lat": 7.0, "lng": 30.0},
    "Ukraine": {"lat": 48.5, "lng": 31.2},
    "Syria": {"lat": 35.0, "lng": 38.0},
    "Afghanistan": {"lat": 33.9, "lng": 67.7},
    "Yemen": {"lat": 15.5, "lng": 48.5},
    "Democratic Republic of the Congo": {"lat": -2.5, "lng": 23.5},
    "Ethiopia": {"lat": 9.1, "lng": 40.5},
    "Nigeria": {"lat": 9.1, "lng": 8.7},
    "Myanmar": {"lat": 19.8, "lng": 96.2},
    "Bangladesh": {"lat": 23.7, "lng": 90.4},
    "Somalia": {"lat": 5.1, "lng": 46.2},
    "Iraq": {"lat": 33.2, "lng": 43.7},
    "Venezuela": {"lat": 6.4, "lng": -66.6},
    "Central African Republic": {"lat": 6.6, "lng": 20.9},
    "Mali": {"lat": 17.6, "lng": -4.0},
    "Niger": {"lat": 17.6, "lng": 8.0},
    "Burkina Faso": {"lat": 12.2, "lng": -1.6},
    "Cameroon": {"lat": 7.4, "lng": 12.4},
    "Chad": {"lat": 15.5, "lng": 18.7},
    "Lebanon": {"lat": 33.9, "lng": 35.5},
    "Pakistan": {"lat": 30.4, "lng": 69.3},
    "Haiti": {"lat": 18.97, "lng": -72.33},
    "Philippines": {"lat": 12.9, "lng": 122.0},
    "Colombia": {"lat": 4.6, "lng": -74.1},
    "Ecuador": {"lat": -1.8, "lng": -78.2},
    "Turkey": {"lat": 39.0, "lng": 35.2},
    "Iran": {"lat": 32.4, "lng": 53.7},
    "Libya": {"lat": 26.3, "lng": 17.2},
    "Mozambique": {"lat": -18.7, "lng": 35.5},
    "Zimbabwe": {"lat": -19.0, "lng": 29.2},
    "Uganda": {"lat": 1.4, "lng": 32.3},
    "Malawi": {"lat": -13.3, "lng": 34.3},
    "Madagascar": {"lat": -18.8, "lng": 47.5},
    "Angola": {"lat": -11.2, "lng": 17.9},
    "Gaza Strip": {"lat": 31.4, "lng": 34.3},
    "occupied Palestinian territory": {"lat": 31.9, "lng": 35.2},
    "Israel": {"lat": 31.0, "lng": 34.8},
    "Jordan": {"lat": 30.6, "lng": 36.2},
    "Egypt": {"lat": 26.8, "lng": 30.8},
    "Kenya": {"lat": -0.02, "lng": 37.9},
    "Tanzania": {"lat": -6.4, "lng": 34.9},
    "Rwanda": {"lat": -1.9, "lng": 29.9},
    "Burundi": {"lat": -3.4, "lng": 30.0},
    "Tanzania": {"lat": -6.4, "lng": 34.9},
    "Georgia": {"lat": 42.3, "lng": 43.4},
    "Moldova": {"lat": 47.0, "lng": 28.5},
    "Sri Lanka": {"lat": 7.9, "lng": 81.0},
    "El Salvador": {"lat": 13.8, "lng": -88.9},
    "Guatemala": {"lat": 14.6, "lng": -90.5},
    "Honduras": {"lat": 15.2, "lng": -86.2},
    "Nicaragua": {"lat": 12.9, "lng": -85.0},
    "Peru": {"lat": -9.2, "lng": -75.0},
    "Bolivia": {"lat": -16.3, "lng": -63.7},
    "Brazil": {"lat": -14.2, "lng": -51.9},
    "Mexico": {"lat": 23.6, "lng": -102.6},
    "Tunisia": {"lat": 33.9, "lng": 9.5},
    "Algeria": {"lat": 28.0, "lng": 1.7},
    "Morocco": {"lat": 31.8, "lng": -7.1},
    "Sudan": {"lat": 15.5, "lng": 32.5},
    "Eritrea": {"lat": 15.2, "lng": 39.8},
    "Djibouti": {"lat": 11.8, "lng": 42.6},
    "Cuba": {"lat": 21.5, "lng": -78.0},
    "Dominican Republic": {"lat": 18.7, "lng": -70.2},
    "Thailand": {"lat": 15.9, "lng": 100.9},
    "Indonesia": {"lat": -0.8, "lng": 113.9},
    "Nepal": {"lat": 28.4, "lng": 84.1},
    "India": {"lat": 20.6, "lng": 78.9},
}

# ── Country name aliases (ReliefWeb → common name) ──────────────────────────
COUNTRY_ALIASES: dict[str, str] = {
    "Syrian Arab Republic": "Syria",
    "Türkiye": "Turkey",
    "oPt": "occupied Palestinian territory",
    "DR Congo": "Democratic Republic of the Congo",
    "Congo": "Republic of the Congo",
    "Iran (Islamic Republic of)": "Iran",
    "Venezuela (Bolivarian Republic of)": "Venezuela",
    "Korea (Democratic People's Republic of)": "North Korea",
    "Korea (Republic of)": "South Korea",
    "Russian Federation": "Russia",
    "Moldova (Republic of)": "Moldova",
    "Tanzania (United Republic of)": "Tanzania",
    "Bolivia (Plurinational State of)": "Bolivia",
    "Venezuela (Bolivarian Republic of)": "Venezuela",
    "Iran, Islamic Republic of": "Iran",
    "Palestine": "occupied Palestinian territory",
    "Lao People's Democratic Republic": "Laos",
    "Viet Nam": "Vietnam",
    "Côte d'Ivoire": "Ivory Coast",
    "Eswatini": "Swaziland",
    "North Macedonia": "Macedonia",
}

# ── Reverse aliases (common → ReliefWeb) ────────────────────────────────────
REVERSE_COUNTRY_ALIASES: dict[str, str] = {v: k for k, v in COUNTRY_ALIASES.items()}


def get_country_coords(country: str) -> dict:
    """Get coordinates for a country name, trying aliases if direct lookup fails."""
    coords = COUNTRY_COORDS.get(country, {})
    if not coords:
        coords = COUNTRY_COORDS.get(COUNTRY_ALIASES.get(country, ""), {})
    if not coords:
        coords = COUNTRY_COORDS.get(REVERSE_COUNTRY_ALIASES.get(country, ""), {})
    return coords


# ── Country → ISO3 code mapping ──────────────────────────────────────────────
_COUNTRY_TO_ISO3: dict[str, str] = {
    "Afghanistan": "AFG", "Albania": "ALB", "Algeria": "DZA", "Angola": "AGO",
    "Argentina": "ARG", "Armenia": "ARM", "Azerbaijan": "AZE", "Bangladesh": "BGD",
    "Belarus": "BLR", "Benin": "BEN", "Bolivia": "BOL", "Brazil": "BRA",
    "Burkina Faso": "BFA", "Burundi": "BDI", "Cameroon": "CMR", "CAR": "CAF",
    "Central African Republic": "CAF", "Chad": "TCD", "Colombia": "COL",
    "Democratic Republic of the Congo": "COD", "Congo": "COG", "Djibouti": "DJI",
    "Dominican Republic": "DOM", "Ecuador": "ECU", "Egypt": "EGY", "El Salvador": "SLV",
    "Eritrea": "ERI", "Eswatini": "SWZ", "Ethiopia": "ETH", "Gaza Strip": "PSE",
    "Georgia": "GEO", "Ghana": "GHA", "Guatemala": "GTM", "Guinea": "GIN",
    "Haiti": "HTI", "Honduras": "HND", "India": "IND", "Indonesia": "IDN",
    "Iran": "IRN", "Iraq": "IRQ", "Israel": "ISR", "Jordan": "JOR",
    "Kenya": "KEN", "Lebanon": "LBN", "Libya": "LBY", "Madagascar": "MDG",
    "Malawi": "MWI", "Mali": "MLI", "Mexico": "MEX", "Moldova": "MDA",
    "Mozambique": "MOZ", "Myanmar": "MMR", "Nepal": "NPL", "Nicaragua": "NIC",
    "Niger": "NER", "Nigeria": "NGA", "occupied Palestinian territory": "PSE",
    "Pakistan": "PAK", "Peru": "PER", "Philippines": "PHL", "Russia": "RUS",
    "Rwanda": "RWA", "Somalia": "SOM", "South Sudan": "SSD", "Sri Lanka": "LKA",
    "Sudan": "SDN", "Syria": "SYR", "Tanzania": "TZA", "Thailand": "THA",
    "Tunisia": "TUN", "Turkey": "TUR", "Uganda": "UGA", "Ukraine": "UKR",
    "Uruguay": "URY", "Venezuela": "VEN", "Yemen": "YEM", "Zimbabwe": "ZWE",
}


def country_to_iso3(name: str) -> str:
    """Convert a country name to its ISO 3166-1 alpha-3 code."""
    iso3 = _COUNTRY_TO_ISO3.get(name)
    if iso3:
        return iso3
    # Try aliases
    canonical = COUNTRY_ALIASES.get(name, name)
    return _COUNTRY_TO_ISO3.get(canonical, "")