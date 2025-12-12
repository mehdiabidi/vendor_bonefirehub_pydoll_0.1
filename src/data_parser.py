"""
Data Parser and Cleaner for Bonfire Hub Scraper

This module reads raw scraped JSON data and transforms it into
clean, structured format ready for MongoDB insertion.

Fields extracted and mapped:
- Organization Name: Agency that announced the opportunity
- Bidding ID: Unique identifier for the project/bid
- Name of Opportunity: Title of the project
- Description of Opportunity: Project overview/details
- Application Instructions: URL where bidders can submit proposals
- Deadline: Due date for proposal submission
"""

import json
import os
import hashlib
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any

# Setup logger
logger = logging.getLogger("data_parser")


def setup_parser_logging():
    """Configure logging for parser module"""
    if not logger.handlers:
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler()
        ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logger.addHandler(ch)


class DataParser:
    """
    Parser class to clean and structure scraped opportunity data

    Transforms raw JSON from scraper into MongoDB-ready documents
    with consistent field naming and proper handling of missing values.
    """

    def __init__(self, raw_data_dir: str = "output/raw", clean_data_dir: str = "output/cleaned"):
        self.raw_data_dir = raw_data_dir
        self.clean_data_dir = clean_data_dir

    def generate_document_id(self, org_name: str, bidding_id: str) -> str:
        """
        Generate a unique document ID based on org name and bidding ID

        This helps with deduplication - same opportunity won't be inserted twice
        """
        combined = f"{org_name}_{bidding_id}".lower().strip()
        return hashlib.md5(combined.encode()).hexdigest()

    def clean_html_entities(self, text: str) -> str:
        """Remove common HTML entities from text"""
        if not text:
            return text

        replacements = {
            "&amp;": "&",
            "&lt;": "<",
            "&gt;": ">",
            "&quot;": '"',
            "&#39;": "'",
            "&nbsp;": " ",
            "\\u00a0": " "
        }

        for entity, char in replacements.items():
            text = text.replace(entity, char)

        return text.strip()

    def parse_deadline(self, date_str: str) -> Dict[str, Any]:
        """
        Parse deadline string into structured format

        Args:
            date_str: Date in format 'YYYY-MM-DD HH:MM:SS'

        Returns:
            Dict with original string, ISO format, and readable format
        """
        result = {
            "raw": date_str,
            "iso_format": None,
            "readable": None,
            "has_passed": False
        }

        if not date_str:
            return result

        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d %H:%M:%S")
            result["iso_format"] = dt.isoformat()
            result["readable"] = dt.strftime("%B %d, %Y at %I:%M %p")
            result["has_passed"] = dt < datetime.now()
        except ValueError:
            logger.debug(f"Could not parse date: {date_str}")

        return result

    def parse_open_opportunity(self, raw_opp: Dict, agency_name: str, agency_url: str) -> Dict:
        """
        Transform a single open opportunity into clean MongoDB document

        Args:
            raw_opp: Raw opportunity dict from scraper
            agency_name: Name of the agency
            agency_url: Base URL of agency portal

        Returns:
            Cleaned and structured opportunity document
        """
        bidding_id = raw_opp.get("Refference", "") or raw_opp.get("Reference", "")
        project_name = self.clean_html_entities(raw_opp.get("Project Name", ""))

        # Construct application URL (where vendors submit proposals)
        # This points to the agency's open opportunities tab
        application_url = f"{agency_url}/portal/?tab=openOpportunities"

        clean_doc = {
            # Required fields as per specification
            "organization_name": agency_name,
            "bidding_id": bidding_id,
            "opportunity_name": project_name,
            "description": project_name,  # Using project name as description since detailed desc requires additional page scraping
            "application_instructions": {
                "url": application_url,
                "method": "Submit proposal through Bonfire Hub portal"
            },
            "deadline": self.parse_deadline(raw_opp.get("Closed Date", "")),

            # Additional useful fields
            "status": raw_opp.get("Status", "Open"),
            "days_remaining": raw_opp.get("Number of days Left", 0),

            # Metadata for database operations
            "_document_id": self.generate_document_id(agency_name, bidding_id),
            "_source_url": agency_url,
            "_scraped_at": datetime.now().isoformat(),
            "_opportunity_type": "open"
        }

        return clean_doc

    def parse_past_opportunity(self, raw_opp: Dict, agency_name: str, agency_url: str) -> Dict:
        """
        Transform a single past opportunity into clean MongoDB document

        Args:
            raw_opp: Raw opportunity dict from scraper
            agency_name: Name of the agency
            agency_url: Base URL of agency portal

        Returns:
            Cleaned and structured opportunity document
        """
        bidding_id = raw_opp.get("Refference", "") or raw_opp.get("Reference", "")
        project_name = self.clean_html_entities(raw_opp.get("Project Name", ""))

        application_url = f"{agency_url}/portal/?tab=pastOpportunities"

        clean_doc = {
            "organization_name": agency_name,
            "bidding_id": bidding_id,
            "opportunity_name": project_name,
            "description": project_name,
            "application_instructions": {
                "url": application_url,
                "method": "Opportunity closed - historical record only"
            },
            "deadline": self.parse_deadline(raw_opp.get("Closed Date", "")),

            "status": raw_opp.get("Status", "Closed"),

            "_document_id": self.generate_document_id(agency_name, bidding_id),
            "_source_url": agency_url,
            "_scraped_at": datetime.now().isoformat(),
            "_opportunity_type": "past"
        }

        return clean_doc

    def process_open_opportunities(self, raw_data: List[Dict]) -> List[Dict]:
        """
        Process all raw open opportunities data

        Args:
            raw_data: List of agency dictionaries with opportunities

        Returns:
            List of cleaned opportunity documents
        """
        cleaned = []

        for agency_data in raw_data:
            agency_name = agency_data.get("Agency Name", "Unknown")
            agency_url_full = agency_data.get("Agency Open Public Opportunity Url", "")

            # Extract base URL from full URL
            agency_url = agency_url_full.replace("/portal/?tab=openOpportunities", "")

            opportunities = agency_data.get("Agency Open Public Opportunities", [])

            for opp in opportunities:
                try:
                    clean_opp = self.parse_open_opportunity(opp, agency_name, agency_url)
                    cleaned.append(clean_opp)
                except Exception as e:
                    logger.warning(f"Failed to parse opportunity: {e}")

        logger.info(f"Processed {len(cleaned)} open opportunities from {len(raw_data)} agencies")
        return cleaned

    def process_past_opportunities(self, raw_data: List[Dict]) -> List[Dict]:
        """
        Process all raw past opportunities data

        Args:
            raw_data: List of agency dictionaries with past opportunities

        Returns:
            List of cleaned opportunity documents
        """
        cleaned = []

        for agency_data in raw_data:
            agency_name = agency_data.get("Agency Name", "Unknown")
            agency_url_full = agency_data.get("Agency Past Public Opportunity Url", "")

            agency_url = agency_url_full.replace("/portal/?tab=pastOpportunities", "")

            opportunities = agency_data.get("Agency Past Public Opportunities", [])

            for opp in opportunities:
                try:
                    clean_opp = self.parse_past_opportunity(opp, agency_name, agency_url)
                    cleaned.append(clean_opp)
                except Exception as e:
                    logger.warning(f"Failed to parse past opportunity: {e}")

        logger.info(f"Processed {len(cleaned)} past opportunities from {len(raw_data)} agencies")
        return cleaned

    def remove_duplicates(self, opportunities: List[Dict]) -> List[Dict]:
        """
        Remove duplicate opportunities based on document ID

        Args:
            opportunities: List of opportunity documents

        Returns:
            Deduplicated list
        """
        seen_ids = set()
        unique = []

        for opp in opportunities:
            doc_id = opp.get("_document_id", "")
            if doc_id and doc_id not in seen_ids:
                seen_ids.add(doc_id)
                unique.append(opp)

        removed = len(opportunities) - len(unique)
        if removed > 0:
            logger.info(f"Removed {removed} duplicate opportunities")

        return unique

    def load_raw_data(self, filename: str) -> List[Dict]:
        """Load raw JSON data from file"""
        filepath = os.path.join(self.raw_data_dir, filename)

        if not os.path.exists(filepath):
            logger.error(f"Raw data file not found: {filepath}")
            return []

        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)

    def save_cleaned_data(self, data: List[Dict], filename: str):
        """Save cleaned data to JSON file"""
        os.makedirs(self.clean_data_dir, exist_ok=True)
        filepath = os.path.join(self.clean_data_dir, filename)

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        logger.info(f"Saved {len(data)} records to {filepath}")

    def run(self,
            open_raw_file: str = "open_opportunities_raw.json",
            past_raw_file: str = "past_opportunities_raw.json",
            open_clean_file: str = "open_opportunities_clean.json",
            past_clean_file: str = "past_opportunities_clean.json"):
        """
        Main execution to process all raw data files

        Args:
            open_raw_file: Input filename for open opportunities
            past_raw_file: Input filename for past opportunities
            open_clean_file: Output filename for cleaned open opportunities
            past_clean_file: Output filename for cleaned past opportunities

        Returns:
            Tuple of (cleaned_open_opps, cleaned_past_opps)
        """
        setup_parser_logging()

        # Process open opportunities
        logger.info("Processing open opportunities...")
        raw_open = self.load_raw_data(open_raw_file)
        clean_open = self.process_open_opportunities(raw_open)
        clean_open = self.remove_duplicates(clean_open)
        self.save_cleaned_data(clean_open, open_clean_file)

        # Process past opportunities
        logger.info("Processing past opportunities...")
        raw_past = self.load_raw_data(past_raw_file)
        clean_past = self.process_past_opportunities(raw_past)
        clean_past = self.remove_duplicates(clean_past)
        self.save_cleaned_data(clean_past, past_clean_file)

        return clean_open, clean_past


def main():
    """Standalone execution of the data parser"""
    print("=" * 50)
    print("Bonfire Hub Data Parser")
    print("=" * 50)

    parser = DataParser()
    open_opps, past_opps = parser.run()

    print(f"\nParsing complete!")
    print(f"Cleaned open opportunities: {len(open_opps)}")
    print(f"Cleaned past opportunities: {len(past_opps)}")
    print(f"\nOutput files saved to: {parser.clean_data_dir}/")


if __name__ == "__main__":
    main()
