"""
Downloads adsb.lol data and writes to Parquet files.

This file contains utility functions for downloading and processing adsb.lol trace data.
Used by the historical ADS-B processing pipeline.
"""
import datetime as dt
import gzip
import os
import re
import resource
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime
import time
import orjson
import pyarrow as pa
import pyarrow.parquet as pq
from pathlib import Path


# ============================================================================
# Configuration
# ============================================================================

OUTPUT_DIR = Path("./data/output")
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
        retry_delay = 60*5
        
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
                            print(f"Waiting {retry_delay} seconds before retry")
                            time.sleep(retry_delay)
                        else:
                            print(f"Giving up after {max_retries} attempts")
                            return releases
            except urllib.error.HTTPError as e:
                # 404 means the repo/page does not exist. Retrying cannot change that,
                # and 10 attempts x 5 min burns ~45 min of runner time to learn nothing.
                if e.code == 404:
                    print(f"Not found (HTTP 404): {BASE_URL}?page={page} - not retrying")
                    return releases
                print(f"Request exception (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"Waiting {retry_delay} seconds before retry")
                    time.sleep(retry_delay)
                else:
                    print(f"Giving up after {max_retries} attempts")
                    return releases
            except Exception as e:
                print(f"Request exception (attempt {attempt}/{max_retries}): {e}")
                if attempt < max_retries:
                    print(f"Waiting {retry_delay} seconds before retry")
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
        print(f"No releases found for {version_date} in {year} repo, checking {next_year} repo")
        releases = _fetch_releases_from_repo(next_year, version_date)
    
    return releases


def download_asset(asset_url: str, file_path: str, expected_size: int | None = None) -> bool:
    """Download a single release asset with size verification.
    
    Args:
        asset_url: URL to download from
        file_path: Local path to save to
        expected_size: Expected file size in bytes (for verification)
    
    Returns:
        True if download succeeded and size matches (if provided), False otherwise
    """
    os.makedirs(os.path.dirname(file_path) or OUTPUT_DIR, exist_ok=True)
    
    # Check if file exists and has correct size
    if os.path.exists(file_path):
        if expected_size is not None:
            actual_size = os.path.getsize(file_path)
            if actual_size == expected_size:
                print(f"[SKIP] {file_path} already downloaded and verified ({actual_size} bytes).")
                return True
            else:
                print(f"[WARN] {file_path} exists but size mismatch (expected {expected_size}, got {actual_size}). Re-downloading.")
                os.remove(file_path)
        else:
            print(f"[SKIP] {file_path} already downloaded.")
            return True
    
    max_retries = 2
    retry_delay = 30
    timeout_seconds = 140
    
    for attempt in range(1, max_retries + 1):
        print(f"Downloading {asset_url} (attempt {attempt}/{max_retries})")
        try:
            req = urllib.request.Request(asset_url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=timeout_seconds) as response:
                if response.status == 200:
                    with open(file_path, "wb") as file:
                        while True:
                            chunk = response.read(8192)
                            if not chunk:
                                break
                            file.write(chunk)
                    
                    # Verify file size if expected_size was provided
                    if expected_size is not None:
                        actual_size = os.path.getsize(file_path)
                        if actual_size != expected_size:
                            print(f"[ERROR] Size mismatch for {file_path}: expected {expected_size} bytes, got {actual_size} bytes")
                            os.remove(file_path)
                            if attempt < max_retries:
                                print(f"Waiting {retry_delay} seconds before retry")
                                time.sleep(retry_delay)
                                continue
                            return False
                        print(f"Saved {file_path} ({actual_size} bytes, verified)")
                    else:
                        print(f"Saved {file_path}")
                    return True
                else:
                    print(f"Failed to download {asset_url}: {response.status} {response.msg}")
                    if attempt < max_retries:
                        print(f"Waiting {retry_delay} seconds before retry")
                        time.sleep(retry_delay)
                    else:
                        return False
        except urllib.error.HTTPError as e:
            if e.code == 404:
                print(f"404 Not Found: {asset_url}")
                raise Exception(f"Asset not found (404): {asset_url}")
            else:
                print(f"HTTP error occurred (attempt {attempt}/{max_retries}): {e.code} {e.reason}")
                if attempt < max_retries:
                    print(f"Waiting {retry_delay} seconds before retry")
                    time.sleep(retry_delay)
                else:
                    return False
        except urllib.error.URLError as e:
            print(f"URL/Timeout error (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                print(f"Waiting {retry_delay} seconds before retry")
                time.sleep(retry_delay)
            else:
                return False
        except Exception as e:
            print(f"An error occurred (attempt {attempt}/{max_retries}): {e}")
            if attempt < max_retries:
                print(f"Waiting {retry_delay} seconds before retry")
                time.sleep(retry_delay)
            else:
                return False
    
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
        )
        cat_proc.stdout.close()
        cat_stderr = cat_proc.stderr.read().decode() if cat_proc.stderr else ""
        cat_proc.wait()
        
        if cat_stderr:
            print(f"cat stderr: {cat_stderr}")
        
        tar_stderr = result.stderr.decode() if result.stderr else ""
        if result.returncode != 0:
            # GNU tar exits non-zero for format issues that BSD tar silently
            # tolerates (e.g. trailing junk after the last valid entry).
            # Check whether files were actually extracted before giving up.
            extracted_items = os.listdir(extract_dir)
            if extracted_items:
                print(f"[WARN] tar exited {result.returncode} but extracted "
                      f"{len(extracted_items)} items — treating as success")
                if tar_stderr:
                    print(f"tar stderr: {tar_stderr}")
            else:
                print(f"Failed to extract split archive (tar exit {result.returncode})")
                if tar_stderr:
                    print(f"tar stderr: {tar_stderr}")
                shutil.rmtree(extract_dir, ignore_errors=True)
                return False
        
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
    except Exception as e:
        print(f"Failed to extract split archive: {e}")
        shutil.rmtree(extract_dir, ignore_errors=True)
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
    
    print(f"Creating parquet for {version_date}")
    rows_processed = process_version_date(version_date, keep_folders)
    
    if rows_processed > 0 and parquet_path.exists():
        return parquet_path
    else:
        return None
