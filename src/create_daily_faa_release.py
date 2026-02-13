from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse

parser = argparse.ArgumentParser(description="Create daily FAA release")
parser.add_argument("--date", type=str, help="Date to process (YYYY-MM-DD format, default: today)")
args = parser.parse_args()

if args.date:
    date_str = args.date
else:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

out_dir = Path("data/faa_releasable")
out_dir.mkdir(parents=True, exist_ok=True)
zip_name = f"ReleasableAircraft_{date_str}.zip"

zip_path = out_dir / zip_name
if not zip_path.exists():
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

OUT_ROOT = Path("data/openairframes")
OUT_ROOT.mkdir(parents=True, exist_ok=True)
from derive_from_faa_master_txt import convert_faa_master_txt_to_df, concat_faa_historical_df
from get_latest_release import get_latest_aircraft_faa_csv_df
df_new = convert_faa_master_txt_to_df(zip_path, date_str)

try:
    df_base, start_date_str = get_latest_aircraft_faa_csv_df()
    df_base = concat_faa_historical_df(df_base, df_new)
    assert df_base['download_date'].is_monotonic_increasing, "download_date is not monotonic increasing"
except Exception as e:
    print(f"No existing FAA release found, using only new data: {e}")
    df_base = df_new
    start_date_str = date_str

df_base.to_csv(OUT_ROOT / f"openairframes_faa_{start_date_str}_{date_str}.csv", index=False)