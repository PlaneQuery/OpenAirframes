"""
Combines chunk parquet files and compresses to final aircraft CSV.
This is the reduce phase of the map-reduce pipeline.

Supports both single-day (daily) and multi-day (historical) modes.

Memory-efficient: processes each chunk separately, compresses, then combines.

Usage:
    # Daily mode
    python -m src.adsb.combine_chunks_to_csv --chunks-dir data/output/adsb_chunks
    
    # Historical mode
    python -m src.adsb.combine_chunks_to_csv --chunks-dir data/output/adsb_chunks --start-date 2024-01-01 --end-date 2024-01-07 --skip-base
"""
import gc
import os
import sys
import glob
import argparse
from datetime import datetime, timedelta

import polars as pl

from src.adsb.download_adsb_data_to_parquet import OUTPUT_DIR, get_resource_usage
from src.adsb.compress_adsb_to_aircraft_data import compress_multi_icao_df, COLUMNS


DEFAULT_CHUNK_DIR = os.path.join(OUTPUT_DIR, "adsb_chunks")
FINAL_OUTPUT_DIR = "./data/planequery_aircraft"
os.makedirs(FINAL_OUTPUT_DIR, exist_ok=True)


def get_target_day() -> datetime:
    """Get yesterday's date (the day we're processing)."""
    return datetime.utcnow() - timedelta(days=1)


def process_single_chunk(chunk_path: str) -> pl.DataFrame:
    """Load and compress a single chunk parquet file."""
    print(f"Processing {os.path.basename(chunk_path)}... | {get_resource_usage()}")
    
    # Load chunk - only columns we need
    needed_columns = ['time', 'icao'] + COLUMNS
    df = pl.read_parquet(chunk_path, columns=needed_columns)
    print(f"  Loaded {len(df)} rows")
    
    # Compress to aircraft records (one per ICAO) using shared function
    compressed = compress_multi_icao_df(df, verbose=True)
    print(f"  Compressed to {len(compressed)} aircraft records")
    
    del df
    gc.collect()
    
    return compressed


def combine_compressed_chunks(compressed_dfs: list[pl.DataFrame]) -> pl.DataFrame:
    """Combine multiple compressed DataFrames.
    
    Since chunks are partitioned by ICAO hash, each ICAO only appears in one chunk.
    No deduplication needed here - just concatenate.
    """
    print(f"Combining {len(compressed_dfs)} compressed chunks... | {get_resource_usage()}")
    
    # Concat all
    combined = pl.concat(compressed_dfs)
    print(f"Combined: {len(combined)} records")
    
    return combined


def download_and_merge_base_release(compressed_df: pl.DataFrame) -> pl.DataFrame:
    """Download base release and merge with new data."""
    from src.get_latest_planequery_aircraft_release import download_latest_aircraft_adsb_csv
    
    print("Downloading base ADS-B release...")
    try:
        base_path = download_latest_aircraft_adsb_csv(
            output_dir="./data/planequery_aircraft_base"
        )
        print(f"Download returned: {base_path}")
        
        if base_path and os.path.exists(str(base_path)):
            print(f"Loading base release from {base_path}")
            base_df = pl.read_csv(base_path)
            print(f"Base release has {len(base_df)} records")
            
            # Ensure columns match
            base_cols = set(base_df.columns)
            new_cols = set(compressed_df.columns)
            print(f"Base columns: {sorted(base_cols)}")
            print(f"New columns: {sorted(new_cols)}")
            
            # Add missing columns
            for col in new_cols - base_cols:
                base_df = base_df.with_columns(pl.lit(None).alias(col))
            for col in base_cols - new_cols:
                compressed_df = compressed_df.with_columns(pl.lit(None).alias(col))
            
            # Reorder columns to match
            compressed_df = compressed_df.select(base_df.columns)
            
            # Concat and deduplicate by icao (keep new data - it comes last)
            combined = pl.concat([base_df, compressed_df])
            print(f"After concat: {len(combined)} records")
            
            deduplicated = combined.unique(subset=["icao"], keep="last")
            
            print(f"Combined with base: {len(combined)} -> {len(deduplicated)} after dedup")
            
            del base_df, combined
            gc.collect()
            
            return deduplicated
        else:
            print(f"No base release found at {base_path}, using only new data")
            return compressed_df
    except Exception as e:
        import traceback
        print(f"Failed to download base release: {e}")
        traceback.print_exc()
        return compressed_df


