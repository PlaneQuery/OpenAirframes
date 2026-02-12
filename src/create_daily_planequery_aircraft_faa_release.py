from pathlib import Path
from datetime import datetime, timezone
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

OUT_ROOT = Path("data/planequery_aircraft")
OUT_ROOT.mkdir(parents=True, exist_ok=True)
from derive_from_faa_master_txt import convert_faa_master_txt_to_df, concat_faa_historical_df
from get_latest_planequery_aircraft_release import get_latest_aircraft_faa_csv_df
df_new = convert_faa_master_txt_to_df(zip_path, date_str)
df_base, start_date_str = get_latest_aircraft_faa_csv_df()
df_base = concat_faa_historical_df(df_base, df_new)
assert df_base['download_date'].is_monotonic_increasing, "download_date is not monotonic increasing"
df_base.to_csv(OUT_ROOT / f"planequery_aircraft_faa_{start_date_str}_{date_str}.csv", index=False)