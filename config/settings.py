"""
Configuration settings for the Bonfire Hub scraper
Contains all configurable paramaters for the scraping process
"""

import os

# Load environment variables from .env file if python-dotenv is installed
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # dotenv not installed, will use system environment variables

# ============== Account Credentials ==============
# NOTE: For production use, always use environment variables
# Never hardcode credentials in the config file

BONFIRE_EMAIL = os.getenv("BONFIRE_EMAIL", "")
BONFIRE_PASSWORD = os.getenv("BONFIRE_PASSWORD", "")

# ============== MongoDB Configuration ==============
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB_OPEN = "open_public_opportunities"
MONGO_DB_PAST = "past_public_opportunities"
MONGO_COLLECTION = "opportunities"

# ============== Scraping Parameters ==============
# How many agencies to collect per letter (D, G, J, L)
AGENCIES_PER_LETTER = 5

# Letters to filter agencies by
TARGET_LETTERS = ["D", "G", "J", "L"]

# Page size for API requests
PAGE_LIMIT = 80

# Max retry attempts for failed requests
MAX_RETRIES = 3

# Request timeout in seconds
REQUEST_TIMEOUT = 30

# Delay between requests (to avoid rate limiting)
REQUEST_DELAY = 1.5

# ============== Output Paths ==============
OUTPUT_DIR = "output"
RAW_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "raw")
CLEANED_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "cleaned")

# Output filenames
AGENCIES_FILE = "agencies.json"
OPEN_OPPORTUNITIES_RAW = "open_opportunities_raw.json"
PAST_OPPORTUNITIES_RAW = "past_opportunities_raw.json"
OPEN_OPPORTUNITIES_CLEAN = "open_opportunities_clean.json"
PAST_OPPORTUNITIES_CLEAN = "past_opportunities_clean.json"

# ============== Logging Configuration ==============
LOG_DIR = "logs"
LOG_FILE = "scraper.log"
LOG_LEVEL = "DEBUG"
LOG_FORMAT = "%(asctime)s %(levelname)-8s [%(name)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# ============== Browser Settings ==============
HEADLESS_MODE = True  # Set to False for debugging
BROWSER_TIMEOUT = 60

# ============== API Endpoints ==============
BASE_DOMAIN = "https://vendor.bonfirehub.com"
LOGIN_URL = "https://account.bonfirehub.com/login"
ORGANIZATIONS_API = "https://common-production-api-global.bonfirehub.com/v1.0/organizations/searchByLocation"
