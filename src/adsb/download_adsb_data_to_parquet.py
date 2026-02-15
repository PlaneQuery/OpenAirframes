"""
Downloads adsb.lol data and writes to Parquet files.

Usage:
    python -m src.process_historical_adsb_data.download_to_parquet 2025-01-01 2025-01-02

This will download trace data for the specified date range and output Parquet files.

This file is self-contained and does not import from other project modules.
"""
import gc
import glob
import gzip
import resource
import shutil
import sys
import logging
import time
import re
import signal
import concurrent.futures
import subprocess
import os
import argparse
import datetime as dt
from datetime import datetime, timedelta, timezone
import urllib.request
import urllib.error

import orjson
import pyarrow as pa
import pyarrow.parquet as pq


# ============================================================================
# Configuration
# ============================================================================

OUTPUT_DIR = "./data/output"
os.makedirs(OUTPUT_DIR, exist_ok=True)

PARQUET_DIR = os.path.join(OUTPUT_DIR, "parquet_output")
os.makedirs(PARQUET_DIR, exist_ok=True)

TOKEN = os.environ.get('GITHUB_TOKEN')  # Optional: for higher GitHub API rate limits
HEADERS = {"Authorization": f"token {TOKEN}"} if TOKEN else {}


def get_resource_usage() -> str:
    """Get current RAM and disk usage as a formatted string."""
    # RAM usage (RSS = Resident Set Size)
    ram_bytes = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    # On macOS, ru_maxrss is in bytes; on Linux, it's in KB
    if sys.platform == 'darwin':
        ram_gb = ram_bytes / (1024**3)
    else:
        ram_gb = ram_bytes / (1024**2)  # Convert KB to GB
    
    # Disk usage
    disk = shutil.disk_usage('.')
    disk_free_gb = disk.free / (1024**3)
    disk_total_gb = disk.total / (1024**3)
    
    return f"RAM: {ram_gb:.2f}GB | Disk: {disk_free_gb:.1f}GB free / {disk_total_gb:.1f}GB total"


# ============================================================================
# GitHub Release Fetching and Downloading
# ============================================================================

class DownloadTimeoutException(Exception):
    pass


def timeout_handler(signum, frame):
    raise DownloadTimeoutException("Download timed out after 40 seconds")


