from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import re
import urllib.request
import urllib.error
import json


REPO = "PlaneQuery/openairframes"
LATEST_RELEASE_URL = f"https://api.github.com/repos/{REPO}/releases/latest"


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    download_url: str
    size: int  # bytes


def _http_get_json(url: str, headers: dict[str, str]) -> dict:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = resp.read()
    return json.loads(data.decode("utf-8"))


def get_releases(repo: str = REPO, github_token: Optional[str] = None, per_page: int = 30) -> list[dict]:
    """Get a list of releases from the repository."""
    url = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openairframes-downloader/1.0",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    return _http_get_json(url, headers=headers)


def get_release_assets_from_release_data(release_data: dict) -> list[ReleaseAsset]:
    """Extract assets from a release data dictionary."""
    assets = []
    for a in release_data.get("assets", []):
        assets.append(
            ReleaseAsset(
                name=a["name"],
                download_url=a["browser_download_url"],
                size=int(a.get("size", 0)),
            )
        )
    return assets


def get_latest_release_assets(repo: str = REPO, github_token: Optional[str] = None) -> list[ReleaseAsset]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "openairframes-downloader/1.0",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    payload = _http_get_json(url, headers=headers)
    return get_release_assets_from_release_data(payload)


def pick_asset(
    assets: Iterable[ReleaseAsset],
    *,
    exact_name: Optional[str] = None,
    name_regex: Optional[str] = None,
) -> ReleaseAsset:
    assets = list(assets)

    if exact_name:
        for a in assets:
            if a.name == exact_name:
                return a
        raise FileNotFoundError(f"No asset exactly named {exact_name!r}. Available: {[a.name for a in assets]}")

    if name_regex:
        rx = re.compile(name_regex)
        matches = [a for a in assets if rx.search(a.name)]
        if not matches:
            raise FileNotFoundError(f"No asset matched regex {name_regex!r}. Available: {[a.name for a in assets]}")
        if len(matches) > 1:
            raise FileExistsError(f"Regex {name_regex!r} matched multiple assets: {[m.name for m in matches]}")
        return matches[0]

    raise ValueError("Provide either exact_name=... or name_regex=...")


