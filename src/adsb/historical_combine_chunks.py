#!/usr/bin/env python3
"""Combine processed chunks into final historical ADS-B release."""

import os
import sys
from pathlib import Path

import polars as pl


def combine_chunks(chunks_dir: Path, output_dir: Path, start_date: str, end_date: str) -> Path:
    """Combine all chunk CSVs into final output.
    
    Args:
        chunks_dir: Directory containing chunk CSV files
        output_dir: Directory to write final output
        start_date: Global start date for filename
        end_date: Global end date for filename
        
    Returns:
        Path to final output CSV
    """
    # Import here to allow script to be run from repo root
    sys.path.insert(0, str(Path(__file__).parent))
    from compress_adsb_to_aircraft_data import deduplicate_by_signature
    
    csv_files = sorted(chunks_dir.glob("**/*.csv"))
    print(f"Found {len(csv_files)} chunk files")
    
    if not csv_files:
        print("ERROR: No chunk files found", file=sys.stderr)
        sys.exit(1)
    
    dfs: list[pl.DataFrame] = []
    for csv_file in csv_files:
        print(f"Loading {csv_file}")
        df = pl.read_csv(csv_file, null_values=[""])
        dfs.append(df)
        print(f"  {df.height} rows")
    
    df_combined = pl.concat(dfs)
    print(f"Combined: {df_combined.height} rows")
    
    df_combined = deduplicate_by_signature(df_combined)
    print(f"After final dedup: {df_combined.height} rows")
    
    # Sort by time
    if "time" in df_combined.columns:
        df_combined = df_combined.sort("time")
    
    # Convert list columns to strings for CSV compatibility
    for col in df_combined.columns:
        if df_combined[col].dtype == pl.List:
            df_combined = df_combined.with_columns(
                pl.col(col).list.join(",").alias(col)
            )
    
    # Write output
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"planequery_aircraft_adsb_{start_date}_{end_date}.csv"
    
    df_combined.write_csv(output_path)
    print(f"Wrote final output: {output_path}")
    print(f"Total records: {df_combined.height}")
    
    return output_path


def main() -> None:
    """Main entry point for GitHub Actions."""
    start_date = os.environ.get("GLOBAL_START_DATE")
    end_date = os.environ.get("GLOBAL_END_DATE")
    
    if not start_date or not end_date:
        print("ERROR: GLOBAL_START_DATE and GLOBAL_END_DATE must be set", file=sys.stderr)
        sys.exit(1)
    
    chunks_dir = Path("chunks")
    output_dir = Path("data/planequery_aircraft")
    
    combine_chunks(chunks_dir, output_dir, start_date, end_date)


if __name__ == "__main__":
    main()
