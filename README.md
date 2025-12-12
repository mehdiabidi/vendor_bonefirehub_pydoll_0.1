# Bonfire Hub Opportunities Scraper

A Python-based web scraper for extracting bidding opportunities from the Bonfire Hub vendor portal (https://vendor.bonfirehub.com/). This tool collects both open and past public opportunities from government agencies and prepares the data for MongoDB storage.

## Table of Contents

- [Overview](#overview)
- [Website Discovery](#website-discovery)
- [Project Structure](#project-structure)
- [Requirements](#requirements)
- [Installation](#installation)
- [Configuration](#configuration)
- [Running the Scraper](#running-the-scraper)
- [Docker Deployment](#docker-deployment)
- [Output Data Format](#output-data-format)
- [Technical Approach](#technical-approach)
- [Assumptions](#assumptions)
- [Troubleshooting](#troubleshooting)

## Overview

This scraper performs the following tasks:

1. **Authentication**: Logs into the Bonfire Hub portal using provided credentials
2. **Agency Collection**: Fetches agencies filtered by starting letters (D, G, J, L) - 5 agencies per letter
3. **Data Extraction**: Scrapes both "Open Public Opportunities" and "Past Public Opportunities" for each agency
4. **Data Processing**: Cleans and structures the raw data into MongoDB-ready format
5. **Database Storage**: Uploads processed data to MongoDB with deduplication support

### Scraped Data Fields

For each opportunity, the following information is extracted:

| Field | Description |
|-------|-------------|
| Organization Name | The agency that announced the bid/opportunity |
| Bidding ID | Unique identifier assigned to the project |
| Opportunity Name | Title of the project or bid |
| Description | Project overview and details |
| Application Instructions | URL where bidders can submit proposals |
| Deadline | Due date for proposal submission |
| Status | Open, Closed, Awarded, or Cancelled |

## Website Discovery

### Understanding Bonfire Hub Structure

Bonfire Hub is a procurement platform used by government agencies to post bidding opportunities. The website has the following structure:

- **Main Portal**: https://vendor.bonfirehub.com/
- **Login Page**: https://account.bonfirehub.com/login
- **Agency Pages**: Each agency has its own subdomain (e.g., https://dart.bonfirehub.com/)
- **Opportunities Tabs**: Each agency portal has "Open Public Opportunities" and "Past Public Opportunities" tabs

### API Endpoints Discovered

During development, I identified the following API endpoints that the website uses internally:

1. **Organization Search API**:
   - URL: `https://common-production-api-global.bonfirehub.com/v1.0/organizations/searchByLocation`
   - Used to: Fetch list of all registered agencies
   - Pagination: Supports `page` and `limit` parameters

2. **Open Opportunities API** (per agency):
   - URL Pattern: `{agency_url}/PublicPortal/getOpenPublicOpportunitiesSectionData`
   - Returns: JSON with currently active bidding opportunities

3. **Past Opportunities API** (per agency):
   - URL Pattern: `{agency_url}/PublicPortal/getPastPublicOpportunitiesSectionData`
   - Returns: JSON with historical (closed/awarded) opportunities

These internal APIs return JSON data, which made the scraping process more reliable compared to parsing HTML.

## Project Structure

```
bonfire-scraper/
├── main.py                 # Main entry point - orchestrates full pipeline
├── requirements.txt        # Python dependencies
├── Dockerfile             # Docker image configuration
├── docker-compose.yml     # Docker Compose setup with MongoDB
├── .env.example           # Environment variables template
├── README.md              # This documentation
│
├── config/
│   └── settings.py        # Configuration parameters
│
├── src/
│   ├── __init__.py
│   ├── scraper.py         # Main scraping logic using Pydoll
│   ├── data_parser.py     # Data cleaning and transformation
│   └── db_handler.py      # MongoDB operations
│
├── output/
│   ├── raw/               # Raw scraped JSON files
│   │   ├── agencies.json
│   │   ├── open_opportunities_raw.json
│   │   └── past_opportunities_raw.json
│   └── cleaned/           # Processed MongoDB-ready files
│       ├── open_opportunities_clean.json
│       └── past_opportunities_clean.json
│
└── logs/
    └── scraper.log        # Detailed execution logs
```

## Requirements

- Python 3.9 or higher
- Google Chrome browser (for Pydoll/headless browsing)
- MongoDB (optional, for database storage)
- Docker & Docker Compose (optional, for containerized deployment)

## Installation

### Option 1: Local Installation

1. Clone or extract the project:
```bash
cd bonfire-scraper
```

2. Create a virtual environment (recommended):
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Set up configuration:
```bash
cp .env.example .env
# Edit .env with your Bonfire Hub credentials
```

### Option 2: Docker Installation

1. Make sure Docker and Docker Compose are installed

2. Create environment file:
```bash
cp .env.example .env
# Edit .env with your credentials
```

3. Build and run:
```bash
docker-compose up --build
```

## Configuration

### Environment Variables

Create a `.env` file with the following variables:

```env
# Required - Your Bonfire Hub account
BONFIRE_EMAIL=your_email@example.com
BONFIRE_PASSWORD=your_password

# Optional - MongoDB connection (defaults to localhost)
MONGO_URI=mongodb://localhost:27017
```

### Configuration File (config/settings.py)

You can also modify scraping parameters in `config/settings.py`:

```python
# Number of agencies to scrape per letter
AGENCIES_PER_LETTER = 5

# Target letters for agency filtering
TARGET_LETTERS = ["D", "G", "J", "L"]

# Delay between requests (seconds)
REQUEST_DELAY = 1.5
```

## Running the Scraper

### Full Pipeline

Run the complete scraping, parsing, and upload workflow:

```bash
python main.py
```

### Individual Steps

```bash
# Only scrape data (no parsing or upload)
python main.py --scrape-only

# Only parse existing raw data
python main.py --parse-only

# Only upload cleaned data to MongoDB
python main.py --upload-only
```

### With Credentials as Arguments

```bash
python main.py --email your@email.com --password yourpassword
```

## Docker Deployment

### Quick Start

```bash
# Build and start scraper with MongoDB
docker-compose up --build

# Run in background
docker-compose up -d --build
```

### View Logs

```bash
docker-compose logs -f scraper
```

### With MongoDB Admin UI

```bash
# Start with Mongo Express web interface
docker-compose --profile admin up
```

Access Mongo Express at http://localhost:8081 (admin/admin123)

### Stop Services

```bash
docker-compose down
```

### Data Persistence

Scraped data is persisted in mounted volumes:
- `./output/` - Contains JSON output files
- `./logs/` - Contains log files
- Docker volume `bonfire-mongodb-data` - MongoDB data

## Output Data Format

### Raw Data (output/raw/)

The raw scraped data maintains the original structure from the website:

```json
{
  "Agency Open Public Opportunity Url": "https://dart.bonfirehub.com/portal/?tab=openOpportunities",
  "Agency Name": "Dallas Area Rapid Transit",
  "Agency Open Public Opportunities": [
    {
      "Status": "Open",
      "Refference": "2096154",
      "Project Name": "BOLT, 1/2-13 X 4, GRADE 8",
      "Closed Date": "2025-12-11 20:00:00",
      "Number of days Left": 5
    }
  ]
}
```

### Cleaned Data (output/cleaned/)

Processed data ready for MongoDB insertion:

```json
{
  "organization_name": "Dallas Area Rapid Transit",
  "bidding_id": "2096154",
  "opportunity_name": "BOLT, 1/2-13 X 4, GRADE 8",
  "description": "BOLT, 1/2-13 X 4, GRADE 8",
  "application_instructions": {
    "url": "https://dart.bonfirehub.com/portal/?tab=openOpportunities",
    "method": "Submit proposal through Bonfire Hub portal"
  },
  "deadline": {
    "raw": "2025-12-11 20:00:00",
    "iso_format": "2025-12-11T20:00:00",
    "readable": "December 11, 2025 at 08:00 PM",
    "has_passed": false
  },
  "status": "Open",
  "days_remaining": 5,
  "_document_id": "abc123...",
  "_source_url": "https://dart.bonfirehub.com",
  "_scraped_at": "2025-12-12T10:30:00",
  "_opportunity_type": "open"
}
```

## Technical Approach

### Why Pydoll?

As required by the task specification, this scraper uses **Pydoll** (https://pydoll.tech/) for web scraping. Pydoll provides:

- Async browser automation with Chrome/Chromium
- Built-in handling for dynamic JavaScript content
- Clean API for element selection and interaction
- Support for both headed and headless modes

### Scraping Strategy

1. **Authentication Flow**:
   - Navigate to login page
   - Enter email, click continue
   - Wait for password field to appear
   - Enter password and submit
   - Wait for login completion

2. **Agency Collection**:
   - Query the organization search API
   - Filter agencies by starting letters (D, G, J, L)
   - Collect 5 agencies per letter (20 total)

3. **Opportunity Extraction**:
   - For each agency, hit the internal JSON API endpoints
   - Extract opportunity data from the JSON response
   - Handle missing fields gracefully (null values)

4. **Data Processing**:
   - Clean HTML entities from text
   - Parse and normalize date formats
   - Generate unique document IDs for deduplication
   - Structure data for MongoDB

### Rate Limiting Considerations

The scraper includes delays between requests to avoid triggering rate limits. If you experience blocking, you can:

1. Increase `REQUEST_DELAY` in settings
2. Add proxy rotation (not implemented in base version)
3. Add random user-agent rotation

## Assumptions

1. **Account Access**: You have a valid Bonfire Hub account created at https://vendor.bonfirehub.com/

2. **Agency Selection**: The 20 agencies are selected based on the first letter of their name (D, G, J, L - 5 each). The selection is done in order of appearance from the API, not randomly.

3. **Description Field**: Since detailed project descriptions require navigating to individual project pages (which would significantly increase scraping time), the "opportunity_name" is used as the description. Full descriptions could be added with additional scraping logic.

4. **Application URL**: The application URL points to the agency's opportunities tab where users can find and apply for specific opportunities. Direct application links require additional page scraping.

5. **MongoDB Optional**: The scraper works without MongoDB - all data is saved to JSON files. MongoDB upload is an additional step.

6. **Chrome Required**: Pydoll requires Chrome/Chromium browser to be installed.

## Troubleshooting

### Common Issues

**"Could not find email input field"**
- The login page structure may have changed
- Try running in headed mode (set `HEADLESS_MODE = False` in settings)
- Check if you're being blocked by CAPTCHA

**"Failed to connect to MongoDB"**
- Ensure MongoDB is running
- Check MONGO_URI configuration
- Try: `docker-compose up mongodb` if using Docker

**"No agencies found"**
- Login may have failed silently
- Check the log file for details
- Verify your credentials are correct

**Empty opportunities for some agencies**
- Some agencies may not have any current opportunities
- This is normal behavior - not all agencies have active bids

### Enabling Debug Logs

Detailed logs are written to `logs/scraper.log`. For more verbose console output:

```python
# In config/settings.py
LOG_LEVEL = "DEBUG"
```

### Running in Headed Mode (Visible Browser)

For debugging, you can watch the browser actions:

```python
# In config/settings.py
HEADLESS_MODE = False
```

## License

This project is provided as-is for educational and evaluation purposes.

---

*Last updated: December 2025*