def _fetch_releases_from_repo(year: str, version_date: str) -> list:
    """Fetch GitHub releases for a given version date from a specific year's adsblol repo."""
    BASE_URL = f"https://api.github.com/repos/adsblol/globe_history_{year}/releases"
    PATTERN = rf"^{re.escape(version_date)}-planes-readsb-prod-\d+(tmp)?$"
    releases = []
    page = 1
    
    while True:
        max_retries = 10
        retry_delay = 60
        
        for attempt in range(1, max_retries + 1):
            try:
                req = urllib.request.Request(f"{BASE_URL}?page={page}", headers=HEADERS)
                with urllib.request.urlopen(req) as response:
                    if response.status == 200:
                        data = orjson.loads(response.read())
                        break
                    else:
                        print(f"Failed to fetch releases (attempt {attempt}/{max_retries}): {response.status} {response.reason}")
                        if attempt < max_retries:
                            print(f"Waiting {retry_delay} seconds before retry...")
                            time.sleep(retry_delay)
                        else:
                            print(f"Giving up after {max_retries} attempts")
                            return releases
            except Exception as e:
                print(f"Request exception (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"Waiting {retry_delay} seconds before retry...")
                    time.sleep(retry_delay)
                else:
                    print(f"Giving up after {max_retries} attempts")
                    return releases
        if not data:
            break
        for release in data:
            if re.match(PATTERN, release["tag_name"]):
                releases.append(release)
        page += 1
    return releases


def fetch_releases(version_date: str) -> list:
    """Fetch GitHub releases for a given version date from adsblol.
    
    For Dec 31 dates, if no releases are found in the current year's repo,
    also checks the next year's repo (adsblol sometimes publishes Dec 31
    data in the following year's repository).
    """
    year = version_date.split('.')[0][1:]
    releases = _fetch_releases_from_repo(year, version_date)
    
    # For last day of year, also check next year's repo if nothing found
    if not releases and version_date.endswith(".12.31"):
        next_year = str(int(year) + 1)
        print(f"No releases found for {version_date} in {year} repo, checking {next_year} repo...")
        releases = _fetch_releases_from_repo(next_year, version_date)
    
    return releases


def download_asset(asset_url: str, file_path: str) -> bool:
    """Download a single release asset."""
    os.makedirs(os.path.dirname(file_path) or OUTPUT_DIR, exist_ok=True)
    
    if os.path.exists(file_path):
        print(f"[SKIP] {file_path} already downloaded.")
        return True
    
    print(f"Downloading {asset_url}...")
    try:
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(40)  # 40-second timeout
        
        req = urllib.request.Request(asset_url, headers=HEADERS)
        with urllib.request.urlopen(req) as response:
            signal.alarm(0)
            
            if response.status == 200:
                with open(file_path, "wb") as file:
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break
                        file.write(chunk)
                print(f"Saved {file_path}")
                return True
            else:
                print(f"Failed to download {asset_url}: {response.status} {response.msg}")
                return False
    except DownloadTimeoutException as e:
        print(f"Download aborted for {asset_url}: {e}")
        return False
    except Exception as e:
        print(f"An error occurred while downloading {asset_url}: {e}")
        return False


def extract_split_archive(file_paths: list, extract_dir: str) -> bool:
    """
    Extracts a split archive by concatenating the parts using 'cat'
    and then extracting with 'tar' in one pipeline.
    Deletes the tar files immediately after extraction to save disk space.
    """
    if os.path.isdir(extract_dir):
        print(f"[SKIP] Extraction directory already exists: {extract_dir}")
        return True
    
    def sort_key(path: str):
        base = os.path.basename(path)
        parts = base.rsplit('.', maxsplit=1)
        if len(parts) == 2:
            suffix = parts[1]
            if suffix.isdigit():
                return (0, int(suffix))
            if re.fullmatch(r'[a-zA-Z]+', suffix):
                return (1, suffix)
        return (2, base)
    
    file_paths = sorted(file_paths, key=sort_key)
    os.makedirs(extract_dir, exist_ok=True)
    
    try:
        cat_proc = subprocess.Popen(
            ["cat"] + file_paths,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )
        tar_cmd = ["tar", "xf", "-", "-C", extract_dir, "--strip-components=1"]
        result = subprocess.run(
            tar_cmd,
            stdin=cat_proc.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        cat_proc.stdout.close()
        cat_stderr = cat_proc.stderr.read().decode() if cat_proc.stderr else ""
        cat_proc.wait()
        
        if cat_stderr:
            print(f"cat stderr: {cat_stderr}")
        
        print(f"Successfully extracted archive to {extract_dir}")
        
        # Delete tar files immediately after extraction
        for tar_file in file_paths:
            try:
                os.remove(tar_file)
                print(f"Deleted tar file: {tar_file}")
            except Exception as e:
                print(f"Failed to delete {tar_file}: {e}")
        
        # Check disk usage after deletion
        disk = shutil.disk_usage('.')
        free_gb = disk.free / (1024**3)
        print(f"Disk space after tar deletion: {free_gb:.1f}GB free")
        
        return True
    except subprocess.CalledProcessError as e:
        stderr_output = e.stderr.decode() if e.stderr else ""
        print(f"Failed to extract split archive: {e}")
        if stderr_output:
            print(f"tar stderr: {stderr_output}")
        return False


# ============================================================================
# Trace File Processing (with alt_baro/on_ground handling)
# ============================================================================

ALLOWED_DATA_SOURCE = {'', 'adsb.lol', 'adsbexchange', 'airplanes.live'}


def process_file(filepath: str) -> list:
    """
    Process a single trace file and return list of rows.
    Handles alt_baro/on_ground: if altitude == "ground", on_ground=True and alt_baro=None.
    """
    insert_rows = []
    with gzip.open(filepath, 'rb') as f:
        data = orjson.loads(f.read())
        icao = data.get('icao', None)
        if icao is None:
            print(f"Skipping file {filepath} as it does not contain 'icao'")
            return []
        
        r = data.get('r', "")
        t = data.get('t', "")
        dbFlags = data.get('dbFlags', 0)
        noRegData = data.get('noRegData', False)
        ownOp = data.get('ownOp', "")
        year = int(data.get('year', 0))
        timestamp = data.get('timestamp', None)
        desc = data.get('desc', "")
        trace_data = data.get('trace', None)
        
        if timestamp is None or trace_data is None:
            print(f"Skipping file {filepath} as it does not contain 'timestamp' or 'trace'")
            return []
        
        for row in trace_data:
            time_offset = row[0]
            lat = row[1]
            lon = row[2]
            altitude = row[3]
            
            # Handle alt_baro/on_ground
            alt_baro = None
            on_ground = False
            if type(altitude) is str and altitude == "ground":
                on_ground = True
            elif type(altitude) is int:
                alt_baro = altitude
            elif type(altitude) is float:
                alt_baro = int(altitude)
            
            ground_speed = row[4]
            track_degrees = row[5]
            flags = row[6]
            vertical_rate = row[7]
            aircraft = row[8]
            source = row[9]
            data_source_value = "adsb.lol" if "adsb.lol" in ALLOWED_DATA_SOURCE else ""
            geometric_altitude = row[10]
            geometric_vertical_rate = row[11]
            indicated_airspeed = row[12]
            roll_angle = row[13]
            
            time_val = timestamp + time_offset
            dt64 = dt.datetime.fromtimestamp(time_val, tz=dt.timezone.utc)
            
            # Prepare base fields
            inserted_row = [
                dt64, icao, r, t, dbFlags, noRegData, ownOp, year, desc,
                lat, lon, alt_baro, on_ground, ground_speed, track_degrees,
                flags, vertical_rate
            ]
            next_part = [
                source, geometric_altitude, geometric_vertical_rate,
                indicated_airspeed, roll_angle
            ]
            inserted_row.extend(next_part)
            
            if aircraft is None or type(aircraft) is not dict:
                aircraft = dict()
            
            aircraft_data = {
                'alert': aircraft.get('alert', None),
                'alt_geom': aircraft.get('alt_geom', None),
                'gva': aircraft.get('gva', None),
                'nac_p': aircraft.get('nac_p', None),
                'nac_v': aircraft.get('nac_v', None),
                'nic': aircraft.get('nic', None),
                'nic_baro': aircraft.get('nic_baro', None),
                'rc': aircraft.get('rc', None),
                'sda': aircraft.get('sda', None),
                'sil': aircraft.get('sil', None),
                'sil_type': aircraft.get('sil_type', ""),
                'spi': aircraft.get('spi', None),
                'track': aircraft.get('track', None),
                'type': aircraft.get('type', ""),
                'version': aircraft.get('version', None),
                'category': aircraft.get('category', ''),
                'emergency': aircraft.get('emergency', ''),
                'flight': aircraft.get('flight', ""),
                'squawk': aircraft.get('squawk', ""),
                'baro_rate': aircraft.get('baro_rate', None),
                'nav_altitude_fms': aircraft.get('nav_altitude_fms', None),
                'nav_altitude_mcp': aircraft.get('nav_altitude_mcp', None),
                'nav_modes': aircraft.get('nav_modes', []),
                'nav_qnh': aircraft.get('nav_qnh', None),
                'geom_rate': aircraft.get('geom_rate', None),
                'ias': aircraft.get('ias', None),
                'mach': aircraft.get('mach', None),
                'mag_heading': aircraft.get('mag_heading', None),
                'oat': aircraft.get('oat', None),
                'roll': aircraft.get('roll', None),
                'tas': aircraft.get('tas', None),
                'tat': aircraft.get('tat', None),
                'true_heading': aircraft.get('true_heading', None),
                'wd': aircraft.get('wd', None),
                'ws': aircraft.get('ws', None),
                'track_rate': aircraft.get('track_rate', None),
                'nav_heading': aircraft.get('nav_heading', None)
            }
            
            aircraft_list = list(aircraft_data.values())
            inserted_row.extend(aircraft_list)
            inserted_row.append(data_source_value)
            
            insert_rows.append(inserted_row)
    
    if insert_rows:
        # print(f"Got {len(insert_rows)} rows from {filepath}")
        return insert_rows
    else:
        return []


# ============================================================================
# Parquet Writing
# ============================================================================

# Column names matching the order of data in inserted_row
COLUMNS = [
    "time", "icao",
    "r", "t", "dbFlags", "noRegData", "ownOp", "year", "desc",
    "lat", "lon", "alt_baro", "on_ground", "ground_speed", "track_degrees",
    "flags", "vertical_rate", "source", "geometric_altitude",
    "geometric_vertical_rate", "indicated_airspeed", "roll_angle",
    "aircraft_alert", "aircraft_alt_geom", "aircraft_gva", "aircraft_nac_p",
    "aircraft_nac_v", "aircraft_nic", "aircraft_nic_baro", "aircraft_rc",
    "aircraft_sda", "aircraft_sil", "aircraft_sil_type", "aircraft_spi",
    "aircraft_track", "aircraft_type", "aircraft_version", "aircraft_category",
    "aircraft_emergency", "aircraft_flight", "aircraft_squawk",
    "aircraft_baro_rate", "aircraft_nav_altitude_fms", "aircraft_nav_altitude_mcp",
    "aircraft_nav_modes", "aircraft_nav_qnh", "aircraft_geom_rate",
    "aircraft_ias", "aircraft_mach", "aircraft_mag_heading", "aircraft_oat",
    "aircraft_roll", "aircraft_tas", "aircraft_tat", "aircraft_true_heading",
    "aircraft_wd", "aircraft_ws", "aircraft_track_rate", "aircraft_nav_heading",
    "data_source",
]


OS_CPU_COUNT = os.cpu_count() or 1
MAX_WORKERS = OS_CPU_COUNT if OS_CPU_COUNT > 4 else 1
CHUNK_SIZE = MAX_WORKERS * 500  # Reduced for lower RAM usage
BATCH_SIZE = 250_000  # Fixed size for predictable memory usage (~500MB per batch)

# PyArrow schema for efficient Parquet writing
PARQUET_SCHEMA = pa.schema([
    ("time", pa.timestamp("ms", tz="UTC")),
    ("icao", pa.string()),
    ("r", pa.string()),
    ("t", pa.string()),
    ("dbFlags", pa.int32()),
    ("noRegData", pa.bool_()),
    ("ownOp", pa.string()),
    ("year", pa.uint16()),
    ("desc", pa.string()),
    ("lat", pa.float64()),
    ("lon", pa.float64()),
    ("alt_baro", pa.int32()),
    ("on_ground", pa.bool_()),
    ("ground_speed", pa.float32()),
    ("track_degrees", pa.float32()),
    ("flags", pa.uint32()),
    ("vertical_rate", pa.int32()),
    ("source", pa.string()),
    ("geometric_altitude", pa.int32()),
    ("geometric_vertical_rate", pa.int32()),
    ("indicated_airspeed", pa.int32()),
    ("roll_angle", pa.float32()),
    ("aircraft_alert", pa.int64()),
    ("aircraft_alt_geom", pa.int64()),
    ("aircraft_gva", pa.int64()),
    ("aircraft_nac_p", pa.int64()),
    ("aircraft_nac_v", pa.int64()),
    ("aircraft_nic", pa.int64()),
    ("aircraft_nic_baro", pa.int64()),
    ("aircraft_rc", pa.int64()),
    ("aircraft_sda", pa.int64()),
    ("aircraft_sil", pa.int64()),
    ("aircraft_sil_type", pa.string()),
    ("aircraft_spi", pa.int64()),
    ("aircraft_track", pa.float64()),
    ("aircraft_type", pa.string()),
    ("aircraft_version", pa.int64()),
    ("aircraft_category", pa.string()),
    ("aircraft_emergency", pa.string()),
    ("aircraft_flight", pa.string()),
    ("aircraft_squawk", pa.string()),
    ("aircraft_baro_rate", pa.int64()),
    ("aircraft_nav_altitude_fms", pa.int64()),
    ("aircraft_nav_altitude_mcp", pa.int64()),
    ("aircraft_nav_modes", pa.list_(pa.string())),
    ("aircraft_nav_qnh", pa.float64()),
    ("aircraft_geom_rate", pa.int64()),
    ("aircraft_ias", pa.int64()),
    ("aircraft_mach", pa.float64()),
    ("aircraft_mag_heading", pa.float64()),
    ("aircraft_oat", pa.int64()),
    ("aircraft_roll", pa.float64()),
    ("aircraft_tas", pa.int64()),
    ("aircraft_tat", pa.int64()),
    ("aircraft_true_heading", pa.float64()),
    ("aircraft_wd", pa.int64()),
    ("aircraft_ws", pa.int64()),
    ("aircraft_track_rate", pa.float64()),
    ("aircraft_nav_heading", pa.float64()),
    ("data_source", pa.string()),
])


def collect_trace_files_with_find(root_dir):
    """Find all trace_full_*.json files in the extracted directory."""
    trace_dict: dict[str, str] = {}
    cmd = ['find', root_dir, '-type', 'f', '-name', 'trace_full_*.json']
    
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    if result.returncode != 0:
        print(f"Error executing find: {result.stderr}")
        return trace_dict
    
    for file_path in result.stdout.strip().split('\n'):
        if file_path:
            filename = os.path.basename(file_path)
            if filename.startswith("trace_full_") and filename.endswith(".json"):
                icao = filename[len("trace_full_"):-len(".json")]
                trace_dict[icao] = file_path
                    
    return trace_dict


def generate_version_dates(start_date: str, end_date: str) -> list:
    """Generate a list of dates from start_date to end_date inclusive."""
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    delta = end - start
    return [start + timedelta(days=i) for i in range(delta.days + 1)]


def safe_process(fp):
    """Safely process a file, returning empty list on error."""
    try:
        return process_file(fp)
    except Exception as e:
        logging.error(f"Error processing {fp}: {e}")
        return []


def rows_to_arrow_table(rows: list) -> pa.Table:
    """Convert list of rows to a PyArrow Table directly (no pandas)."""
    # Transpose rows into columns
    columns = list(zip(*rows))
    
    # Build arrays for each column according to schema
    arrays = []
    for i, field in enumerate(PARQUET_SCHEMA):
        col_data = list(columns[i]) if i < len(columns) else [None] * len(rows)
        arrays.append(pa.array(col_data, type=field.type))
    
    return pa.Table.from_arrays(arrays, schema=PARQUET_SCHEMA)


def write_batch_to_parquet(rows: list, version_date: str, batch_idx: int):
    """Write a batch of rows to a Parquet file."""
    if not rows:
        return
    
    table = rows_to_arrow_table(rows)
    
    parquet_path = os.path.join(PARQUET_DIR, f"{version_date}_batch_{batch_idx:04d}.parquet")
    
    pq.write_table(table, parquet_path, compression='snappy')
    
    print(f"Written parquet batch {batch_idx} ({len(rows)} rows) | {get_resource_usage()}")


def merge_parquet_files(version_date: str, delete_batches: bool = True):
    """Merge all batch parquet files for a version_date into a single file using streaming."""
    pattern = os.path.join(PARQUET_DIR, f"{version_date}_batch_*.parquet")
    batch_files = sorted(glob.glob(pattern))
    
    if not batch_files:
        print(f"No batch files found for {version_date}")
        return None
    
    print(f"Merging {len(batch_files)} batch files for {version_date} (streaming)...")
    
    merged_path = os.path.join(PARQUET_DIR, f"{version_date}.parquet")
    total_rows = 0
    
    # Stream write: read one batch at a time to minimize RAM usage
    writer = None
    try:
        for i, f in enumerate(batch_files):
            table = pq.read_table(f)
            total_rows += table.num_rows
            
            if writer is None:
                writer = pq.ParquetWriter(merged_path, table.schema, compression='snappy')
            
            writer.write_table(table)
            
            # Delete batch file immediately after reading to free disk space
            if delete_batches:
                os.remove(f)
            
            # Free memory
            del table
            if (i + 1) % 10 == 0:
                gc.collect()
                print(f"  Merged {i + 1}/{len(batch_files)} batches... | {get_resource_usage()}")
    finally:
        if writer is not None:
            writer.close()
    
    print(f"Merged parquet file written to {merged_path} ({total_rows} total rows) | {get_resource_usage()}")
    
    if delete_batches:
        print(f"Deleted {len(batch_files)} batch files during merge")
    
    gc.collect()
    return merged_path


def process_version_date(version_date: str, keep_folders: bool = False):
    """Download, extract, and process trace files for a single version date."""
    print(f"\nProcessing version_date: {version_date}")
    extract_dir = os.path.join(OUTPUT_DIR, f"{version_date}-planes-readsb-prod-0.tar_0")
    
    def collect_trace_files_for_version_date(vd):
        releases = fetch_releases(vd)
        if len(releases) == 0:
            print(f"No releases found for {vd}.")
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

            # Only download prod-0 if available, else prod-0tmp
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
                result = download_asset(asset_url, file_path)
                if result:
                    downloaded_files.append(file_path)

        extract_split_archive(downloaded_files, extract_dir)
        return collect_trace_files_with_find(extract_dir)

    # Check if files already exist
    pattern = os.path.join(OUTPUT_DIR, f"{version_date}-planes-readsb-prod-0*")
    matches = [p for p in glob.glob(pattern) if os.path.isfile(p)]
    
    if matches:
        print(f"Found existing files for {version_date}:")
        # Prefer non-tmp slices when reusing existing files
        normal_matches = [
            p for p in matches
            if "-planes-readsb-prod-0." in os.path.basename(p)
            and "tmp" not in os.path.basename(p)
        ]
        downloaded_files = normal_matches if normal_matches else matches
        
        extract_split_archive(downloaded_files, extract_dir)
        trace_files = collect_trace_files_with_find(extract_dir)
    else:
        trace_files = collect_trace_files_for_version_date(version_date)
    
    if trace_files is None or len(trace_files) == 0:
        print(f"No trace files found for version_date: {version_date}")
        return 0
    
    file_list = list(trace_files.values())
    
    start_time = time.perf_counter()
    total_num_rows = 0
    batch_rows = []
    batch_idx = 0
    
    # Process files in chunks
    for offset in range(0, len(file_list), CHUNK_SIZE):
        chunk = file_list[offset:offset + CHUNK_SIZE]
        with concurrent.futures.ProcessPoolExecutor(max_workers=MAX_WORKERS) as process_executor:
            for rows in process_executor.map(safe_process, chunk):
                if not rows:
                    continue
                batch_rows.extend(rows)
                
                if len(batch_rows) >= BATCH_SIZE:
                    total_num_rows += len(batch_rows)
                    write_batch_to_parquet(batch_rows, version_date, batch_idx)
                    batch_idx += 1
                    batch_rows = []
                    
                    elapsed = time.perf_counter() - start_time
                    speed = total_num_rows / elapsed if elapsed > 0 else 0
                    print(f"[{version_date}] processed {total_num_rows} rows in {elapsed:.2f}s ({speed:.2f} rows/s)")
        
        gc.collect()
    
    # Final batch
    if batch_rows:
        total_num_rows += len(batch_rows)
        write_batch_to_parquet(batch_rows, version_date, batch_idx)
        elapsed = time.perf_counter() - start_time
        speed = total_num_rows / elapsed if elapsed > 0 else 0
        print(f"[{version_date}] processed {total_num_rows} rows in {elapsed:.2f}s ({speed:.2f} rows/s)")
    
    print(f"Total rows processed for version_date {version_date}: {total_num_rows}")
    
    # Clean up extracted directory immediately after processing (before merging parquet files)
    if not keep_folders and os.path.isdir(extract_dir):
        print(f"Deleting extraction directory with 100,000+ files: {extract_dir}")
        shutil.rmtree(extract_dir)
        print(f"Successfully deleted extraction directory: {extract_dir} | {get_resource_usage()}")
    
    # Merge batch files into a single parquet file
    merge_parquet_files(version_date, delete_batches=True)
    
    return total_num_rows


def create_parquet_for_day(day, keep_folders: bool = False):
    """Create parquet file for a single day.
    
    Args:
        day: datetime object or string in 'YYYY-MM-DD' format
        keep_folders: Whether to keep extracted folders after processing
    
    Returns:
        Path to the created parquet file, or None if failed
    """
    from pathlib import Path
    
    if isinstance(day, str):
        day = datetime.strptime(day, "%Y-%m-%d")
    
    version_date = f"v{day.strftime('%Y.%m.%d')}"
    
    # Check if parquet already exists
    parquet_path = Path(PARQUET_DIR) / f"{version_date}.parquet"
    if parquet_path.exists():
        print(f"Parquet file already exists: {parquet_path}")
        return parquet_path
    
    print(f"Creating parquet for {version_date}...")
    rows_processed = process_version_date(version_date, keep_folders)
    
    if rows_processed > 0 and parquet_path.exists():
        return parquet_path
    else:
        return None


def main(start_date: str, end_date: str, keep_folders: bool = False):
    """Main function to download and convert adsb.lol data to Parquet."""
    version_dates = [f"v{date.strftime('%Y.%m.%d')}" for date in generate_version_dates(start_date, end_date)]
    print(f"Processing dates: {version_dates}")
    
    total_rows_all = 0
    for version_date in version_dates:
        rows_processed = process_version_date(version_date, keep_folders)
        total_rows_all += rows_processed
    
    print(f"\n=== Summary ===")
    print(f"Total dates processed: {len(version_dates)}")
    print(f"Total rows written to Parquet: {total_rows_all}")
    print(f"Parquet files location: {PARQUET_DIR}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, force=True)
    
    parser = argparse.ArgumentParser(
        description="Download adsb.lol data and write to Parquet files"
    )
    parser.add_argument("start_date", type=str, help="Start date in YYYY-MM-DD format")
    parser.add_argument("end_date", type=str, help="End date in YYYY-MM-DD format")
    parser.add_argument("--keep-folders", action="store_true", 
                        help="Keep extracted folders after processing")
    
    args = parser.parse_args()
    
    main(args.start_date, args.end_date, args.keep_folders)
