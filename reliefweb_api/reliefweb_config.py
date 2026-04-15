"""
ReliefWeb API Configuration and Constants
"""

import os
from typing import Dict

# ========================================================================
# API CONFIGURATION
# ========================================================================

# ReliefWeb API Settings
RELIEFWEB_APPNAME = os.getenv("RELIEFWEB_APPNAME", "RELIEFWEB_APPNAME_PLACEHOLDER")
RELIEFWEB_API_BASE = "https://api.reliefweb.int/v2"
RELIEFWEB_REPORTS_API = f"{RELIEFWEB_API_BASE}/reports"
RELIEFWEB_DISASTERS_API = f"{RELIEFWEB_API_BASE}/disasters"
RELIEFWEB_SOURCES_API = f"{RELIEFWEB_API_BASE}/sources"

# ========================================================================
# TIMEOUT SETTINGS
# ========================================================================

API_TIMEOUT_SHORT = 30      # For simple queries
API_TIMEOUT_LONG = 120      # For complex queries
PDF_DOWNLOAD_TIMEOUT = 180   # For large PDF downloads (up to 50 MB)

# ========================================================================
# LIMITS AND CONSTRAINTS
# ========================================================================

REPORT_LIMIT_MAX = 1000
REPORT_LIMIT_DEFAULT = 25
DISASTER_LIMIT_MAX = 50
DISASTER_LIMIT_DEFAULT = 20
HEADLINE_LIMIT_DEFAULT = 15
BLOG_LIMIT_DEFAULT = 10
SUMMARY_DAYS_DEFAULT = 7

# PDF Constraints
PDF_SIZE_LIMIT = 50_000_000  # 50 MB in bytes
PDF_SIZE_LIMIT_MB = 50

# Content Limits
SUMMARY_CHAR_LIMIT = 700
EXCERPT_CHAR_LIMIT = 200

# Local SQLite DB (checked before making external API calls)
LOCAL_DB_PATH = os.getenv("DB_PATH", "reliefweb.db")

# ========================================================================
# COUNTRY NAME MAPPING
# ========================================================================

COUNTRY_NAME_MAP: Dict[str, str] = {
    # Middle East
    "syria": "Syrian Arab Republic",
    "yemen": "Yemen",
    "palestine": "occupied Palestinian territory",
    "gaza": "occupied Palestinian territory",
    "west bank": "occupied Palestinian territory",
    "iraq": "Iraq",
    "iran": "Iran (Islamic Republic of)",
    "lebanon": "Lebanon",
    "jordan": "Jordan",
    "turkey": "Türkiye",
    "turkiye": "Türkiye",
    "türkiye": "Türkiye",
    # Africa
    "democratic republic of the congo": "Democratic Republic of the Congo",
    "drc": "Democratic Republic of the Congo",
    "congo": "Democratic Republic of the Congo",
    "south sudan": "South Sudan",
    "sudan": "Sudan",
    "ethiopia": "Ethiopia",
    "somalia": "Somalia",
    "nigeria": "Nigeria",
    "mali": "Mali",
    "burkina faso": "Burkina Faso",
    "niger": "Niger",
    "chad": "Chad",
    "cameroon": "Cameroon",
    "central african republic": "Central African Republic",
    "car": "Central African Republic",
    "mozambique": "Mozambique",
    "libya": "Libya",
    "kenya": "Kenya",
    "uganda": "Uganda",
    # Asia
    "myanmar": "Myanmar",
    "burma": "Myanmar",
    "afghanistan": "Afghanistan",
    "pakistan": "Pakistan",
    "bangladesh": "Bangladesh",
    "philippines": "Philippines",
    "nepal": "Nepal",
    "india": "India",
    "sri lanka": "Sri Lanka",
    # Americas
    "haiti": "Haiti",
    "colombia": "Colombia",
    "venezuela": "Venezuela (Bolivarian Republic of)",
    "honduras": "Honduras",
    "guatemala": "Guatemala",
    "el salvador": "El Salvador",
    # Europe
    "ukraine": "Ukraine",
}

# ========================================================================
# DISASTER TYPE REFERENCE
# ========================================================================

DISASTER_TYPES = [
    "Drought", "Earthquake", "Epidemic", "Flash Flood", "Flood",
    "Food Insecurity", "Heat Wave", "Cold Wave", "Insect Infestation",
    "Land Slide", "Mud Slide", "Complex Emergency", "Cyclone",
    "Fire", "Storm Surge", "Technological Disaster", "Tsunami",
    "Volcano", "Wild Fire",
]

# ========================================================================
# ORGANIZATION TYPE REFERENCE
# ========================================================================

ORG_TYPES = [
    "International NGO", "National NGO", "Government",
    "International Organization", "United Nations",
    "Academic and Research Institution", "Donor", "Media", "Red Cross / Red Crescent",
    "Other",
]

# ========================================================================
# FIELD SELECTIONS
# ========================================================================

# Fields to request from API (minimizes payload)
REPORT_FIELDS = ["id", "title", "date", "source", "url"]
REPORT_FULL_FIELDS = [
    "id", "title", "date", "source", "url",
    "body", "body-html", "headline",
    "country", "disaster", "theme",
    "format", "language", "origin"
]
DISASTER_FIELDS = ["id", "name", "type", "status", "date", "country", "url", "glide"]
HEADLINE_FIELDS = ["id", "title", "date", "source", "url", "country", "theme"]

# ========================================================================
# ERROR MESSAGES
# ========================================================================

ERROR_NO_REPORTS = "No reports found for {country}"
ERROR_API_COMMUNICATION = "Error communicating with ReliefWeb API: {error}"
ERROR_INVALID_COUNTRY = "Invalid country name: {country}"
ERROR_INVALID_LIMIT = "Limit must be between 1 and {max}"
ERROR_INVALID_DATE = "Invalid date format: {date}. Use YYYY-MM-DD"

# ========================================================================
# SUCCESS MESSAGES
# ========================================================================

SUCCESS_REPORTS_FOUND = "Found {count} reports for {country}"
SUCCESS_DISASTERS_FOUND = "Found {count} disasters"
SUCCESS_HEADLINES_FOUND = "Found {count} headlines"

# ========================================================================
# LOGGING CONFIGURATION
# ========================================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# ========================================================================
# FEATURE FLAGS
# ========================================================================

ENABLE_CACHING = False  # Set to True in production
ENABLE_RETRY = True
MAX_RETRIES = 3
RETRY_DELAY = 1  # seconds

# ========================================================================
# VALIDATION RULES
# ========================================================================

MIN_COUNTRY_LENGTH = 2
MAX_COUNTRY_LENGTH = 50
MAX_QUERY_LENGTH = 500
DATE_FORMAT = "%Y-%m-%d"

# ========================================================================
# API RESPONSE SETTINGS
# ========================================================================

RESPONSE_INDENT = 2
ENSURE_ASCII = False  # Allow non-ASCII characters
