#!/usr/bin/env python3
"""
Optional Scheduler for Bonfire Hub Scraper

This module provides a simple scheduling mechanism to run the scraper
at regular intervals. Can be used as an alternative to cron jobs.

Usage:
    python scheduler.py                    # Run every 24 hours (default)
    python scheduler.py --interval 12      # Run every 12 hours
    python scheduler.py --run-once         # Run once and exit

For cron-based scheduling, add to crontab:
    # Run daily at 6 AM
    0 6 * * * cd /path/to/scraper && python main.py >> logs/cron.log 2>&1

For Airflow integration, see the example DAG below in comments.
"""

import os
import sys
import time
import asyncio
import argparse
import logging
from datetime import datetime, timedelta

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def setup_scheduler_logging():
    """Configure logging for the scheduler"""
    os.makedirs("logs", exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("logs/scheduler.log"),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger("scheduler")


async def run_scraper_job():
    """Execute the scraper as an async job"""
    from main import run_scraper, run_parser, run_upload
    from config.settings import BONFIRE_EMAIL, BONFIRE_PASSWORD

    logger = logging.getLogger("scheduler")

    try:
        logger.info("Starting scheduled scraper job")

        # Run scraper
        await run_scraper(BONFIRE_EMAIL, BONFIRE_PASSWORD)

        # Run parser
        run_parser()

        # Run upload
        run_upload()

        logger.info("Scheduled job completed successfully")
        return True

    except Exception as e:
        logger.exception(f"Scheduled job failed: {e}")
        return False


def calculate_next_run(interval_hours: int) -> datetime:
    """Calculate the next scheduled run time"""
    return datetime.now() + timedelta(hours=interval_hours)


def main():
    parser = argparse.ArgumentParser(description="Scheduler for Bonfire Hub Scraper")
    parser.add_argument("--interval", type=int, default=24,
                        help="Interval in hours between runs (default: 24)")
    parser.add_argument("--run-once", action="store_true",
                        help="Run once and exit")

    args = parser.parse_args()

    logger = setup_scheduler_logging()

    print("""
    ╔═══════════════════════════════════════════════════════╗
    ║       Bonfire Hub Scraper - Scheduler                 ║
    ╚═══════════════════════════════════════════════════════╝
    """)

    if args.run_once:
        logger.info("Running single execution mode")
        asyncio.run(run_scraper_job())
        return

    logger.info(f"Starting scheduler with {args.interval} hour interval")

    while True:
        try:
            # Run the job
            asyncio.run(run_scraper_job())

            # Calculate and display next run time
            next_run = calculate_next_run(args.interval)
            logger.info(f"Next scheduled run: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")

            # Sleep until next run
            time.sleep(args.interval * 3600)

        except KeyboardInterrupt:
            logger.info("Scheduler stopped by user")
            break
        except Exception as e:
            logger.exception(f"Scheduler error: {e}")
            # Wait 5 minutes before retrying after error
            time.sleep(300)


if __name__ == "__main__":
    main()


# ============================================================
# EXAMPLE: Apache Airflow DAG Configuration
# ============================================================
#
# If using Airflow, create a file: dags/bonfire_scraper_dag.py
#
# from datetime import datetime, timedelta
# from airflow import DAG
# from airflow.operators.bash import BashOperator
#
# default_args = {
#     'owner': 'airflow',
#     'depends_on_past': False,
#     'email_on_failure': False,
#     'email_on_retry': False,
#     'retries': 1,
#     'retry_delay': timedelta(minutes=5),
# }
#
# dag = DAG(
#     'bonfire_hub_scraper',
#     default_args=default_args,
#     description='Scrape bidding opportunities from Bonfire Hub',
#     schedule_interval=timedelta(days=1),
#     start_date=datetime(2025, 1, 1),
#     catchup=False,
# )
#
# scrape_task = BashOperator(
#     task_id='run_scraper',
#     bash_command='cd /path/to/scraper && python main.py',
#     dag=dag,
# )
