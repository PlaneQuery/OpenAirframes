from pathlib import Path
import pandas as pd
import re
from derive_from_faa_master_txt import concat_faa_historical_df

def concatenate_aircraft_csvs(
    input_dir: Path = Path("data/concat"),
    output_dir: Path = Path("data/planequery_aircraft"),
    filename_pattern: str = r"planequery_aircraft_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv"
):
    """
    Read all CSVs matching the pattern from input_dir in order,
    concatenate them using concat_faa_historical_df, and output a single CSV.
    
    Args:
        input_dir: Directory containing the CSV files to concatenate
        output_dir: Directory where the output CSV will be saved
        filename_pattern: Regex pattern to match CSV filenames
    """
    input_dir = Path(input_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    # Find all matching CSV files
    pattern = re.compile(filename_pattern)
    csv_files = []
    
    for csv_path in sorted(input_dir.glob("*.csv")):
        match = pattern.search(csv_path.name)
        if match:
            start_date = match.group(1)
            end_date = match.group(2)
            csv_files.append((start_date, end_date, csv_path))
    
    # Sort by start date, then end date
    csv_files.sort(key=lambda x: (x[0], x[1]))
    
    if not csv_files:
        raise FileNotFoundError(f"No CSV files matching pattern found in {input_dir}")
    
    print(f"Found {len(csv_files)} CSV files to concatenate")
    
    # Read first CSV as base
    first_start_date, first_end_date, first_path = csv_files[0]
    print(f"Reading base file: {first_path.name}")
    df_base = pd.read_csv(
        first_path,
        dtype={
            'transponder_code': str,
            'unique_regulatory_id': str,
            'registrant_county': str
        }
    )
    
    # Concatenate remaining CSVs
    for start_date, end_date, csv_path in csv_files[1:]:
        print(f"Concatenating: {csv_path.name}")
        df_new = pd.read_csv(
            csv_path,
            dtype={
                'transponder_code': str,
                'unique_regulatory_id': str,
                'registrant_county': str
            }
        )
        df_base = concat_faa_historical_df(df_base, df_new)
    
    # Verify monotonic increasing download_date
    assert df_base['download_date'].is_monotonic_increasing, "download_date is not monotonic increasing"
    
    # Output filename uses first start date and last end date
    last_start_date, last_end_date, _ = csv_files[-1]
    output_filename = f"planequery_aircraft_{first_start_date}_{last_end_date}.csv"
    output_path = output_dir / output_filename
    
    print(f"Writing output to: {output_path}")
    df_base.to_csv(output_path, index=False)
    print(f"Successfully concatenated {len(csv_files)} files into {output_filename}")
    print(f"Total rows: {len(df_base)}")
    
    return output_path


if __name__ == "__main__":
    # Example usage - modify these paths as needed
    concatenate_aircraft_csvs(
        input_dir=Path("data/concat"),
        output_dir=Path("data/planequery_aircraft")
    )