import zipfile
from pathlib import Path
from datetime import datetime, timezone
date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

out_dir = Path("data/faa_releasable")
out_dir.mkdir(parents=True, exist_ok=True)
zip_name = f"ReleasableAircraft_{date_str}.zip"
csv_name = f"Master_{date_str}.csv"

zip_path = out_dir / zip_name
csv_path = out_dir / csv_name

# URL and paths
url = "https://registry.faa.gov/database/ReleasableAircraft.zip"
from urllib.request import Request, urlopen

req = Request(
    url,
    headers={"User-Agent": "Mozilla/5.0"},
    method="GET",
)

with urlopen(req, timeout=120) as r:
    body = r.read()
    zip_path.write_bytes(body)

from derive_from_faa_master_txt import convert_faa_master_txt_to_csv
convert_faa_master_txt_to_csv(zip_path, csv_path)
