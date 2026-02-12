"""
Processes a chunk of ICAOs from pre-extracted trace files.
This is the map phase of the map-reduce pipeline.

Supports both single-day (daily) and multi-day (historical) modes.

Expects extract_dir to already exist with trace files.
Reads ICAO manifest to determine which ICAOs to process based on chunk-id.

Usage:
    # Daily mode (single day)
    python -m src.adsb.process_icao_chunk --chunk-id 0 --total-chunks 4
    
    # Historical mode (date range)
    python -m src.adsb.process_icao_chunk --chunk-id 0 --total-chunks 4 --start-date 2024-01-01 --end-date 2024-01-07
"""
import gc
import os
import sys
import argparse
import time
import concurrent.futures
from datetime import datetime, timedelta

import pyarrow as pa
import pyarrow.parquet as pq

from src.adsb.download_adsb_data_to_parquet import (
    OUTPUT_DIR,
    PARQUET_DIR,
    PARQUET_SCHEMA,
    COLUMNS,
    MAX_WORKERS,
    process_file,
    get_resource_usage,
    collect_trace_files_with_find,
)


CHUNK_OUTPUT_DIR = os.path.join(OUTPUT_DIR, "adsb_chunks")
os.makedirs(CHUNK_OUTPUT_DIR, exist_ok=True)

# Smaller batch size for memory efficiency
BATCH_SIZE = 100_000


def get_target_day() -> datetime:
    """Get yesterday's date (the day we're processing)."""
    return datetime.utcnow() - timedelta(days=1)


def read_manifest(manifest_id: str) -> list[str]:
    """Read ICAO manifest file.
    
    Args:
        manifest_id: Either a date string (YYYY-MM-DD) or range string (YYYY-MM-DD_YYYY-MM-DD)
    """
    manifest_path = os.path.join(OUTPUT_DIR, f"icao_manifest_{manifest_id}.txt")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"Manifest not found: {manifest_path}")
    
    with open(manifest_path, "r") as f:
        icaos = [line.strip() for line in f if line.strip()]
    return icaos


def deterministic_hash(s: str) -> int:
    """Return a deterministic hash for a string (unlike Python's hash() which is randomized)."""
    # Use sum of byte values - simple but deterministic
    return sum(ord(c) for c in s)


def get_chunk_icaos(icaos: list[str], chunk_id: int, total_chunks: int) -> list[str]:
    """Get the subset of ICAOs for this chunk based on deterministic hash partitioning."""
    return [icao for icao in icaos if deterministic_hash(icao) % total_chunks == chunk_id]


def build_trace_file_map(extract_dir: str) -> dict[str, str]:
    """Build a map of ICAO -> trace file path using find command."""
    print(f"Building trace file map from {extract_dir}...")
    
    # Debug: check what's in extract_dir
    if os.path.isdir(extract_dir):
        items = os.listdir(extract_dir)[:10]
        print(f"First 10 items in extract_dir: {items}")
        # Check if there are subdirectories
        for item in items[:3]:
            subpath = os.path.join(extract_dir, item)
            if os.path.isdir(subpath):
                subitems = os.listdir(subpath)[:5]
                print(f"  Contents of {item}/: {subitems}")
    
    trace_map = collect_trace_files_with_find(extract_dir)
    print(f"Found {len(trace_map)} trace files")
    
    if len(trace_map) == 0:
        # Debug: try manual find
        import subprocess
        result = subprocess.run(
            ['find', extract_dir, '-type', 'f', '-name', 'trace_full_*'],
            capture_output=True, text=True
        )
        print(f"Manual find output (first 500 chars): {result.stdout[:500]}")
        print(f"Manual find stderr: {result.stderr[:200]}")
    
    return trace_map


def safe_process(filepath: str) -> list:
    """Safely process a file, returning empty list on error."""
    try:
        return process_file(filepath)
    except Exception as e:
        print(f"Error processing {filepath}: {e}")
        return []


def rows_to_table(rows: list) -> pa.Table:
    """Convert list of rows to PyArrow table."""
    import pandas as pd
    df = pd.DataFrame(rows, columns=COLUMNS)
    if not df['time'].dt.tz:
        df['time'] = df['time'].dt.tz_localize('UTC')
    return pa.Table.from_pandas(df, schema=PARQUET_SCHEMA, preserve_index=False)


