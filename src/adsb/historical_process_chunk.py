#!/usr/bin/env python3
"""Process a single date chunk for historical ADS-B data."""

import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

# Add parent directory to path for imports when run from repo root
sys.path.insert(0, str(Path(__file__).parent))


def process_chunk(start_date: str, end_date: str, output_dir: Path) -> Path | None:
    """Process a date range and output compressed CSV.
    
    Args:
        start_date: Start date in YYYY-MM-DD format
        end_date: End date in YYYY-MM-DD format
        output_dir: Directory to write output CSV
        
    Returns:
        Path to output CSV, or None if no data
    """
    from compress_adsb_to_aircraft_data import (
        load_historical_for_day,
        deduplicate_by_signature,
    )
    import polars as pl
    
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    
    total_days = (end - start).days + 1
    print(f"Processing {total_days} days [{start_date}, {end_date}]")
    
    dfs: list[pl.DataFrame] = []
    current_date = start
    
    while current_date <= end:
        day_str = current_date.strftime("%Y-%m-%d")
        print(f"  Loading {day_str}...")
        
        try:
            df_compressed = load_historical_for_day(current_date)
            if df_compressed.height > 0:
                dfs.append(df_compressed)
                total_rows = sum(df.height for df in dfs)
                print(f"  +{df_compressed.height} rows (total: {total_rows})")
        except Exception as e:
            print(f"  Warning: Failed to load {day_str}: {e}")
        
        current_date += timedelta(days=1)
    
    if not dfs:
        print("No data found for this chunk")
        return None
    
    df_accumulated = pl.concat(dfs)
    df_accumulated = deduplicate_by_signature(df_accumulated)
    print(f"After dedup: {df_accumulated.height} rows")
    
    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"chunk_{start_date}_{end_date}.csv"
    df_accumulated.write_csv(output_path)
    print(f"Wrote {output_path}")
    
    return output_path


def main() -> None:
    """Main entry point for GitHub Actions."""
    start_date = os.environ.get("CHUNK_START_DATE")
    end_date = os.environ.get("CHUNK_END_DATE")
    
    if not start_date or not end_date:
        print("ERROR: CHUNK_START_DATE and CHUNK_END_DATE must be set", file=sys.stderr)
        sys.exit(1)
    
    # Output to repo root data/chunks (script runs from src/adsb)
    repo_root = Path(__file__).parent.parent.parent
    output_dir = repo_root / "data" / "chunks"
    result = process_chunk(start_date, end_date, output_dir)
    
    if result is None:
        print("No data produced for this chunk")
        sys.exit(0)


if __name__ == "__main__":
    main()
