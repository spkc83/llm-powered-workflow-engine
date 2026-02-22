"""Standalone database initialization and seeding.

Usage:
    python -m workflow_engine.database          # Create tables and seed data
    python -m workflow_engine.database --reset   # Delete existing DB, recreate, and seed
"""

import argparse
import asyncio
import sys

from workflow_engine.database.db import DB_PATH, init_db
from workflow_engine.database.seed import seed_all


async def main(reset: bool = False) -> None:
    if reset and DB_PATH.exists():
        DB_PATH.unlink()
        print(f"Deleted existing database: {DB_PATH}")

    await init_db()
    print(f"Initialized database schema: {DB_PATH}")

    await seed_all()
    print("Seeded database with sample data.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Initialize and seed the workflow database.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete the existing database and recreate from scratch.",
    )
    args = parser.parse_args()
    asyncio.run(main(reset=args.reset))