def process_chunk(
    chunk_id: int,
    total_chunks: int,
    trace_map: dict[str, str],
    icaos: list[str],
    output_id: str,
) -> str | None:
    """Process a chunk of ICAOs and write to parquet.
    
    Args:
        chunk_id: This chunk's ID (0-indexed)
        total_chunks: Total number of chunks
        trace_map: Map of ICAO -> trace file path
        icaos: Full list of ICAOs from manifest
        output_id: Identifier for output file (date or date range)
    """
    chunk_icaos = get_chunk_icaos(icaos, chunk_id, total_chunks)
    print(f"Chunk {chunk_id}/{total_chunks}: Processing {len(chunk_icaos)} ICAOs")
    
    if not chunk_icaos:
        print(f"Chunk {chunk_id}: No ICAOs to process")
        return None
    
    # Get trace file paths from the map
    trace_files = []
    for icao in chunk_icaos:
        if icao in trace_map:
            trace_files.append(trace_map[icao])
    
    print(f"Chunk {chunk_id}: Found {len(trace_files)} trace files")
    
    if not trace_files:
        print(f"Chunk {chunk_id}: No trace files found")
        return None
    
    # Process files and write parquet in batches
    output_path = os.path.join(CHUNK_OUTPUT_DIR, f"chunk_{chunk_id}_{output_id}.parquet")
    
    start_time = time.perf_counter()
    total_rows = 0
    batch_rows = []
    writer = None
    
    try:
        # Process in parallel batches
        files_per_batch = MAX_WORKERS * 100
        for offset in range(0, len(trace_files), files_per_batch):
            batch_files = trace_files[offset:offset + files_per_batch]
            
            with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for rows in executor.map(safe_process, batch_files):
                    if rows:
                        batch_rows.extend(rows)
                        
                        # Write when batch is full
                        if len(batch_rows) >= BATCH_SIZE:
                            table = rows_to_table(batch_rows)
                            total_rows += len(batch_rows)
                            
                            if writer is None:
                                writer = pq.ParquetWriter(output_path, PARQUET_SCHEMA, compression='snappy')
                            writer.write_table(table)
                            
                            batch_rows = []
                            del table
                            gc.collect()
                            
                            elapsed = time.perf_counter() - start_time
                            print(f"Chunk {chunk_id}: {total_rows} rows, {elapsed:.1f}s | {get_resource_usage()}")
            
            gc.collect()
        
        # Write remaining rows
        if batch_rows:
            table = rows_to_table(batch_rows)
            total_rows += len(batch_rows)
            
            if writer is None:
                writer = pq.ParquetWriter(output_path, PARQUET_SCHEMA, compression='snappy')
            writer.write_table(table)
            del table
    
    finally:
        if writer:
            writer.close()
    
    elapsed = time.perf_counter() - start_time
    print(f"Chunk {chunk_id}: Done! {total_rows} rows in {elapsed:.1f}s | {get_resource_usage()}")
    
    if total_rows > 0:
        return output_path
    return None


def process_single_day(
    chunk_id: int,
    total_chunks: int,
    target_day: datetime,
) -> str | None:
    """Process a single day for this chunk."""
    date_str = target_day.strftime("%Y-%m-%d")
    version_date = f"v{target_day.strftime('%Y.%m.%d')}"
    
    extract_dir = os.path.join(OUTPUT_DIR, f"{version_date}-planes-readsb-prod-0.tar_0")
    
    if not os.path.isdir(extract_dir):
        print(f"Extract directory not found: {extract_dir}")
        return None
    
    trace_map = build_trace_file_map(extract_dir)
    if not trace_map:
        print("No trace files found")
        return None
    
    icaos = read_manifest(date_str)
    print(f"Total ICAOs in manifest: {len(icaos)}")
    
    return process_chunk(chunk_id, total_chunks, trace_map, icaos, date_str)


def process_date_range(
    chunk_id: int,
    total_chunks: int,
    start_date: datetime,
    end_date: datetime,
) -> str | None:
    """Process a date range for this chunk.
    
    Combines trace files from all days in the range.
    
    Args:
        chunk_id: This chunk's ID (0-indexed)
        total_chunks: Total number of chunks
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    """
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d")
    manifest_id = f"{start_str}_{end_str}"
    
    print(f"Processing date range: {start_str} to {end_str}")
    
    # Build combined trace map from all days
    combined_trace_map: dict[str, str] = {}
    current = start_date
    
    # Both start and end are inclusive
    while current <= end_date:
        version_date = f"v{current.strftime('%Y.%m.%d')}"
        extract_dir = os.path.join(OUTPUT_DIR, f"{version_date}-planes-readsb-prod-0.tar_0")
        
        if os.path.isdir(extract_dir):
            trace_map = build_trace_file_map(extract_dir)
            # Later days override earlier days (use most recent trace file)
            combined_trace_map.update(trace_map)
            print(f"  {current.strftime('%Y-%m-%d')}: {len(trace_map)} trace files")
        else:
            print(f"  {current.strftime('%Y-%m-%d')}: no extract directory")
        
        current += timedelta(days=1)
    
    if not combined_trace_map:
        print("No trace files found in date range")
        return None
    
    print(f"Combined trace map: {len(combined_trace_map)} ICAOs")
    
    icaos = read_manifest(manifest_id)
    print(f"Total ICAOs in manifest: {len(icaos)}")
    
    return process_chunk(chunk_id, total_chunks, combined_trace_map, icaos, manifest_id)


def main():
    parser = argparse.ArgumentParser(description="Process a chunk of ICAOs")
    parser.add_argument("--chunk-id", type=int, required=True, help="Chunk ID (0-indexed)")
    parser.add_argument("--total-chunks", type=int, required=True, help="Total number of chunks")
    parser.add_argument("--date", type=str, help="Single date in YYYY-MM-DD format (default: yesterday)")
    parser.add_argument("--start-date", type=str, help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date for range (YYYY-MM-DD)")
    args = parser.parse_args()
    
    print(f"Processing chunk {args.chunk_id}/{args.total_chunks}")
    print(f"OUTPUT_DIR: {OUTPUT_DIR}")
    print(f"CHUNK_OUTPUT_DIR: {CHUNK_OUTPUT_DIR}")
    print(f"Resource usage at start: {get_resource_usage()}")
    
    # Debug: List what's in OUTPUT_DIR
    print(f"\nContents of {OUTPUT_DIR}:")
    if os.path.isdir(OUTPUT_DIR):
        for item in os.listdir(OUTPUT_DIR)[:20]:
            print(f"  - {item}")
    else:
        print(f"  Directory does not exist!")
    
    # Determine mode: single day or date range
    if args.start_date and args.end_date:
        # Historical mode
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
        output_path = process_date_range(args.chunk_id, args.total_chunks, start_date, end_date)
    else:
        # Daily mode
        if args.date:
            target_day = datetime.strptime(args.date, "%Y-%m-%d")
        else:
            target_day = get_target_day()
        output_path = process_single_day(args.chunk_id, args.total_chunks, target_day)
    
    if output_path:
        print(f"Output: {output_path}")
    else:
        print("No output generated")


if __name__ == "__main__":
    main()
