"""
Meesho Tracker - APScheduler In-Process Daemon
==============================================
Runs in-process daily scheduler with persistent SQLite jobstore and random start jitter.
Also allows Windows Task Scheduler via standalone CLI command.
"""

import logging
import random
import time
from datetime import datetime
from pathlib import Path

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from meesho_tracker.config import load_config
from meesho_tracker.runner import TrackerRunner

logger = logging.getLogger("meesho_tracker.scheduler")


def run_scheduled_job():
    """Triggered by APScheduler daily. Adds 0-30 min randomized jitter."""
    jitter_min = random.uniform(0.0, 30.0)
    logger.info(f"Scheduled job awakened. Applying randomized jitter pause of {jitter_min:.1f} minutes...")
    time.sleep(int(jitter_min * 60))

    runner = TrackerRunner()
    result = runner.run(mode="scheduled")
    logger.info(f"Scheduled daily run complete. Status: {result.get('status')}")


def start_daemon():
    """Starts the in-process blocking APScheduler daemon."""
    config = load_config()

    jobstores = {
        'default': MemoryJobStore()
    }

    scheduler = BlockingScheduler(jobstores=jobstores)

    # Schedule run daily at 02:00 AM local time
    scheduler.add_job(
        run_scheduled_job,
        trigger=CronTrigger(hour=2, minute=0),
        id="meesho_daily_tracker",
        name="Meesho Store Daily Full Scan",
        replace_existing=True,
        misfire_grace_time=3600
    )

    logger.info("APScheduler daemon active. Daily scan scheduled for 02:00 AM with 0-30 min jitter.")
    print("Meesho Tracker Daemon is running. Press Ctrl+C to exit.")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("APScheduler daemon stopped cleanly.")
