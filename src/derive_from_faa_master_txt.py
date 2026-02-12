from pathlib import Path
import zipfile
import pandas as pd
from faa_aircraft_registry import read

def convert_faa_master_txt_to_df(zip_path: Path, date: str):
    with zipfile.ZipFile(zip_path) as z:
        registrations = read(z)

    df = pd.DataFrame(registrations['master'].values())
    
    df.insert(0, "download_date", date)
    
    registrant = pd.json_normalize(df["registrant"]).add_prefix("registrant_")
    df = df.drop(columns="registrant").join(registrant)
    
    # Move transponder_code_hex to second column (after registration_number)
    cols = df.columns.tolist()
    cols.remove("transponder_code_hex")
    cols.insert(1, "transponder_code_hex")
    df = df[cols]
    
    df = df.rename(columns={"aircraft_type": "aircraft_type_2"})
    aircraft = pd.json_normalize(df["aircraft"].where(df["aircraft"].notna(), {})).add_prefix("aircraft_")
    df = df.drop(columns="aircraft").join(aircraft)
    df = df.rename(columns={"engine_type": "engine_type_2"})
    engine = pd.json_normalize(df["engine"].where(df["engine"].notna(), {})).add_prefix("engine_")
    df = df.drop(columns="engine").join(engine)
    certification = pd.json_normalize(df["certification"].where(df["certification"].notna(), {})).add_prefix("certificate_")
    df = df.drop(columns="certification").join(certification)
    
    # Create openairframes_id
    df["openairframes_id"] = (
        normalize(df["aircraft_manufacturer"])
        + "|"
        + normalize(df["aircraft_model"])
        + "|"
        + normalize(df["serial_number"])
    )
    
    # Move openairframes_id to come after registration_number
    cols = df.columns.tolist()
    cols.remove("openairframes_id")
    reg_idx = cols.index("registration_number")
    cols.insert(reg_idx + 1, "openairframes_id")
    df = df[cols]
    
    # Convert all NaN to empty strings
    df = df.fillna("")
    
    return df



def normalize(s: pd.Series) -> pd.Series:
    return (
        s.fillna("")
         .astype(str)
         .str.upper()
         .str.strip()
         # collapse whitespace
         .str.replace(r"\s+", " ", regex=True)
         # remove characters that cause false mismatches
         .str.replace(r"[^\w\-]", "", regex=True)
    )


def concat_faa_historical_df(df_base, df_new):
    df_new = df_new[df_base.columns]
    df_base = pd.concat([df_base, df_new], ignore_index=True)
    
    CONTENT_COLS = [
        c for c in df_base.columns
        if c not in {"download_date"}
    ]
    
    # Normalize values to handle numeric type, formatting, and list ordering differences
    def normalize_series(series):
        def normalize_value(val):
            # Handle lists (sort them for consistent comparison)
            if isinstance(val, list):
                return "|".join(sorted(str(v) for v in val))
            
            # Convert to string
            val_str = str(val).strip()
            
            # Handle empty strings
            if val_str == "" or val_str == "nan":
                return ""
            
            # Check if it looks like a list representation (starts with [ )
            if val_str.startswith('[') and val_str.endswith(']'):
                try:
                    # Try to parse as a list-like string
                    import ast
                    parsed = ast.literal_eval(val_str)
                    if isinstance(parsed, list):
                        return "|".join(sorted(str(v) for v in parsed))
                except (ValueError, SyntaxError):
                    pass  # Not a valid list, continue to other checks
            
            # Try to normalize as number
            try:
                # Remove leading zeros and convert float/int representations
                num_val = float(val_str)
                # If it's a whole number, return as int string (no .0)
                if num_val == int(num_val):
                    return str(int(num_val))
                # Otherwise return as float
                return str(num_val)
            except (ValueError, OverflowError):
                # Not a number, return as-is
                return val_str
        
        return series.apply(normalize_value)
    
    df_base["row_fingerprint"] = (
        df_base[CONTENT_COLS]
        .apply(normalize_series, axis=0)
        .apply(lambda row: "|".join(row), axis=1)
    )
    
    df_base = df_base.drop_duplicates(
              subset=["row_fingerprint"],
              keep="first"
          ).drop(columns=["row_fingerprint"])
    return df_base