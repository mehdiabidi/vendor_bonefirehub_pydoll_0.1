"""
MongoDB Database Handler for Bonfire Hub Scraper

Handles all database operations including:
- Connection management
- Data insertion with deduplication
- Index creation for efficient querying
- Data retrieval
"""

import json
import os
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime

try:
    import pymongo
    from pymongo import MongoClient
    from pymongo.errors import DuplicateKeyError, BulkWriteError
    PYMONGO_AVAILABLE = True
except ImportError:
    PYMONGO_AVAILABLE = False
    print("Warning: pymongo not installed. Database operations will be disabled.")

# Import configuration
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from config.settings import (
        MONGO_URI, MONGO_DB_OPEN, MONGO_DB_PAST, MONGO_COLLECTION
    )
except ImportError:
    MONGO_URI = "mongodb://localhost:27017"
    MONGO_DB_OPEN = "open_public_opportunities"
    MONGO_DB_PAST = "past_public_opportunities"
    MONGO_COLLECTION = "opportunities"


# ============== Database Logger Setup ==============
# Create separate log file for database operations
LOG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
DB_LOG_FILE = os.path.join(LOG_DIR, "db_handler.log")

logger = logging.getLogger("db_handler")
logger.setLevel(logging.DEBUG)

# File handler for database logs
if not logger.handlers:
    file_handler = logging.FileHandler(DB_LOG_FILE, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(file_handler)

    # Console handler for immediate feedback
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(logging.Formatter(
        "%(asctime)s %(levelname)-8s %(message)s",
        datefmt="%H:%M:%S"
    ))
    logger.addHandler(console_handler)

# Suppress pymongo verbose logging
logging.getLogger("pymongo").setLevel(logging.ERROR)


class MongoHandler:
    """
    MongoDB handler class for managing opportunity data

    Provides methods for connecting to MongoDB, inserting data with
    deduplication support, and creating indexes for efficient queries.
    """

    def __init__(self, connection_uri: str = None):
        """
        Initialize MongoDB handler

        Args:
            connection_uri: MongoDB connection string. If not provided,
                           uses MONGO_URI from config.
        """
        if not PYMONGO_AVAILABLE:
            raise ImportError("pymongo is required for database operations")

        self.uri = connection_uri or MONGO_URI
        self.client = None
        self._connected = False

    def connect(self) -> bool:
        """
        Establish connection to MongoDB server

        Returns:
            True if connection successful, False otherwise
        """
        try:
            self.client = MongoClient(self.uri, serverSelectionTimeoutMS=5000)
            # Test connection
            self.client.server_info()
            self._connected = True
            logger.info("Successfully connected to MongoDB")
            return True
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {e}")
            self._connected = False
            return False

    def disconnect(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            self._connected = False
            logger.info("Disconnected from MongoDB")

    def get_database(self, db_name: str):
        """Get reference to a database"""
        if not self._connected:
            self.connect()
        return self.client[db_name]

    def get_collection(self, db_name: str, collection_name: str = None):
        """Get reference to a collection"""
        collection_name = collection_name or MONGO_COLLECTION
        db = self.get_database(db_name)
        return db[collection_name]

    def create_indexes(self, db_name: str):
        """
        Create indexes on the opportunities collection for efficient queries

        Indexes created:
        - _document_id: Unique index for deduplication
        - organization_name: For filtering by agency
        - bidding_id: For looking up specific opportunities
        - deadline.iso_format: For sorting by deadline
        """
        collection = self.get_collection(db_name)

        indexes = [
            ("_document_id", {"unique": True}),
            ("organization_name", {}),
            ("bidding_id", {}),
            ("deadline.iso_format", {}),
            ("status", {})
        ]

        for field, options in indexes:
            try:
                if options.get("unique"):
                    collection.create_index(field, unique=True, background=True)
                else:
                    collection.create_index(field, background=True)
                logger.debug(f"Created index on {field}")
            except Exception as e:
                logger.debug(f"Index on {field} may already exist: {e}")

        logger.info(f"Indexes ensured for {db_name}.{MONGO_COLLECTION}")

    def insert_opportunities(self, db_name: str, opportunities: List[Dict],
                            skip_duplicates: bool = True) -> Dict[str, int]:
        """
        Insert opportunities into MongoDB with deduplication

        Args:
            db_name: Target database name
            opportunities: List of opportunity documents
            skip_duplicates: If True, skip documents that already exist

        Returns:
            Dict with counts of inserted, skipped, and failed documents
        """
        if not opportunities:
            return {"inserted": 0, "skipped": 0, "failed": 0}

        collection = self.get_collection(db_name)
        self.create_indexes(db_name)

        inserted = 0
        skipped = 0
        failed = 0

        for opp in opportunities:
            try:
                # Add insertion timestamp
                opp["_inserted_at"] = datetime.now().isoformat()

                if skip_duplicates:
                    # Use upsert to handle duplicates gracefully
                    result = collection.update_one(
                        {"_document_id": opp.get("_document_id")},
                        {"$setOnInsert": opp},
                        upsert=True
                    )
                    if result.upserted_id:
                        inserted += 1
                    else:
                        skipped += 1
                else:
                    collection.insert_one(opp)
                    inserted += 1

            except DuplicateKeyError:
                skipped += 1
            except Exception as e:
                logger.warning(f"Failed to insert document: {e}")
                failed += 1

        logger.info(f"Database {db_name}: Inserted {inserted}, Skipped {skipped}, Failed {failed}")

        return {"inserted": inserted, "skipped": skipped, "failed": failed}

    def bulk_insert(self, db_name: str, opportunities: List[Dict]) -> Dict[str, int]:
        """
        Bulk insert opportunities (faster but less error handling)

        Args:
            db_name: Target database name
            opportunities: List of opportunity documents

        Returns:
            Dict with insert results
        """
        if not opportunities:
            return {"inserted": 0, "errors": 0}

        collection = self.get_collection(db_name)
        self.create_indexes(db_name)

        # Add timestamps
        for opp in opportunities:
            opp["_inserted_at"] = datetime.now().isoformat()

        try:
            result = collection.insert_many(opportunities, ordered=False)
            return {"inserted": len(result.inserted_ids), "errors": 0}
        except BulkWriteError as e:
            inserted = e.details.get("nInserted", 0)
            errors = len(e.details.get("writeErrors", []))
            logger.warning(f"Bulk insert completed with {errors} errors")
            return {"inserted": inserted, "errors": errors}

    def get_all_records(self, db_name: str) -> List[Dict]:
        """
        Retrieve all opportunities from a database

        Args:
            db_name: Database name to query

        Returns:
            List of opportunity documents
        """
        collection = self.get_collection(db_name)
        records = list(collection.find())

        # Convert ObjectId to string for JSON serialization
        for record in records:
            record["_id"] = str(record["_id"])

        return records

    def get_existing_ids(self, db_name: str) -> set:
        """
        Get set of existing document IDs for deduplication

        Args:
            db_name: Database name

        Returns:
            Set of _document_id values
        """
        collection = self.get_collection(db_name)
        ids = collection.distinct("_document_id")
        return set(ids)

    def filter_new_records(self, db_name: str, opportunities: List[Dict]) -> List[Dict]:
        """
        Filter out opportunities that already exist in database

        Args:
            db_name: Database name to check against
            opportunities: List of opportunities to filter

        Returns:
            List of opportunities not already in database
        """
        existing_ids = self.get_existing_ids(db_name)

        new_records = [
            opp for opp in opportunities
            if opp.get("_document_id") not in existing_ids
        ]

        filtered = len(opportunities) - len(new_records)
        if filtered > 0:
            logger.info(f"Filtered out {filtered} existing records")

        return new_records

    def export_to_json(self, db_name: str, output_file: str):
        """
        Export all records from database to JSON file

        Args:
            db_name: Database to export from
            output_file: Path to output JSON file
        """
        records = self.get_all_records(db_name)

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(records, f, ensure_ascii=False, indent=2)

        logger.info(f"Exported {len(records)} records to {output_file}")


def upload_opportunities(open_data_file: str = None, past_data_file: str = None):
    """
    Convenience function to upload cleaned data to MongoDB

    Args:
        open_data_file: Path to cleaned open opportunities JSON
        past_data_file: Path to cleaned past opportunities JSON
    """
    open_data_file = open_data_file or "output/cleaned/open_opportunities_clean.json"
    past_data_file = past_data_file or "output/cleaned/past_opportunities_clean.json"

    handler = MongoHandler()

    if not handler.connect():
        print("Failed to connect to MongoDB. Check your connection settings.")
        return

    try:
        # Upload open opportunities
        if os.path.exists(open_data_file):
            with open(open_data_file, "r", encoding="utf-8") as f:
                open_data = json.load(f)
            results = handler.insert_opportunities(MONGO_DB_OPEN, open_data)
            print(f"Open opportunities: {results}")
        else:
            print(f"File not found: {open_data_file}")

        # Upload past opportunities
        if os.path.exists(past_data_file):
            with open(past_data_file, "r", encoding="utf-8") as f:
                past_data = json.load(f)
            results = handler.insert_opportunities(MONGO_DB_PAST, past_data)
            print(f"Past opportunities: {results}")
        else:
            print(f"File not found: {past_data_file}")

    finally:
        handler.disconnect()


if __name__ == "__main__":
    print("=" * 50)
    print("MongoDB Upload Utility")
    print("=" * 50)
    upload_opportunities()
