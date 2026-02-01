from pathlib import Path
import zipfile
import pandas as pd
from faa_aircraft_registry import read

def convert_faa_master_txt_to_csv(zip_path: Path, csv_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as z:
        registrations = read(z)

    df = pd.DataFrame(registrations['master'].values())
    col = "transponder_code_hex"
    df = df[[col] + [c for c in df.columns if c != col]]
    df = df.rename(columns={"transponder_code_hex": "icao"})
    registrant = pd.json_normalize(df["registrant"]).add_prefix("registrant_")
    df = df.drop(columns="registrant").join(registrant)
    df = df.rename(columns={"aircraft_type": "aircraft_type_2"})
    aircraft = pd.json_normalize(df["aircraft"].where(df["aircraft"].notna(), {})).add_prefix("aircraft_")
    df = df.drop(columns="aircraft").join(aircraft)
    df = df.rename(columns={"engine_type": "engine_type_2"})
    engine = pd.json_normalize(df["engine"].where(df["engine"].notna(), {})).add_prefix("engine_")
    df = df.drop(columns="engine").join(engine)
    df = df.sort_values(by=["icao"])
    df.to_csv(csv_path, index=False)