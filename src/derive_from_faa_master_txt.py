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
    
    # Create planequery_airframe_id
    df["planequery_airframe_id"] = (
        normalize(df["aircraft_manufacturer"])
        + "|"
        + normalize(df["aircraft_model"])
        + "|"
        + normalize(df["serial_number"])
    )
    
    # Move planequery_airframe_id to come after registration_number
    cols = df.columns.tolist()
    cols.remove("planequery_airframe_id")
    reg_idx = cols.index("registration_number")
    cols.insert(reg_idx + 1, "planequery_airframe_id")
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

    df_base = pd.concat([df_base, df_new], ignore_index=True)
    
    CONTENT_COLS = [
        c for c in df_base.columns
        if c not in {"download_date"}
    ]
    
    df_base["row_fingerprint"] = (
        df_base[CONTENT_COLS]
        .fillna("")
        .astype(str)
        .apply(lambda row: "|".join(row), axis=1)
    )
    
    df_base = df_base.drop_duplicates(
              subset=["row_fingerprint"],
              keep="first"
          ).drop(columns=["row_fingerprint"])
    return df_base