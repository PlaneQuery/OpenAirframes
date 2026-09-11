from pathlib import Path
from datetime import datetime, timezone, timedelta
import argparse

parser = argparse.ArgumentParser(description="Create daily FAA release")
parser.add_argument("--date", type=str, help="Date to process (YYYY-MM-DD format, default: today)")
parser.add_argument("--allow-bootstrap", action="store_true",
                    help="Permit rebuilding from a single day when no published asset is found. "
                         "Onboarding only: a missing asset is otherwise indistinguishable from a "
                         "transient outage, and rebuilding would erase the accumulated history.")
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

# Only a genuine first run may rebuild from a single day. A rate limit, a parse error or a
# non-monotonic download_date must stop the run: this file becomes tomorrow's base, so
# silently republishing one day erases the accumulated history.
try:
    df_base, start_date_str = get_latest_aircraft_faa_csv_df()
except FileNotFoundError as e:
    if not args.allow_bootstrap:
        raise SystemExit(
            f"No published FAA asset found: {e}\n"
            "This is indistinguishable from a transient outage, and rebuilding from one day "
            "would erase the accumulated history. Pass --allow-bootstrap when onboarding."
        ) from None
    print(f"Bootstrapping FAA from today only (--allow-bootstrap): {e}")
    df_base = None
    start_date_str = date_str

if df_base is not None:
    df_base = concat_faa_historical_df(df_base, df_new)
    assert df_base['download_date'].is_monotonic_increasing, "download_date is not monotonic increasing"
else:
    df_base = df_new

df_base.to_csv(OUT_ROOT / f"openairframes_faa_{start_date_str}_{date_str}.csv", index=False)