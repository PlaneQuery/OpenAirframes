"""
Processes trace files from a single archive part for a single day.
This is the map phase of the map-reduce pipeline.

Usage:
    python -m src.adsb.process_icao_chunk --part-id 1 --date 2026-01-01
"""
import gc
import os
import sys
import argparse
import time
import concurrent.futures
from datetime import datetime, timedelta
import tarfile
import tempfile
import shutil

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

def build_trace_file_map(archive_path: str) -> dict[str, str]:
    """Build a map of ICAO -> trace file path by extracting tar.gz archive."""
    print(f"Extracting {archive_path}...")
    
    temp_dir = tempfile.mkdtemp(prefix="adsb_extract_")
    
    with tarfile.open(archive_path, 'r:gz') as tar:
        tar.extractall(path=temp_dir, filter='data')
    
    trace_map = collect_trace_files_with_find(temp_dir)
    print(f"Found {len(trace_map)} trace files")
    
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
    trace_files: list[str],
    part_id: int,
    date_str: str,
) -> str | None:
    """Process trace files and write to a single parquet file."""
    
    output_path = os.path.join(PARQUET_DIR, f"part_{part_id}_{date_str}.parquet")
    
    start_time = time.perf_counter()
    total_rows = 0
    batch_rows = []
    writer = None
    
    try:
        writer = pq.ParquetWriter(output_path, PARQUET_SCHEMA, compression='snappy')
        
        files_per_batch = MAX_WORKERS * 100
        for offset in range(0, len(trace_files), files_per_batch):
            batch_files = trace_files[offset:offset + files_per_batch]
            
            with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for rows in executor.map(safe_process, batch_files):
                    if rows:
                        batch_rows.extend(rows)
                        
                        if len(batch_rows) >= BATCH_SIZE:
                            writer.write_table(rows_to_table(batch_rows))
                            total_rows += len(batch_rows)
                            batch_rows = []
                            gc.collect()
                            
                            print(f"Part {part_id}: {total_rows} rows, {time.perf_counter() - start_time:.1f}s | {get_resource_usage()}")
            
            gc.collect()
        
        if batch_rows:
            writer.write_table(rows_to_table(batch_rows))
            total_rows += len(batch_rows)
    
    finally:
        if writer:
            writer.close()
    
    print(f"Part {part_id}: Done! {total_rows} rows in {time.perf_counter() - start_time:.1f}s | {get_resource_usage()}")
    
    return output_path if total_rows > 0 else None

from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Process a single archive part for a day")
    parser.add_argument("--part-id", type=int, required=True, help="Part ID (1-indexed)")
    parser.add_argument("--date", type=str, required=True, help="Date in YYYY-MM-DD format")
    args = parser.parse_args()
    
    print(f"Processing part {args.part_id} for {args.date}")
    
    # Get specific archive file for this part
    archive_path = os.path.join(OUTPUT_DIR, "adsb_archives", args.date, f"{args.date}_part_{args.part_id}.tar.gz")
    
    # Extract and collect trace files
    trace_map = build_trace_file_map(archive_path)
    all_trace_files = list(trace_map.values())
    
    print(f"Total trace files: {len(all_trace_files)}")
    
    # Process and write output
    output_path = process_chunk(all_trace_files, args.part_id, args.date)
    
    from src.adsb.compress_adsb_to_aircraft_data import compress_parquet_part
    df_compressed = compress_parquet_part(args.part_id, args.date)
    
    # Write parquet
    df_compressed_output = OUTPUT_DIR / "compressed" / args.date/ f"part_{args.part_id}_{args.date}.parquet"
    os.makedirs(df_compressed_output.parent, exist_ok=True)
    df_compressed.write_parquet(df_compressed_output, compression='snappy')
    
    # Write CSV
    csv_output = OUTPUT_DIR / "compressed" / args.date / f"part_{args.part_id}_{args.date}.csv"
    df_compressed.write_csv(csv_output)
    
    print(f"Raw output: {output_path}" if output_path else "No raw output generated")
    print(f"Compressed parquet: {df_compressed_output}")
    print(f"Compressed CSV: {csv_output}")


if __name__ == "__main__":
    main()