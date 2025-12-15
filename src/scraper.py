"""
Bonfire Hub Web Scraper
Scrapes bidding opportunities from vendor.bonfirehub.com using Pydoll

This module handles all the web scraping logic including:
- Authentication with the Bonfire portal
- Fetching agency listings filtered by starting letters
- Extracting open and past public oppurtunities
"""

import json
import re
import os
import asyncio
import logging
import shutil
import tempfile
import atexit
import time
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from pydoll.browser.chromium import Chrome
from pydoll.browser.options import ChromiumOptions


# ============== Windows Temp Cleanup Fix ==============
# Chrome browser creates temp files that may not be immediately released on Windows
# This causes PermissionError during Python's exit cleanup
def _safe_cleanup_temp_dirs():
    """Safely cleanup browser temp directories, ignoring locked files"""
    temp_dir = tempfile.gettempdir()
    for item in os.listdir(temp_dir):
        if item.startswith('tmp') and os.path.isdir(os.path.join(temp_dir, item)):
            try:
                path = os.path.join(temp_dir, item)
                # Check if it looks like a browser temp dir
                if os.path.exists(os.path.join(path, 'BrowserMetrics')):
                    shutil.rmtree(path, ignore_errors=True)
            except Exception:
                pass  # Ignore cleanup errors

# Register cleanup to run at exit (before Python's internal cleanup)
atexit.register(_safe_cleanup_temp_dirs)

# Import config (adjust path based on how script is run)
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.settings import (
        BONFIRE_EMAIL, BONFIRE_PASSWORD, AGENCIES_PER_LETTER,
        TARGET_LETTERS, PAGE_LIMIT, MAX_RETRIES, REQUEST_DELAY,
        RAW_OUTPUT_DIR, AGENCIES_FILE, OPEN_OPPORTUNITIES_RAW,
        PAST_OPPORTUNITIES_RAW, ORGANIZATIONS_API, LOGIN_URL
    )
except ImportError:
    # Fallback defaults if config not found
    BONFIRE_EMAIL = ""
    BONFIRE_PASSWORD = ""
    AGENCIES_PER_LETTER = 5
    TARGET_LETTERS = ["D", "G", "J", "L"]
    PAGE_LIMIT = 80
    MAX_RETRIES = 3
    REQUEST_DELAY = 1.5
    RAW_OUTPUT_DIR = "output/raw"
    AGENCIES_FILE = "agencies.json"
    OPEN_OPPORTUNITIES_RAW = "open_opportunities_raw.json"
    PAST_OPPORTUNITIES_RAW = "past_opportunities_raw.json"
    ORGANIZATIONS_API = "https://common-production-api-global.bonfirehub.com/v1.0/organizations/searchByLocation"
    LOGIN_URL = "https://account.bonfirehub.com/login"


# Setup logging for this module
logger = logging.getLogger("bonfire_scraper")


