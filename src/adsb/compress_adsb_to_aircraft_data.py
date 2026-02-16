# Shared compression logic for ADS-B aircraft data
import os
import polars as pl

COLUMNS = ['dbFlags', 'ownOp', 'year', 'desc', 'aircraft_category', 'r', 't']


def compress_df_polars(df: pl.DataFrame, icao: str) -> pl.DataFrame:
    """Compress a single ICAO group to its most informative row using Polars."""
    # Create signature string
    df = df.with_columns(
        pl.concat_str([pl.col(c).cast(pl.Utf8) for c in COLUMNS], separator="|").alias("_signature")
    )
    
    # Compute signature counts
    signature_counts = df.group_by("_signature").len().rename({"len": "_sig_count"})
    
    # Group by signature and take first row
    df = df.group_by("_signature").first()
    
    if df.height == 1:
        # Only one unique signature, return it
        result = df.drop("_signature").with_columns(pl.lit(icao).alias("icao"))
        return result
    
    # For each row, create dict of non-empty column values and check subsets
    # Convert to list of dicts for subset checking (same logic as pandas version)
    rows_data = []
    for row in df.iter_rows(named=True):
        non_empty = {col: row[col] for col in COLUMNS if row[col] != '' and row[col] is not None}
        rows_data.append({
            'signature': row['_signature'],
            'non_empty_dict': non_empty,
            'non_empty_count': len(non_empty),
            'row_data': row
        })
    
    # Check if row i's non-empty values are a subset of row j's non-empty values
    def is_subset_of_any(idx):
        row_dict = rows_data[idx]['non_empty_dict']
        row_count = rows_data[idx]['non_empty_count']
        
        for other_idx, other_data in enumerate(rows_data):
            if idx == other_idx:
                continue
            other_dict = other_data['non_empty_dict']
            other_count = other_data['non_empty_count']
            
            # Check if all non-empty values in current row match those in other row
            if all(row_dict.get(k) == other_dict.get(k) for k in row_dict.keys()):
                # If they match and other has more defined columns, current row is redundant
                if other_count > row_count:
                    return True
        return False
    
    # Keep rows that are not subsets of any other row
    keep_indices = [i for i in range(len(rows_data)) if not is_subset_of_any(i)]
    
    if len(keep_indices) == 0:
        keep_indices = [0]  # Fallback: keep first row
    
    remaining_signatures = [rows_data[i]['signature'] for i in keep_indices]
    df = df.filter(pl.col("_signature").is_in(remaining_signatures))
    
    if df.height > 1:
        # Use signature counts to pick the most frequent one
        df = df.join(signature_counts, on="_signature", how="left")
        max_count = df["_sig_count"].max()
        df = df.filter(pl.col("_sig_count") == max_count).head(1)
        df = df.drop("_sig_count")
    
    result = df.drop("_signature").with_columns(pl.lit(icao).alias("icao"))
    
    # Ensure empty strings are preserved
    for col in COLUMNS:
        if col in result.columns:
            result = result.with_columns(pl.col(col).fill_null(""))
    
    return result


def compress_multi_icao_df(df: pl.DataFrame, verbose: bool = True) -> pl.DataFrame:
    """Compress a DataFrame with multiple ICAOs to one row per ICAO per UTC day.
    
    This is the main entry point for compressing ADS-B data.
    Used by both daily GitHub Actions runs and historical AWS runs.
    
    Args:
        df: DataFrame with columns ['time', 'icao'] + COLUMNS
        verbose: Whether to print progress
    
    Returns:
        Compressed DataFrame with one row per ICAO per UTC day
    """
    if df.height == 0:
        return df
    
    # Extract UTC date from time column
    df = df.with_columns(pl.col('time').dt.date().alias('_date'))
    
    # Sort by date, icao, and time
    df = df.sort(['_date', 'icao', 'time'])
    
    # Fill null values with empty strings for COLUMNS
    for col in COLUMNS:
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Utf8).fill_null(""))
    
    # First pass: quick deduplication of exact duplicates per day
    df = df.unique(subset=['_date', 'icao'] + COLUMNS, keep='first')
    if verbose:
        print(f"After quick dedup: {df.height} records")
    
    # Second pass: sophisticated compression per date and ICAO
    if verbose:
        print("Compressing per ICAO...")
    
    # Process each date+ICAO group
    date_icao_groups = df.partition_by(['_date', 'icao'], as_dict=True, maintain_order=True)
    compressed_dfs = []
    
    for group_key, group_df in date_icao_groups.items():
        # partition_by with as_dict=True returns tuple keys: (date, icao)
        date_val, icao = group_key
        compressed = compress_df_polars(group_df, str(icao))
        # Time is preserved from compress_df_polars (earliest time for this ICAO on this day)
        compressed_dfs.append(compressed)
    
    if compressed_dfs:
        df_compressed = pl.concat(compressed_dfs)
    else:
        df_compressed = df.head(0)  # Empty with same schema
    
    if verbose:
        print(f"After compress: {df_compressed.height} records")
    
    # Drop the temporary _date column
    df_compressed = df_compressed.drop('_date')
    
    # Reorder columns: time first, then icao
    cols = df_compressed.columns
    ordered_cols = ['time', 'icao'] + [c for c in cols if c not in ['time', 'icao']]
    df_compressed = df_compressed.select(ordered_cols)
    
    return df_compressed


