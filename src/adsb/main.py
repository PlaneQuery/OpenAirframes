"""
Main pipeline for processing ADS-B data from adsb.lol.

Usage:
    python -m src.adsb.main --date 2026-01-01
"""
import argparse
import subprocess
import sys
from datetime import datetime, timedelta

from src.adsb.download_and_list_icaos import NUMBER_PARTS


def main():
    parser = argparse.ArgumentParser(description="Process ADS-B data for a single day")
    parser.add_argument("--date", type=str, required=True)
    args = parser.parse_args()
    
    date_str = datetime.strptime(args.date, "%Y-%m-%d").strftime("%Y-%m-%d")
    print(f"Processing day: {date_str}")
    
    # Download and split
    subprocess.run([sys.executable, "-m", "src.adsb.download_and_list_icaos", "--date", date_str], check=True)
    
    # Process parts
    for part_id in range(NUMBER_PARTS):
        subprocess.run([sys.executable, "-m", "src.adsb.process_icao_chunk", "--part-id", str(part_id), "--date", date_str], check=True)
    
    # Concatenate
    subprocess.run([sys.executable, "src/adsb/concat_parquet_to_final.py", "--date", date_str], check=True)
    
    print("Done")


if __name__ == "__main__":
    main()