def cleanup_chunks(output_id: str, chunks_dir: str):
    """Delete chunk parquet files after successful merge."""
    pattern = os.path.join(chunks_dir, f"chunk_*_{output_id}.parquet")
    chunk_files = glob.glob(pattern)
    for f in chunk_files:
        try:
            os.remove(f)
            print(f"Deleted {f}")
        except Exception as e:
            print(f"Failed to delete {f}: {e}")


def find_chunk_files(chunks_dir: str, output_id: str) -> list[str]:
    """Find chunk parquet files matching the output ID."""
    pattern = os.path.join(chunks_dir, f"chunk_*_{output_id}.parquet")
    chunk_files = sorted(glob.glob(pattern))
    
    if not chunk_files:
        # Try recursive search for historical mode with merged artifacts
        pattern = os.path.join(chunks_dir, "**", "*.parquet")
        chunk_files = sorted(glob.glob(pattern, recursive=True))
    
    return chunk_files


def main():
    parser = argparse.ArgumentParser(description="Combine chunk parquets to final CSV")
    parser.add_argument("--date", type=str, help="Single date in YYYY-MM-DD format (default: yesterday)")
    parser.add_argument("--start-date", type=str, help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date for range (YYYY-MM-DD)")
    parser.add_argument("--chunks-dir", type=str, default=DEFAULT_CHUNK_DIR, help="Directory containing chunk parquet files")
    parser.add_argument("--skip-base", action="store_true", help="Skip downloading and merging base release")
    parser.add_argument("--keep-chunks", action="store_true", help="Keep chunk files after merging")
    args = parser.parse_args()
    
    # Determine output ID and filename based on mode
    if args.start_date and args.end_date:
        # Historical mode
        output_id = f"{args.start_date}_{args.end_date}"
        output_filename = f"planequery_aircraft_adsb_{args.start_date}_{args.end_date}.csv"
        print(f"Combining chunks for date range: {args.start_date} to {args.end_date}")
    else:
        # Daily mode
        if args.date:
            target_day = datetime.strptime(args.date, "%Y-%m-%d")
        else:
            target_day = get_target_day()
        
        date_str = target_day.strftime("%Y-%m-%d")
        output_id = date_str
        output_filename = f"planequery_aircraft_adsb_{date_str}.csv"
        print(f"Combining chunks for {date_str}")
    
    chunks_dir = args.chunks_dir
    print(f"Chunks directory: {chunks_dir}")
    print(f"Resource usage at start: {get_resource_usage()}")
    
    # Find chunk files
    chunk_files = find_chunk_files(chunks_dir, output_id)
    
    if not chunk_files:
        print(f"No chunk files found in: {chunks_dir}")
        sys.exit(1)
    
    print(f"Found {len(chunk_files)} chunk files")
    
    # Process each chunk separately to save memory
    compressed_chunks = []
    for chunk_path in chunk_files:
        compressed = process_single_chunk(chunk_path)
        compressed_chunks.append(compressed)
        gc.collect()
    
    # Combine all compressed chunks
    combined = combine_compressed_chunks(compressed_chunks)
    
    # Free memory from individual chunks
    del compressed_chunks
    gc.collect()
    print(f"After combining: {get_resource_usage()}")
    
    # Merge with base release (unless skipped)
    if not args.skip_base:
        combined = download_and_merge_base_release(combined)
    
    # Convert list columns to strings for CSV compatibility
    for col in combined.columns:
        if combined[col].dtype == pl.List:
            combined = combined.with_columns(
                pl.col(col).list.join(",").alias(col)
            )
    
    # Sort by time for consistent output
    if 'time' in combined.columns:
        combined = combined.sort('time')
    
    # Write final CSV
    output_path = os.path.join(FINAL_OUTPUT_DIR, output_filename)
    combined.write_csv(output_path)
    print(f"Wrote {len(combined)} records to {output_path}")
    
    # Cleanup
    if not args.keep_chunks:
        cleanup_chunks(output_id, chunks_dir)
    
    print(f"Done! | {get_resource_usage()}")


if __name__ == "__main__":
    main()
