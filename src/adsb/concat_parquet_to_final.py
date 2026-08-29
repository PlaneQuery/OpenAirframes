from pathlib import Path
import polars as pl
import argparse
import os
import sys

from src.adsb.compress_adsb_to_aircraft_data import FINAL_COLUMN_ORDER

OUTPUT_DIR = Path("./data/output")

def main():
    parser = argparse.ArgumentParser(description="Concatenate compressed parquet files for a single day")
    parser.add_argument("--date", type=str, required=True, help="Date in YYYY-MM-DD format")
    parser.add_argument("--concat_with_latest_csv", action="store_true", help="Whether to also concatenate with the latest CSV from GitHub releases")
    args = parser.parse_args()

    compressed_dir = OUTPUT_DIR / "compressed"
    date_dir = compressed_dir / args.date

    parquet_files = sorted(date_dir.glob("*.parquet"))
    df = None
    if parquet_files: # TODO: This logic could be updated slightly.
        print(f"Found {len(parquet_files)} parquet part(s) in {date_dir}")

        frames = [pl.read_parquet(p) for p in parquet_files]
        df = pl.concat(frames, how="vertical", rechunk=True)

        df = df.sort(["time", "icao"])
        df = df.select(FINAL_COLUMN_ORDER)
        
        output_path = OUTPUT_DIR / f"openairframes_adsb_{args.date}.parquet"
        print(f"Writing combined parquet to {output_path} with {df.height} rows")
        df.write_parquet(output_path)

        csv_output_path = OUTPUT_DIR / f"openairframes_adsb_{args.date}.csv.gz"
        print(f"Writing combined csv.gz to {csv_output_path} with {df.height} rows")
        df.write_csv(csv_output_path, compression="gzip")
    elif not args.concat_with_latest_csv:
        # Nothing to merge and no release to fall back on: exiting 0 here would let the
        # caller mistake "produced nothing" for "succeeded".
        print(f"ERROR: No parquet files found in {date_dir} and --concat_with_latest_csv not set")
        sys.exit(1)
    else:
        print(f"No parquet files found in {date_dir}; falling back to the latest released CSV")

    if args.concat_with_latest_csv:
        print("Loading latest CSV from GitHub releases to concatenate with...")
        from src.get_latest_release import get_latest_aircraft_adsb_csv_df
        from datetime import datetime
        
        df_latest_csv, csv_start_date, csv_end_date = get_latest_aircraft_adsb_csv_df()
        
        # Compare dates: end_date is exclusive, so if csv_end_date > args.date, 
        # the latest CSV already includes this day's data
        csv_end_dt = datetime.strptime(csv_end_date, "%Y-%m-%d")
        args_dt = datetime.strptime(args.date, "%Y-%m-%d")
        
        if df is None or csv_end_dt >= args_dt:
            print(f"Latest CSV already includes data through {args.date} (end_date={csv_end_date} is exclusive)")
            print("Writing latest CSV directly without concatenation to avoid duplicates")
            os.makedirs(OUTPUT_DIR, exist_ok=True)
            final_csv_output_path = OUTPUT_DIR / f"openairframes_adsb_{csv_start_date}_{csv_end_date}.csv.gz"
            df_latest_csv = df_latest_csv.select(FINAL_COLUMN_ORDER)
            df_latest_csv.write_csv(final_csv_output_path, compression="gzip")
        else:
            print(f"Concatenating latest CSV (through {csv_end_date}) with new data ({args.date})")
            # Ensure column order matches before concatenating
            df_latest_csv = df_latest_csv.select(FINAL_COLUMN_ORDER)
            from src.adsb.compress_adsb_to_aircraft_data import concat_compressed_dfs
            df_final = concat_compressed_dfs(df_latest_csv, df)
            df_final = df_final.select(FINAL_COLUMN_ORDER)
            final_csv_output_path = OUTPUT_DIR / f"openairframes_adsb_{csv_start_date}_{args.date}.csv.gz"
            df_final.write_csv(final_csv_output_path, compression="gzip")
        print(f"Final CSV written to {final_csv_output_path}")

if __name__ == "__main__":
    main()