def load_raw_adsb_for_day(day):
    """Load raw ADS-B data for a day from parquet file."""
    from datetime import timedelta
    from pathlib import Path
    
    start_time = day.replace(hour=0, minute=0, second=0, microsecond=0)
    
    # Check for parquet file first
    version_date = f"v{start_time.strftime('%Y.%m.%d')}"
    parquet_file = Path(f"data/output/parquet_output/{version_date}.parquet")
    
    if not parquet_file.exists():
        # Try to generate parquet file by calling the download function
        print(f"  Parquet file not found: {parquet_file}")
        print(f"  Attempting to download and generate parquet for {start_time.strftime('%Y-%m-%d')}...")
        
        from download_adsb_data_to_parquet import create_parquet_for_day
        result_path = create_parquet_for_day(start_time, keep_folders=False)
        
        if result_path:
            print(f"  Successfully generated parquet file: {result_path}")
        else:
            raise Exception("Failed to generate parquet file")
    
    if parquet_file.exists():
        print(f"  Loading from parquet: {parquet_file}")
        df = pl.read_parquet(
            parquet_file, 
            columns=['time', 'icao', 'r', 't', 'dbFlags', 'ownOp', 'year', 'desc', 'aircraft_category']
        )
        
        # Convert to timezone-naive datetime
        if df["time"].dtype == pl.Datetime:
            df = df.with_columns(pl.col("time").dt.replace_time_zone(None))
        
        return df
    else:
        # Return empty DataFrame if parquet file doesn't exist
        print(f"  No data available for {start_time.strftime('%Y-%m-%d')}")
        return pl.DataFrame(schema={
            'time': pl.Datetime,
            'icao': pl.Utf8,
            'r': pl.Utf8,
            't': pl.Utf8,
            'dbFlags': pl.Int64,
            'ownOp': pl.Utf8,
            'year': pl.Int64,
            'desc': pl.Utf8,
            'aircraft_category': pl.Utf8
        })


def load_historical_for_day(day):
    """Load and compress historical ADS-B data for a day."""
    df = load_raw_adsb_for_day(day)
    if df.height == 0:
        return df
    
    print(f"Loaded {df.height} raw records for {day.strftime('%Y-%m-%d')}")
    
    # Use shared compression function
    return compress_multi_icao_df(df, verbose=True)


def concat_compressed_dfs(df_base, df_new):
    """Concatenate base and new compressed dataframes, keeping the most informative row per ICAO."""
    # Combine both dataframes
    df_combined = pl.concat([df_base, df_new])
    
    # Sort by ICAO and time
    df_combined = df_combined.sort(['icao', 'time'])
    
    # Fill null values
    for col in COLUMNS:
        if col in df_combined.columns:
            df_combined = df_combined.with_columns(pl.col(col).fill_null(""))
    
    # Apply compression logic per ICAO to get the best row
    icao_groups = df_combined.partition_by('icao', as_dict=True, maintain_order=True)
    compressed_dfs = []
    
    for icao_key, group_df in icao_groups.items():
        icao = icao_key[0]
        compressed = compress_df_polars(group_df, str(icao))
        compressed_dfs.append(compressed)
    
    if compressed_dfs:
        df_compressed = pl.concat(compressed_dfs)
    else:
        df_compressed = df_combined.head(0)
    
    # Sort by time
    df_compressed = df_compressed.sort('time')
    
    return df_compressed


def get_latest_aircraft_adsb_csv_df():
    """Download and load the latest ADS-B CSV from GitHub releases."""
    from get_latest_release import download_latest_aircraft_adsb_csv
    import re
    
    csv_path = download_latest_aircraft_adsb_csv()
    df = pl.read_csv(csv_path, null_values=[""])
    
    # Fill nulls with empty strings
    for col in df.columns:
        if df[col].dtype == pl.Utf8:
            df = df.with_columns(pl.col(col).fill_null(""))
    
    # Extract start date from filename pattern: openairframes_adsb_{start_date}_{end_date}.csv[.gz]
    match = re.search(r"openairframes_adsb_(\d{4}-\d{2}-\d{2})_", str(csv_path))
    if not match:
        raise ValueError(f"Could not extract date from filename: {csv_path.name}")
    
    date_str = match.group(1)
    return df, date_str

