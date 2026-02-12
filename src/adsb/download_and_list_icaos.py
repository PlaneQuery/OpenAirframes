"""
Downloads and extracts adsb.lol tar files, then lists all ICAO folders.
This is the first step of the map-reduce pipeline.

Supports both single-day (daily) and multi-day (historical) modes.

Outputs:
- Extracted trace files in data/output/{version_date}-planes-readsb-prod-0.tar_0/
- ICAO manifest at data/output/icao_manifest_{date}.txt
"""
import os
import sys
import argparse
import glob
import subprocess
from datetime import datetime, timedelta

# Re-use download/extract functions from download_adsb_data_to_parquet
from src.adsb.download_adsb_data_to_parquet import (
    OUTPUT_DIR,
    fetch_releases,
    download_asset,
    extract_split_archive,
    collect_trace_files_with_find,
)


def get_target_day() -> datetime:
    """Get yesterday's date (the day we're processing)."""
    return datetime.utcnow() - timedelta(days=1)


def download_and_extract(version_date: str) -> str | None:
    """Download and extract tar files, return extract directory path."""
    extract_dir = os.path.join(OUTPUT_DIR, f"{version_date}-planes-readsb-prod-0.tar_0")
    
    # Check if already extracted
    if os.path.isdir(extract_dir):
        print(f"[SKIP] Already extracted: {extract_dir}")
        return extract_dir
    
    # Check for existing tar files
    pattern = os.path.join(OUTPUT_DIR, f"{version_date}-planes-readsb-prod-0*")
    matches = [p for p in glob.glob(pattern) if os.path.isfile(p)]
    
    if matches:
        print(f"Found existing tar files for {version_date}")
        normal_matches = [
            p for p in matches
            if "-planes-readsb-prod-0." in os.path.basename(p)
            and "tmp" not in os.path.basename(p)
        ]
        downloaded_files = normal_matches if normal_matches else matches
    else:
        # Download from GitHub
        print(f"Downloading releases for {version_date}...")
        releases = fetch_releases(version_date)
        if not releases:
            print(f"No releases found for {version_date}")
            return None
        
        downloaded_files = []
        for release in releases:
            tag_name = release["tag_name"]
            print(f"Processing release: {tag_name}")
            
            assets = release.get("assets", [])
            normal_assets = [
                a for a in assets
                if "planes-readsb-prod-0." in a["name"] and "tmp" not in a["name"]
            ]
            tmp_assets = [
                a for a in assets
                if "planes-readsb-prod-0tmp" in a["name"]
            ]
            use_assets = normal_assets if normal_assets else tmp_assets
            
            for asset in use_assets:
                asset_name = asset["name"]
                asset_url = asset["browser_download_url"]
                file_path = os.path.join(OUTPUT_DIR, asset_name)
                if download_asset(asset_url, file_path):
                    downloaded_files.append(file_path)
    
    if not downloaded_files:
        print(f"No files downloaded for {version_date}")
        return None
    
    # Extract
    if extract_split_archive(downloaded_files, extract_dir):
        return extract_dir
    return None


def list_icao_folders(extract_dir: str) -> list[str]:
    """List all ICAO folder names from extracted directory."""
    trace_files = collect_trace_files_with_find(extract_dir)
    icaos = sorted(trace_files.keys())
    print(f"Found {len(icaos)} unique ICAOs")
    return icaos


def write_manifest(icaos: list[str], manifest_id: str) -> str:
    """Write ICAO list to manifest file.
    
    Args:
        icaos: List of ICAO codes
        manifest_id: Identifier for manifest file (date or date range)
    """
    manifest_path = os.path.join(OUTPUT_DIR, f"icao_manifest_{manifest_id}.txt")
    with open(manifest_path, "w") as f:
        for icao in sorted(icaos):
            f.write(f"{icao}\n")
    print(f"Wrote manifest with {len(icaos)} ICAOs to {manifest_path}")
    return manifest_path


def process_single_day(target_day: datetime) -> tuple[str | None, list[str]]:
    """Process a single day: download, extract, list ICAOs.
    
    Returns:
        Tuple of (extract_dir, icaos)
    """
    date_str = target_day.strftime("%Y-%m-%d")
    version_date = f"v{target_day.strftime('%Y.%m.%d')}"
    
    print(f"Processing date: {date_str} (version: {version_date})")
    
    extract_dir = download_and_extract(version_date)
    if not extract_dir:
        print(f"Failed to download/extract data for {date_str}")
        return None, []
    
    icaos = list_icao_folders(extract_dir)
    print(f"Found {len(icaos)} ICAOs for {date_str}")
    
    return extract_dir, icaos


def process_date_range(start_date: datetime, end_date: datetime) -> set[str]:
    """Process multiple days: download, extract, combine ICAO lists.
    
    Args:
        start_date: Start date (inclusive)
        end_date: End date (inclusive)
    
    Returns:
        Combined set of all ICAOs across the date range
    """
    all_icaos: set[str] = set()
    current = start_date
    
    # Both start and end are inclusive
    while current <= end_date:
        _, icaos = process_single_day(current)
        all_icaos.update(icaos)
        current += timedelta(days=1)
    
    return all_icaos


def main():
    parser = argparse.ArgumentParser(description="Download and list ICAOs from adsb.lol data")
    parser.add_argument("--date", type=str, help="Single date in YYYY-MM-DD format (default: yesterday)")
    parser.add_argument("--start-date", type=str, help="Start date for range (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str, help="End date for range (YYYY-MM-DD)")
    args = parser.parse_args()
    
    # Determine mode: single day or date range
    if args.start_date and args.end_date:
        # Historical mode: process date range
        start_date = datetime.strptime(args.start_date, "%Y-%m-%d")
        end_date = datetime.strptime(args.end_date, "%Y-%m-%d")
        
        print(f"Processing date range: {args.start_date} to {args.end_date}")
        
        all_icaos = process_date_range(start_date, end_date)
        
        if not all_icaos:
            print("No ICAOs found in date range")
            sys.exit(1)
        
        # Write combined manifest with range identifier
        manifest_id = f"{args.start_date}_{args.end_date}"
        write_manifest(list(all_icaos), manifest_id)
        
        print(f"\nDone! Total ICAOs: {len(all_icaos)}")
        
    else:
        # Daily mode: single day
        if args.date:
            target_day = datetime.strptime(args.date, "%Y-%m-%d")
        else:
            target_day = get_target_day()
        
        date_str = target_day.strftime("%Y-%m-%d")
        
        extract_dir, icaos = process_single_day(target_day)
        
        if not icaos:
            print("No ICAOs found")
            sys.exit(1)
        
        write_manifest(icaos, date_str)
        
        print(f"\nDone! Extract dir: {extract_dir}")
        print(f"Total ICAOs: {len(icaos)}")


if __name__ == "__main__":
    main()
