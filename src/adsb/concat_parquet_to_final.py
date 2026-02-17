from pathlib import Path
import polars as pl

OUTPUT_DIR = Path("./data/output")

compressed_dir = OUTPUT_DIR / "compressed"
date_dirs = sorted(p for p in compressed_dir.iterdir() if p.is_dir())
if not date_dirs:
    raise FileNotFoundError(f"No date folders found in {compressed_dir}")

start_date = date_dirs[0].name
end_date = date_dirs[-1].name
parquet_files = []
for d in date_dirs:
    parquet_files.extend(sorted(d.glob("*.parquet")))

if not parquet_files:
    raise FileNotFoundError("No parquet files found in compressed subfolders")

frames = [pl.read_parquet(p) for p in parquet_files]
df = pl.concat(frames, how="vertical", rechunk=True)

df = df.sort(["time", "icao"])
output_path = OUTPUT_DIR / f"openairframes_adsb_{start_date}_{end_date}.parquet"
print(f"Writing combined parquet to {output_path} with {df.height} rows")
df.write_parquet(output_path)
csv_output_path = OUTPUT_DIR / f"openairframes_adsb_{start_date}_{end_date}.csv"
print(f"Writing combined csv to {csv_output_path} with {df.height} rows")
df.write_csv(csv_output_path)