#!/usr/bin/env python3
"""
Run the full ADS-B processing pipeline locally.

Downloads adsb.lol data, processes trace files, and outputs openairframes_adsb CSV.

Usage:
    # Single day (yesterday by default)
    python -m src.adsb.run_local
    
    # Single day (specific date)
    python -m src.adsb.run_local 2024-01-15
    
    # Date range (inclusive)
    python -m src.adsb.run_local 2024-01-01 2024-01-07
"""
import argparse
import os
import subprocess
import sys
from datetime import datetime, timedelta


def run_cmd(cmd: list[str], description: str) -> None:
    """Run a command and exit on failure."""
    print(f"\n>>> {' '.join(cmd)}")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"ERROR: {description} failed with exit code {result.returncode}")
        sys.exit(result.returncode)


def main():
    parser = argparse.ArgumentParser(
        description="Run full ADS-B processing pipeline locally",
        usage="python -m src.adsb.run_local [start_date] [end_date]"
    )
    parser.add_argument(
        "start_date",
        nargs="?",
        help="Start date (YYYY-MM-DD). Default: yesterday"
    )
    parser.add_argument(
        "end_date",
        nargs="?",
        help="End date (YYYY-MM-DD, inclusive). If omitted, processes single day"
    )
    parser.add_argument(
        "--chunks",
        type=int,
        default=4,
        help="Number of parallel chunks (default: 4)"
    )
    parser.add_argument(
        "--chunk-days",
        type=int,
        default=1,
        help="Days per chunk for date range processing (default: 1)"
    )
    parser.add_argument(
        "--skip-base",
        action="store_true",
        help="Skip downloading and merging with base release"
    )
    args = parser.parse_args()

    # Determine dates
    if args.start_date:
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
    else:
        start_date = datetime.utcnow() - timedelta(days=1)
    
    end_date = None
    if args.end_date:
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
    
    start_str = start_date.strftime("%Y-%m-%d")
    end_str = end_date.strftime("%Y-%m-%d") if end_date else None
    
    # Generate date chunks if processing a range
    date_chunks = []
    if end_str:
        current = start_date
        while current < end_date:
            chunk_end = min(current + timedelta(days=args.chunk_days), end_date)
            date_chunks.append({
                'start': current.strftime("%Y-%m-%d"),
                'end': chunk_end.strftime("%Y-%m-%d")
            })
            current = chunk_end
    else:
        # Single day
        date_chunks = [{'start': start_str, 'end': start_str}]
    
    print("=" * 60)
    print("ADS-B Processing Pipeline")
    print("=" * 60)
    if end_str:
        print(f"Date range: {start_str} to {end_str}")
        print(f"Date chunks: {len(date_chunks)} ({args.chunk_days} days each)")
    else:
        print(f"Date: {start_str}")
    print(f"ICAO chunks: {args.chunks}")
    print("=" * 60)
    
    # Process each date chunk
    for idx, date_chunk in enumerate(date_chunks, 1):
        chunk_start = date_chunk['start']
        chunk_end = date_chunk['end']
        
        print(f"\n{'=' * 60}")
        print(f"Processing Date Chunk {idx}/{len(date_chunks)}: {chunk_start} to {chunk_end}")
        print('=' * 60)
        
        # Step 1: Download and extract
        print("\n" + "=" * 60)
        print("Step 1: Download and Extract")
        print("=" * 60)
        
        if chunk_start == chunk_end:
            cmd = ["python", "-m", "src.adsb.download_and_list_icaos",
                   "--date", chunk_start]
        else:
            cmd = ["python", "-m", "src.adsb.download_and_list_icaos",
                   "--start-date", chunk_start, "--end-date", chunk_end]
        run_cmd(cmd, "Download and extract")
        
        # Step 2: Process chunks
        print("\n" + "=" * 60)
        print("Step 2: Process Chunks")
        print("=" * 60)
        
        for chunk_id in range(args.chunks):
            print(f"\n--- ICAO Chunk {chunk_id + 1}/{args.chunks} ---")
            if chunk_start == chunk_end:
                cmd = ["python", "-m", "src.adsb.process_icao_chunk",
                       "--chunk-id", str(chunk_id),
                       "--total-chunks", str(args.chunks),
                       "--date", chunk_start]
            else:
                cmd = ["python", "-m", "src.adsb.process_icao_chunk",
                       "--chunk-id", str(chunk_id),
                       "--total-chunks", str(args.chunks),
                       "--start-date", chunk_start,
                       "--end-date", chunk_end]
            run_cmd(cmd, f"Process ICAO chunk {chunk_id}")
    
    # Step 3: Combine all chunks to CSV
    print("\n" + "=" * 60)
    print("Step 3: Combine All Chunks to CSV")
    print("=" * 60)
    
    chunks_dir = "./data/output/adsb_chunks"
    cmd = ["python", "-m", "src.adsb.combine_chunks_to_csv",
           "--chunks-dir", chunks_dir]
    
    if end_str:
        cmd.extend(["--start-date", start_str, "--end-date", end_str])
    else:
        cmd.extend(["--date", start_str])
    
    if args.skip_base:
        cmd.append("--skip-base")
    
    run_cmd(cmd, "Combine chunks")
    
    print("\n" + "=" * 60)
    print("Done!")
    print("=" * 60)
    
    # Show output
    output_dir = "./data/openairframes"
    if end_str:
        output_file = f"openairframes_adsb_{start_str}_{end_str}.csv.gz"
    else:
        output_file = f"openairframes_adsb_{start_str}_{start_str}.csv.gz"
    
    output_path = os.path.join(output_dir, output_file)
    if os.path.exists(output_path):
        size_mb = os.path.getsize(output_path) / (1024 * 1024)
        print(f"Output: {output_path}")
        print(f"Size: {size_mb:.1f} MB")


if __name__ == "__main__":
    main()
