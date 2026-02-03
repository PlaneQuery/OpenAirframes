from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Optional
import re
import urllib.request
import urllib.error
import json


REPO = "PlaneQuery/planequery-aircraft"
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


def get_latest_release_assets(repo: str = REPO, github_token: Optional[str] = None) -> list[ReleaseAsset]:
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "planequery-aircraft-downloader/1.0",
    }
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    payload = _http_get_json(url, headers=headers)
    assets = []
    for a in payload.get("assets", []):
        assets.append(
            ReleaseAsset(
                name=a["name"],
                download_url=a["browser_download_url"],
                size=int(a.get("size", 0)),
            )
        )
    return assets


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
        "User-Agent": "planequery-aircraft-downloader/1.0",
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
    Download the latest planequery_aircraft_*.csv file from the latest GitHub release.

    Args:
        output_dir: Directory to save the downloaded file (default: "downloads")
        github_token: Optional GitHub token for authentication
        repo: GitHub repository in format "owner/repo" (default: REPO)

    Returns:
        Path to the downloaded file
    """
    assets = get_latest_release_assets(repo, github_token=github_token)
    asset = pick_asset(assets, name_regex=r"^planequery_aircraft_.*\.csv$")
    saved_to = download_asset(asset, output_dir / asset.name, github_token=github_token)
    print(f"Downloaded: {asset.name} ({asset.size} bytes) -> {saved_to}")
    return saved_to

def get_latest_aircraft_csv_df():
    csv_path = download_latest_aircraft_csv()
    import pandas as pd
    df = pd.read_csv(csv_path, dtype={'transponder_code': str, 
           'unique_regulatory_id': str, 
           'registrant_county': str})
    df = df.fillna("")
    # Extract date from filename pattern: planequery_aircraft_{date}_{date}.csv
    match = re.search(r"planequery_aircraft_(\d{4}-\d{2}-\d{2})_", str(csv_path))
    if not match:
        raise ValueError(f"Could not extract date from filename: {csv_path.name}")
    
    date_str = match.group(1)
    return df, date_str

if __name__ == "__main__":
    download_latest_aircraft_csv()
