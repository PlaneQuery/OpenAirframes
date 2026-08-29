# Shared compression logic for ADS-B aircraft data
import os
import polars as pl

COLUMNS = ['dbFlags', 'ownOp', 'year', 'desc', 'aircraft_category', 'r', 't']

# Positional contract for every released ADS-B artifact. polars concatenates by
# position after .select(), so a divergent copy corrupts output without erroring.
FINAL_COLUMN_ORDER = ['time', 'icao', 'r', 't', 'dbFlags', 'ownOp', 'year', 'desc', 'aircraft_category']


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
    """Compress a DataFrame with multiple ICAOs to one row per ICAO.
    
    Args:
        df: DataFrame with columns ['time', 'icao'] + COLUMNS
        verbose: Whether to print progress
    
    Returns:
        Compressed DataFrame with one row per ICAO
    """
    if df.height == 0:
        return df
    
    # Sort by icao and time
    df = df.sort(['icao', 'time'])
    
    # Fill null values with empty strings for COLUMNS
    for col in COLUMNS:
        if col in df.columns:
            df = df.with_columns(pl.col(col).cast(pl.Utf8).fill_null(""))
    
    # Quick deduplication of exact duplicates
    df = df.unique(subset=['icao'] + COLUMNS, keep='first')
    if verbose:
        print(f"After quick dedup: {df.height} records")
    
    # Compress per ICAO
    if verbose:
        print("Compressing per ICAO...")
    
    icao_groups = df.partition_by('icao', as_dict=True, maintain_order=True)
    compressed_dfs = []
    
    for icao_key, group_df in icao_groups.items():
        icao = icao_key[0]
        compressed = compress_df_polars(group_df, str(icao))
        compressed_dfs.append(compressed)
    
    if compressed_dfs:
        df_compressed = pl.concat(compressed_dfs)
    else:
        df_compressed = df.head(0)
    
    if verbose:
        print(f"After compress: {df_compressed.height} records")
    
    # Reorder columns: time first, then icao
    cols = df_compressed.columns
    ordered_cols = ['time', 'icao'] + [c for c in cols if c not in ['time', 'icao']]
    df_compressed = df_compressed.select(ordered_cols)
    
    return df_compressed


def load_parquet_part(part_id: int, date: str) -> pl.DataFrame:
    """Load a single parquet part file for a date.
    
    Args:
        part_id: Part ID (0-indexed, e.g. 0, 1, 2, 3)
        date: Date string in YYYY-MM-DD format
    
    Returns:
        DataFrame with ADS-B data
    """
    from pathlib import Path
    
    parquet_file = Path(f"data/output/parquet_output/part_{part_id}_{date}.parquet")
    
    if not parquet_file.exists():
        print(f"Parquet file not found: {parquet_file}")
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
    
    print(f"Loading from parquet: {parquet_file}")
    df = pl.read_parquet(
        parquet_file,
        columns=FINAL_COLUMN_ORDER
    )
    
    # Convert to timezone-naive datetime
    if df["time"].dtype == pl.Datetime:
        df = df.with_columns(pl.col("time").dt.replace_time_zone(None))
    os.remove(parquet_file)
    return df


def compress_parquet_part(part_id: int, date: str) -> pl.DataFrame:
    """Load and compress a single parquet part file."""
    df = load_parquet_part(part_id, date)
    
    if df.height == 0:
        return df

    # Filter to rows within the given date (UTC-naive). This is because sometimes adsb.lol export can have rows at 00:00:00 of next day or similar.
    date_lit = pl.lit(date).str.strptime(pl.Date, "%Y-%m-%d")
    df = df.filter(pl.col("time").dt.date() == date_lit)
    
    print(f"Loaded {df.height} raw records for part {part_id}, date {date}")
    
    return compress_multi_icao_df(df, verbose=True)


def concat_compressed_dfs(df_base, df_new):
    """Concatenate base and new compressed dataframes, keeping the most informative row per ICAO."""
    # Combine both dataframes
    df_combined = pl.concat([df_base, df_new])
    return df_combined