"""
Downloads and extracts adsb.lol tar files for a single day, then lists all ICAO folders.
This is the first step of the map-reduce pipeline.

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
        
        # Prefer non-tmp releases; only use tmp if no normal releases exist
        normal_releases = [r for r in releases if "tmp" not in r["tag_name"]]
        tmp_releases = [r for r in releases if "tmp" in r["tag_name"]]
        releases = normal_releases if normal_releases else tmp_releases
        print(f"Using {'normal' if normal_releases else 'tmp'} releases ({len(releases)} found)")
        
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

from pathlib import Path
import tarfile
def split_folders_into_gzip_archives(extract_dir: Path, tar_output_dir: Path, icaos: list[str], parts = 16) -> list[str]:
    traces_dir = extract_dir / "traces"
    buckets = sorted(traces_dir.iterdir())
    tars = []
    for i in range(parts):
        tar_path = tar_output_dir / f"{tar_output_dir.name}_part_{i}.tar.gz"
        tars.append(tarfile.open(tar_path, "w:gz"))
    for idx, bucket_path in enumerate(buckets):
        tar_idx = idx % parts
        tars[tar_idx].add(bucket_path, arcname=bucket_path.name)
    for tar in tars:
        tar.close()


def main():
    parser = argparse.ArgumentParser(description="Download and list ICAOs from adsb.lol data for a single day")
    parser.add_argument("--date", type=str, help="Single date in YYYY-MM-DD format (default: yesterday)")
    args = parser.parse_args()
    
    target_day = datetime.strptime(args.date, "%Y-%m-%d")
    date_str = target_day.strftime("%Y-%m-%d")
    tar_output_dir = Path(f"./data/output/adsb_archives/{date_str}")
    
    extract_dir, icaos = process_single_day(target_day)
    extract_dir = Path(extract_dir)
    print(extract_dir)
    tar_output_dir.mkdir(parents=True, exist_ok=True)
    split_folders_into_gzip_archives(extract_dir, tar_output_dir, icaos)
    if not icaos:
        print("No ICAOs found")
        sys.exit(1)
    
    print(f"\nDone! Extract dir: {extract_dir}")
    print(f"Total ICAOs: {len(icaos)}")


if __name__ == "__main__":
    main()