def setup_logging(log_file: str = "logs/scraper.log"):
    """Configure logging for the scraper"""

    os.makedirs(os.path.dirname(log_file), exist_ok=True)

    logger.setLevel(logging.DEBUG)

    # File handler
    fh = logging.FileHandler(log_file, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s [Line:%(lineno)d]",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    # Console handler - only warnings and errors
    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(ch)

    # Suppress noisy third-party logs
    logging.getLogger("pydoll").setLevel(logging.ERROR)
    logging.getLogger("urllib3").setLevel(logging.ERROR)
    logging.getLogger("asyncio").setLevel(logging.ERROR)
    logging.getLogger("pymongo").setLevel(logging.ERROR)


def calculate_days_remaining(deadline_str: str) -> int:
    """
    Calculate number of days remaining until a deadline

    Args:
        deadline_str: Date string in format 'YYYY-MM-DD HH:MM:SS'

    Returns:
        Number of days remaining (0 if deadline passed)
    """
    try:
        deadline = datetime.strptime(deadline_str, "%Y-%m-%d %H:%M:%S")
        now = datetime.now()

        if deadline <= now:
            return 0

        delta = deadline - now
        return delta.days
    except (ValueError, TypeError):
        return 0


def extract_json_from_page(page_content: str) -> Optional[dict]:
    """Extract JSON data from page source wrapped in <pre> tags"""
    match = re.search(r'<pre>(.+?)</pre>', page_content, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse JSON: {e}")
    return None


class BonfireScraper:
    """
    Main scraper class for extracting data from Bonfire Hub

    Usage:
        scraper = BonfireScraper(email, password)
        await scraper.run()
    """

    def __init__(self, email: str, password: str):
        self.email = email
        self.password = password
        self.browser = None
        self.tab = None
        self.agencies = []

    async def start_browser(self):
        """Initialize the browser instance"""
        logger.info("Starting browser...")

        # Configure Chrome options for Docker
        options = ChromiumOptions()
        if os.environ.get('DOCKER_ENV'):
            options.add_argument('--headless=new')
            options.add_argument('--no-sandbox')
            options.add_argument('--disable-dev-shm-usage')
            options.add_argument('--disable-gpu')
            options.add_argument('--window-size=1920,1080')

        self.browser = Chrome(options=options)
        self.tab = await self.browser.start()

    async def close_browser(self):
        """Cleanup browser resources"""
        try:
            if self.tab:
                await self.tab.close()
            if self.browser:
                await self.browser.close()
            logger.info("Browser closed")
            # Give Chrome time to release file handles (Windows fix)
            await asyncio.sleep(1)
        except Exception as e:
            logger.warning(f"Browser cleanup warning (can be ignored): {e}")

    async def login(self) -> bool:
        """
        Authenticate with Bonfire Hub portal

        Returns:
            True if login successful, False otherwise
        """
        try:
            logger.info("Attempting login...")
            await self.tab.go_to(LOGIN_URL)

            # Wait for and fill email field
            email_field = await self.tab.query(
                "input#input-email",
                timeout=10,
                raise_exc=False
            )
            if not email_field:
                logger.error("Could not find email input field")
                return False

            await email_field.type_text(self.email)

            # Click continue button
            continue_btn = await self.tab.query(
                "//button[@type='submit']",
                timeout=10,
                raise_exc=False
            )
            if not continue_btn:
                logger.error("Continue button not found")
                return False

            await continue_btn.click()
            await asyncio.sleep(3)  # Wait for password field to appear

            # Try different selectors for password field
            password_selectors = [
                "input#password",
                "input[type='password']",
                "//input[@type='password']"
            ]

            pswd_field = None
            for selector in password_selectors:
                pswd_field = await self.tab.query(selector, timeout=5, raise_exc=False)
                if pswd_field:
                    break

            if not pswd_field:
                logger.error("Password field not found")
                return False

            await pswd_field.type_text(self.password)

            # Submit login form
            login_btn = await self.tab.query(
                "//button[@type='submit']",
                timeout=10,
                raise_exc=False
            )
            if login_btn:
                await login_btn.click()
                await asyncio.sleep(5)  # Wait for login to complete

            logger.info("Login successful!")
            return True

        except Exception as e:
            logger.exception(f"Login failed: {e}")
            return False

    async def fetch_agencies(self) -> List[Dict]:
        """
        Fetch list of agencies filtered by target letters (D, G, J, L)

        Retrieves agencies from the Bonfire API and filters them
        to get required number per each target letter.

        Returns:
            List of agency dictionaries with name and url
        """
        logger.info("Fetching agency listings...")

        # Wait a bit after login before hitting API
        await asyncio.sleep(40)

        agencies_by_letter = {letter: [] for letter in TARGET_LETTERS}
        page_num = 1
        reached_end = False

        while not reached_end:
            logger.debug(f"Processing page {page_num}")

            # Check if we have enough agencies for all letters
            all_full = all(
                len(agencies_by_letter[l]) >= AGENCIES_PER_LETTER
                for l in TARGET_LETTERS
            )
            if all_full:
                logger.info("Collected required agencies for all target letters")
                break

            url = f"{ORGANIZATIONS_API}?page={page_num}&limit={PAGE_LIMIT}"

            for attempt in range(MAX_RETRIES):
                try:
                    await self.tab.go_to(url)
                    page_content = await self.tab.page_source

                    json_data = extract_json_from_page(page_content)

                    # Empty response means we've reached the end
                    if json_data == [] or not json_data:
                        reached_end = True
                        break

                    # Check for error response
                    if isinstance(json_data, dict) and json_data.get("message"):
                        reached_end = True
                        break

                    # Process each organization in response
                    for org in json_data:
                        try:
                            name = org.get("OrganizationName", "")
                            domain = org.get("Domain", "")

                            if not name or not domain:
                                continue

                            first_letter = name[0].upper()

                            if first_letter in TARGET_LETTERS:
                                if len(agencies_by_letter[first_letter]) < AGENCIES_PER_LETTER:
                                    agency_data = {
                                        "agency_name": name,
                                        "agency_url": f"https://{domain}"
                                    }
                                    agencies_by_letter[first_letter].append(agency_data)
                                    logger.info(f"Added agency [{first_letter}]: {name}")

                        except Exception as e:
                            logger.debug(f"Error processing org record: {e}")

                    break  # Successful, move to next page

                except Exception as e:
                    logger.warning(f"Request failed (attempt {attempt+1}/{MAX_RETRIES}): {e}")
                    await asyncio.sleep(REQUEST_DELAY)

            page_num += 1

        # Combine all agencies
        selected = []
        for letter in TARGET_LETTERS:
            selected.extend(agencies_by_letter[letter][:AGENCIES_PER_LETTER])

        logger.info(f"Total agencies selected: {len(selected)}")
        for letter in TARGET_LETTERS:
            logger.info(f"  {letter}: {len(agencies_by_letter[letter])} agencies")

        self.agencies = selected
        return selected

    async def scrape_open_opportunities(self, agency: Dict) -> Dict:
        """
        Scrape open public opportunities for a single agency

        Args:
            agency: Dict containing agency_name and agency_url

        Returns:
            Dictionary with agency info and list of opportunities
        """
        agency_name = agency["agency_name"]
        agency_url = agency["agency_url"]

        result = {
            "Agency Open Public Opportunity Url": f"{agency_url}/portal/?tab=openOpportunities",
            "Agency Name": agency_name,
            "Agency Open Public Opportunities": []
        }

        api_url = f"{agency_url}/PublicPortal/getOpenPublicOpportunitiesSectionData"

        for attempt in range(MAX_RETRIES):
            try:
                await self.tab.go_to(api_url)
                page_content = await self.tab.page_source

                json_data = extract_json_from_page(page_content)

                if not json_data:
                    logger.debug(f"No data found for {agency_name} (attempt {attempt+1})")
                    continue

                projects = json_data.get("payload", {}).get("projects", {})
                opportunities = []

                # Handle both dict and list formats from API
                if isinstance(projects, dict):
                    project_items = projects.values()
                elif isinstance(projects, list):
                    project_items = projects
                else:
                    project_items = []

                for proj_data in project_items:
                    if not isinstance(proj_data, dict):
                        continue

                    opp = {
                        "Status": "Open",
                        "Refference": proj_data.get("ReferenceID", ""),
                        "Project Name": proj_data.get("ProjectName", ""),
                        "Closed Date": proj_data.get("DateClose", ""),
                        "Number of days Left": 0
                    }

                    if opp["Closed Date"]:
                        opp["Number of days Left"] = calculate_days_remaining(opp["Closed Date"])

                    opportunities.append(opp)

                result["Agency Open Public Opportunities"] = opportunities
                break

            except Exception as e:
                logger.debug(f"Error scraping open opps for {agency_name}: {e}")

        return result

    async def scrape_past_opportunities(self, agency: Dict) -> Dict:
        """
        Scrape past public opportunities for a single agency

        Args:
            agency: Dict containing agency_name and agency_url

        Returns:
            Dictionary with agency info and list of past opportunities
        """
        agency_name = agency["agency_name"]
        agency_url = agency["agency_url"]

        result = {
            "Agency Past Public Opportunity Url": f"{agency_url}/portal/?tab=pastOpportunities",
            "Agency Name": agency_name,
            "Agency Past Public Opportunities": []
        }

        api_url = f"{agency_url}/PublicPortal/getPastPublicOpportunitiesSectionData"

        for attempt in range(MAX_RETRIES):
            try:
                await self.tab.go_to(api_url)
                page_content = await self.tab.page_source

                json_data = extract_json_from_page(page_content)

                if not json_data:
                    logger.debug(f"No past data for {agency_name} (attempt {attempt+1})")
                    continue

                projects = json_data.get("payload", {}).get("projects", {})
                opportunities = []

                # Status mapping based on ProjectSubStatusID
                status_map = {
                    "1": "Closed",
                    "2": "Cancelled",
                    "3": "Awarded"
                }

                # Handle both dict and list formats from API
                if isinstance(projects, dict):
                    project_items = projects.values()
                elif isinstance(projects, list):
                    project_items = projects
                else:
                    project_items = []

                for proj_data in project_items:
                    if not isinstance(proj_data, dict):
                        continue

                    status_id = str(proj_data.get("ProjectSubStatusID", ""))

                    opp = {
                        "Status": status_map.get(status_id, "Unknown"),
                        "Refference": proj_data.get("ReferenceID", ""),
                        "Project Name": proj_data.get("ProjectName", ""),
                        "Closed Date": proj_data.get("DateClose", "")
                    }
                    opportunities.append(opp)

                result["Agency Past Public Opportunities"] = opportunities
                break

            except Exception as e:
                logger.debug(f"Error scraping past opps for {agency_name}: {e}")

        return result

    async def scrape_all_opportunities(self) -> Tuple[List, List]:
        """
        Scrape both open and past opportunities for all agencies

        Returns:
            Tuple of (open_opportunities_list, past_opportunities_list)
        """
        open_opps = []
        past_opps = []

        for idx, agency in enumerate(self.agencies, 1):
            logger.info(f"Scraping agency {idx}/{len(self.agencies)}: {agency['agency_name']}")

            # Get open opportunities
            open_data = await self.scrape_open_opportunities(agency)
            open_opps.append(open_data)

            # Get past opportunities
            past_data = await self.scrape_past_opportunities(agency)
            past_opps.append(past_data)

            # Save progress after each agency (in case of crash)
            self._save_progress(open_opps, past_opps)

            await asyncio.sleep(REQUEST_DELAY)

        return open_opps, past_opps

    def _save_progress(self, open_opps: List, past_opps: List):
        """Save current scraping progress to files"""
        os.makedirs(RAW_OUTPUT_DIR, exist_ok=True)

        open_path = os.path.join(RAW_OUTPUT_DIR, OPEN_OPPORTUNITIES_RAW)
        past_path = os.path.join(RAW_OUTPUT_DIR, PAST_OPPORTUNITIES_RAW)

        with open(open_path, "w", encoding="utf-8") as f:
            json.dump(open_opps, f, ensure_ascii=False, indent=2)

        with open(past_path, "w", encoding="utf-8") as f:
            json.dump(past_opps, f, ensure_ascii=False, indent=2)

    def save_agencies(self):
        """Save the list of scraped agencies to file"""
        os.makedirs(RAW_OUTPUT_DIR, exist_ok=True)
        path = os.path.join(RAW_OUTPUT_DIR, AGENCIES_FILE)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.agencies, f, ensure_ascii=False, indent=4)

        logger.info(f"Saved {len(self.agencies)} agencies to {path}")

    async def run(self) -> Tuple[List, List]:
        """
        Main execution flow for the scraper

        Returns:
            Tuple of (open_opportunities, past_opportunities)
        """
        try:
            await self.start_browser()

            if not await self.login():
                raise Exception("Failed to authenticate with Bonfire Hub")

            await self.fetch_agencies()
            self.save_agencies()

            if not self.agencies:
                logger.warning("No agencies found to scrape")
                return [], []

            open_opps, past_opps = await self.scrape_all_opportunities()

            logger.info(f"Scraping complete! Open: {len(open_opps)}, Past: {len(past_opps)}")
            return open_opps, past_opps

        finally:
            await self.close_browser()


async def main():
    """Entry point for running the scraper standalone"""
    setup_logging()

    # Get credentials from environment or prompt
    email = BONFIRE_EMAIL or os.getenv("BONFIRE_EMAIL")
    password = BONFIRE_PASSWORD or os.getenv("BONFIRE_PASSWORD")

    if not email or not password:
        print("Error: Please set BONFIRE_EMAIL and BONFIRE_PASSWORD environment variables")
        print("Or update them in config/settings.py")
        return

    scraper = BonfireScraper(email, password)
    open_opps, past_opps = await scraper.run()

    print(f"\nScraping completed!")
    print(f"Open opportunities: {len(open_opps)} agencies")
    print(f"Past opportunities: {len(past_opps)} agencies")


if __name__ == "__main__":
    asyncio.run(main())
