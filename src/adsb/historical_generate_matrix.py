#!/usr/bin/env python3
"""Generate date chunk matrix for historical ADS-B processing."""

import json
import os
import sys
from datetime import datetime, timedelta


def generate_chunks(start_date: str, end_date: str, chunk_days: int) -> list[dict]:
    """Generate date chunks for parallel processing.
    
    Args:
        start_date: Start date in YYYY-MM-DD format (inclusive)
        end_date: End date in YYYY-MM-DD format (exclusive)
        chunk_days: Number of days per chunk
        
    Returns:
        List of chunk dictionaries with start_date and end_date (both inclusive within chunk)
    """
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    chunks = []
    current = start
    
    # end_date is exclusive, so we process up to but not including it
    while current < end:
        # chunk_end is inclusive, so subtract 1 from the next chunk start
        chunk_end = min(current + timedelta(days=chunk_days - 1), end - timedelta(days=1))
        chunks.append({
            "start_date": current.strftime("%Y-%m-%d"),
            "end_date": chunk_end.strftime("%Y-%m-%d"),
        })
        current = chunk_end + timedelta(days=1)
    
    return chunks


def main() -> None:
    """Main entry point for GitHub Actions."""
    start_date = os.environ.get("INPUT_START_DATE")
    end_date = os.environ.get("INPUT_END_DATE")
    chunk_days = int(os.environ.get("INPUT_CHUNK_DAYS", "7"))
    
    if not start_date or not end_date:
        print("ERROR: INPUT_START_DATE and INPUT_END_DATE must be set", file=sys.stderr)
        sys.exit(1)
    
    chunks = generate_chunks(start_date, end_date, chunk_days)
    print(f"Generated {len(chunks)} chunks for {start_date} to {end_date}")
    
    # Write to GitHub Actions output
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"chunks={json.dumps(chunks)}\n")
    else:
        # For local testing, just print
        print(json.dumps(chunks, indent=2))


if __name__ == "__main__":
    main()
