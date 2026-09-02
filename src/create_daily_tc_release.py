from pathlib import Path
from datetime import datetime, timezone
import argparse

parser = argparse.ArgumentParser(description="Create daily Transport Canada release")
parser.add_argument("--date", type=str, help="Date to process (YYYY-MM-DD format, default: today)")
args = parser.parse_args()

if args.date:
    date_str = args.date
else:
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

out_dir = Path("data/tc_ccarcs")
out_dir.mkdir(parents=True, exist_ok=True)
zip_name = f"ccarcsdb_{date_str}.zip"

zip_path = out_dir / zip_name
if not zip_path.exists():
    url = "https://wwwapps.tc.gc.ca/saf-sec-sur/2/ccarcs-riacc/download/ccarcsdb.zip"
    from urllib.request import Request, urlopen

    # CCARCS 403s a default urllib agent. Any browser-like UA works; the exact
    # version string is not load-bearing.
    req = Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            )
        },
        method="GET",
    )

    with urlopen(req, timeout=120) as r:
        body = r.read()
    # TC serves an HTML maintenance page with a 200, which would otherwise be cached
    # under a .zip name and re-read on every later run.
    if body[:2] != b"PK":
        raise RuntimeError(f"{url} did not return a zip (got {body[:40]!r})")
    tmp_path = zip_path.with_suffix(".part")
    tmp_path.write_bytes(body)
    tmp_path.replace(zip_path)

OUT_ROOT = Path("data/openairframes")
OUT_ROOT.mkdir(parents=True, exist_ok=True)
from derive_from_tc_ccarcs import convert_tc_ccarcs_to_df
# Named for FAA but column-agnostic: fingerprints every column except download_date.
from derive_from_faa_master_txt import concat_faa_historical_df
from get_latest_release import get_latest_aircraft_tc_csv_df
df_new = convert_tc_ccarcs_to_df(zip_path, date_str)

# Only a genuine first run may rebuild from a single day. Every other failure -- a rate
# limit, a schema change, a truncated download -- must stop the run, because this file
# becomes tomorrow's base and silently republishing one day erases the whole history.
try:
    df_base, start_date_str = get_latest_aircraft_tc_csv_df()
except FileNotFoundError as e:
    print(f"No existing Transport Canada release found, bootstrapping from today only: {e}")
    df_base = None
    start_date_str = date_str

if df_base is not None:
    missing = set(df_base.columns) ^ set(df_new.columns)
    if missing:
        raise SystemExit(f"Column set changed since the last release: {sorted(missing)}")
    df_base = concat_faa_historical_df(df_base, df_new)
    assert df_base['download_date'].is_monotonic_increasing, "download_date is not monotonic increasing"
else:
    df_base = df_new

df_base.to_csv(OUT_ROOT / f"openairframes_tc_{start_date_str}_{date_str}.csv", index=False)
