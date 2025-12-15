#!/usr/bin/env python3
"""
Bonfire Hub Opportunities Scraper - Main Entry Point

This script orchestrates the full scraping pipeline:
1. Authenticate with Bonfire Hub portal
2. Scrape opportunities from 20 agencies (5 each for D, G, J, L)
3. Parse and clean the raw data
4. Upload to MongoDB (optional)

Usage:
    python main.py                  # Run full pipeline
    python main.py --scrape-only   # Only scrape, don't upload to DB
    python main.py --parse-only    # Only parse existing raw data
    python main.py --upload-only   # Only upload cleaned data to DB

Environment variables (or set in config/settings.py):
    BONFIRE_EMAIL    - Your Bonfire Hub account email
    BONFIRE_PASSWORD - Your Bonfire Hub account password
    MONGO_URI        - MongoDB connection string (optional)
"""

import os
import sys
import asyncio
import argparse
import logging
from datetime import datetime

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.scraper import BonfireScraper, setup_logging
from src.data_parser import DataParser
from src.db_handler import MongoHandler, MONGO_DB_OPEN, MONGO_DB_PAST

try:
    from config.settings import BONFIRE_EMAIL, BONFIRE_PASSWORD, MONGO_URI
except ImportError:
    BONFIRE_EMAIL = os.getenv("BONFIRE_EMAIL", "")
    BONFIRE_PASSWORD = os.getenv("BONFIRE_PASSWORD", "")
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")


logger = logging.getLogger("main")

# Suppress verbose logs from libraries
logging.getLogger("pymongo").setLevel(logging.DEBUG)
logging.getLogger("urllib3").setLevel(logging.DEBUG)


def print_banner():
    """Print application banner"""
    banner = """
    ╔══════════════════════════════════════════════════════════╗
    ║     Bonfire Hub Opportunities Scraper v1.0               ║
    ║     Extracts bidding opportunities from 20 agencies      ║
    ╚══════════════════════════════════════════════════════════╝
    """
    print(banner)


async def run_scraper(email: str, password: str) -> bool:
    """
    Execute the scraping phase

    Args:
        email: Bonfire Hub login email
        password: Bonfire Hub login password

    Returns:
        True if scraping completed successfully
    """
    print("\n[1/3] Starting scraper...")
    print("-" * 40)

    scraper = BonfireScraper(email, password)
    try:
        open_opps, past_opps = await scraper.run()

        if open_opps or past_opps:
            print(f"  Scraped data from {len(open_opps)} agencies")

            # Count total opportunities
            total_open = sum(len(a.get("Agency Open Public Opportunities", [])) for a in open_opps)
            total_past = sum(len(a.get("Agency Past Public Opportunities", [])) for a in past_opps)

            print(f"  Total open opportunities: {total_open}")
            print(f"  Total past opportunities: {total_past}")
            return True
        else:
            print("  Warning: No data scraped")
            return False

    except Exception as e:
        logger.exception(f"Scraping failed: {e}")
        print(f"  Error: {e}")
        return False


def run_parser() -> bool:
    """
    Execute the data parsing phase

    Returns:
        True if parsing completed successfully
    """
    print("\n[2/3] Parsing and cleaning data...")
    print("-" * 40)

    try:
        parser = DataParser()
        open_clean, past_clean = parser.run()

        print(f"  Cleaned open opportunities: {len(open_clean)}")
        print(f"  Cleaned past opportunities: {len(past_clean)}")
        return True

    except Exception as e:
        logger.exception(f"Parsing failed: {e}")
        print(f"  Error: {e}")
        return False


def run_upload() -> bool:
    """
    Execute the database upload phase

    Returns:
        True if upload completed successfully
    """
    print("\n[3/3] Uploading to MongoDB...")
    print("-" * 40)

    try:
        handler = MongoHandler()

        if not handler.connect():
            print("  Failed to connect to MongoDB")
            print("  Skipping database upload - data saved to JSON files")
            return False

        # Load cleaned data
        import json

        open_file = "output/cleaned/open_opportunities_clean.json"
        past_file = "output/cleaned/past_opportunities_clean.json"

        # Upload open opportunities
        if os.path.exists(open_file):
            with open(open_file, "r", encoding="utf-8") as f:
                open_data = json.load(f)
            result = handler.insert_opportunities(MONGO_DB_OPEN, open_data)
            print(f"  Open opportunities - Inserted: {result['inserted']}, Skipped: {result['skipped']}")

        # Upload past opportunities
        if os.path.exists(past_file):
            with open(past_file, "r", encoding="utf-8") as f:
                past_data = json.load(f)
            result = handler.insert_opportunities(MONGO_DB_PAST, past_data)
            print(f"  Past opportunities - Inserted: {result['inserted']}, Skipped: {result['skipped']}")

        handler.disconnect()
        return True

    except Exception as e:
        logger.exception(f"Upload failed: {e}")
        print(f"  Error: {e}")
        return False


async def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(
        description="Bonfire Hub Opportunities Scraper",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python main.py                    Run complete pipeline
  python main.py --scrape-only      Only run the scraper
  python main.py --parse-only       Only parse existing raw data
  python main.py --upload-only      Only upload to MongoDB
        """
    )

    parser.add_argument("--scrape-only", action="store_true",
                        help="Only run scraper, skip parsing and upload")
    parser.add_argument("--parse-only", action="store_true",
                        help="Only parse existing raw data")
    parser.add_argument("--upload-only", action="store_true",
                        help="Only upload cleaned data to MongoDB")
    parser.add_argument("--email", type=str, help="Bonfire Hub email")
    parser.add_argument("--password", type=str, help="Bonfire Hub password")

    args = parser.parse_args()

    print_banner()
    setup_logging()

    start_time = datetime.now()

    # Get credentials
    email = args.email or BONFIRE_EMAIL or os.getenv("BONFIRE_EMAIL")
    password = args.password or BONFIRE_PASSWORD or os.getenv("BONFIRE_PASSWORD")

    # Determine which phases to run
    do_scrape = not (args.parse_only or args.upload_only)
    do_parse = not (args.scrape_only or args.upload_only)
    do_upload = not (args.scrape_only or args.parse_only)

    # Check credentials if scraping
    if do_scrape and (not email or not password):
        print("Error: Bonfire Hub credentials not provided")
        print("Set BONFIRE_EMAIL and BONFIRE_PASSWORD environment variables")
        print("Or pass --email and --password arguments")
        sys.exit(1)

    success = True

    # Run selected phases
    if do_scrape:
        success = await run_scraper(email, password) and success

    if do_parse:
        success = run_parser() and success

    if do_upload:
        success = run_upload() and success

    # Summary
    elapsed = datetime.now() - start_time
    print("\n" + "=" * 50)
    print(f"Pipeline completed in {elapsed.total_seconds():.1f} seconds")

    if success:
        print("Status: SUCCESS")
        print("\nOutput files:")
        print("  - output/raw/open_opportunities_raw.json")
        print("  - output/raw/past_opportunities_raw.json")
        print("  - output/cleaned/open_opportunities_clean.json")
        print("  - output/cleaned/past_opportunities_clean.json")
    else:
        print("Status: COMPLETED WITH ERRORS")
        print("Check logs/scraper.log for details")

    print("=" * 50)


if __name__ == "__main__":
    asyncio.run(main())