def download_asset(asset: ReleaseAsset, out_path: Path, github_token: Optional[str] = None) -> Path:
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    headers = {
        "User-Agent": "openairframes-downloader/1.0",
        "Accept": "application/octet-stream",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    req = urllib.request.Request(asset.download_url, headers=headers, method="GET")

    try:
        with urllib.request.urlopen(req, timeout=300) as resp, out_path.open("wb") as f:
            # Stream download
            while True:
                chunk = resp.read(1024 * 1024)  # 1 MiB
                if not chunk:
                    break
                f.write(chunk)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        raise RuntimeError(f"HTTPError {e.code} downloading {asset.name}: {body[:500]}") from e

    return out_path


def download_latest_aircraft_csv(
    output_dir: Path = Path("downloads"),
    github_token: Optional[str] = None,
    repo: str = REPO,
) -> Path:
    """
    Download the latest openairframes_faa_*.csv file from the latest GitHub release.

    Args:
        output_dir: Directory to save the downloaded file (default: "downloads")
        github_token: Optional GitHub token for authentication
        repo: GitHub repository in format "owner/repo" (default: REPO)

    Returns:
        Path to the downloaded file
    """
    output_dir = Path(output_dir)
    assets = get_latest_release_assets(repo, github_token=github_token)
    try:
        asset = pick_asset(assets, name_regex=r"^openairframes_faa_.*\.csv$")
    except FileNotFoundError:
        # Fallback to old naming pattern
        asset = pick_asset(assets, name_regex=r"^openairframes_\d{4}-\d{2}-\d{2}_.*\.csv$")
    saved_to = download_asset(asset, output_dir / asset.name, github_token=github_token)
    print(f"Downloaded: {asset.name} ({asset.size} bytes) -> {saved_to}")
    return saved_to

def get_latest_aircraft_faa_csv_df():
    csv_path = download_latest_aircraft_csv()
    import pandas as pd
    df = pd.read_csv(csv_path, dtype={'transponder_code': str, 
           'unique_regulatory_id': str, 
           'registrant_county': str})
    df = df.fillna("")
    # Extract start date from filename pattern: openairframes_faa_{start_date}_{end_date}.csv
    match = re.search(r"openairframes_faa_(\d{4}-\d{2}-\d{2})_", str(csv_path))
    if not match:
        # Fallback to old naming pattern: openairframes_{start_date}_{end_date}.csv
        match = re.search(r"openairframes_(\d{4}-\d{2}-\d{2})_", str(csv_path))
    if not match:
        raise ValueError(f"Could not extract date from filename: {csv_path.name}")
    
    date_str = match.group(1)
    return df, date_str


def download_latest_aircraft_adsb_csv(
    output_dir: Path = Path("downloads"),
    github_token: Optional[str] = None,
    repo: str = REPO,
) -> Path:
    """
    Download the latest openairframes_adsb_*.csv file from GitHub releases.
    If the latest release doesn't have the file, searches previous releases.

    Args:
        output_dir: Directory to save the downloaded file (default: "downloads")
        github_token: Optional GitHub token for authentication
        repo: GitHub repository in format "owner/repo" (default: REPO)

    Returns:
        Path to the downloaded file
    """
    output_dir = Path(output_dir)
    
    # Get multiple releases
    releases = get_releases(repo, github_token=github_token, per_page=30)
    
    # Try each release until we find one with the matching asset
    for release in releases:
        assets = get_release_assets_from_release_data(release)
        try:
            asset = pick_asset(assets, name_regex=r"^openairframes_adsb_.*\.csv(\.gz)?$")
            saved_to = download_asset(asset, output_dir / asset.name, github_token=github_token)
            print(f"Downloaded: {asset.name} ({asset.size} bytes) -> {saved_to}")
            return saved_to
        except FileNotFoundError:
            # This release doesn't have the matching asset, try the next one
            continue
    
    raise FileNotFoundError(
        f"No release in the last 30 releases has an asset matching 'openairframes_adsb_.*\\.csv(\\.gz)?$'"
    )

import polars as pl
def get_latest_aircraft_adsb_csv_df():
    """Download and load the latest ADS-B CSV from GitHub releases.
    
    Returns:
        tuple: (df, start_date, end_date) where dates are in YYYY-MM-DD format
    """
    import re
    
    csv_path = download_latest_aircraft_adsb_csv()
    df = pl.read_csv(csv_path, null_values=[""])
    
    # Parse time column: values like "2025-12-31T00:00:00.040" or "2025-05-11T15:15:50.540+0000"
    # Try with timezone first (convert to naive), then without timezone
    df = df.with_columns(
        pl.col("time").str.strptime(pl.Datetime("ms"), "%Y-%m-%dT%H:%M:%S%.f%z", strict=False)
            .dt.replace_time_zone(None)  # Convert to naive datetime first
            .fill_null(pl.col("time").str.strptime(pl.Datetime("ms"), "%Y-%m-%dT%H:%M:%S%.f", strict=False))
    )

    # Cast dbFlags and year to strings to match the schema used in compress functions
    for col in ['dbFlags', 'year']:
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Utf8))
    
    # Fill nulls with empty strings for string columns
    for col in df.columns:
        if df[col].dtype == pl.Utf8:
            df = df.with_columns(pl.col(col).fill_null(""))
    
    # Extract start and end dates from filename pattern: openairframes_adsb_{start_date}_{end_date}.csv[.gz]
    match = re.search(r"openairframes_adsb_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv", str(csv_path))
    if not match:
        raise ValueError(f"Could not extract dates from filename: {csv_path.name}")
    
    start_date = match.group(1)
    end_date = match.group(2)
    print(df.columns)
    print(df.dtypes)
    return df, start_date, end_date



if __name__ == "__main__":
    download_latest_aircraft_csv()
    download_latest_aircraft_adsb_csv()