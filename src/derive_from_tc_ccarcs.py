from pathlib import Path
import csv
import io
import zipfile

import pandas as pd

from derive_from_faa_master_txt import normalize

# CCARCS ships headerless, latin1, comma-delimited exports. Column names come from
# carslayout.txt in the same archive and must stay in file order.
CARSCURR_COLUMNS = [
    "MARK", "REGISTRATION_SUB_TYPE_E", "REGISTRATION_SUB_TYPE_F", "COMMON_NAME",
    "MODEL_NAME", "MANUFACTURERS_SERIAL_NUMBER", "MANUFACTURER_SERIAL_COMPRESSED",
    "ID_PLATE_MANUFACTURERS_NAME", "BASIS_FOR_REGISTRATION", "BASIS_FOR_REGISTRATION_F",
    "AIRCRAFT_CATEGORY_E", "AIRCRAFT_CATEGORY_F", "DATE_OF_IMPORT", "ENGINE_MANUF",
    "POWERGLIDER_FLAG", "ENGINE_CATEGORY_E", "ENGINE_CATEGORY_F", "NUMBER_OF_ENGINES",
    "NUMBER_OF_SEATS", "AIR_WEIGHT_KILOS", "SALE_REPORTED", "ISSUE_DATE",
    "EFFECTIVE_DATE", "INEFFECTIVE_DATE", "REGISTERED_PURPOSE_E", "REGISTERED_PURPOSE_F",
    "FLIGHT_AUTHORITY_E", "FLIGHT_AUTHORITY_F", "MANUFACTURE_OR_ASSEMBLY",
    "COUNTRY_MANUFACTURE_ASS_E", "COUNTRY_MANUFACTURE_ASS_F", "DATE_MANUFACTURE_ASSEMBLY",
    "BASE_OF_OPERATIONS_CTRY_E", "BASE_OF_OPERATIONS_CTRY_F", "BASE_PROVINCE_OR_STATE_E",
    "BASE_PROVINCE_OR_STATE_F", "CITY_AIRPORT", "TYPE_CERTIFICATE_NUMBER",
    "REGISTRATION_AUTH_STATUS_E", "REGISTRATION_AUTH_STATUS_F", "MULTIPLE_OWNER_FLAG",
    "MODIFIED_DATE", "MODE_S_TRANSPONDER_BINARY", "PHYSICAL_FILE_REGION_E",
    "PHYSICAL_FILE_REGION_F", "EX_MILITARY_MARK", "TRIMMED_MARK",
]

CARSOWNR_COLUMNS = [
    "MARK_LINK", "FULL_NAME", "TRADE_NAME", "STREET_NAME", "STREET_NAME2", "CITY",
    "PROVINCE_OR_STATE_E", "PROVINCE_OR_STATE_F", "POSTAL_CODE", "COUNTRY_E", "COUNTRY_F",
    "TYPE_OF_OWNER_E", "TYPE_OF_OWNER_F", "ACTIVE_FLAG", "CARE_OF", "REGION_E", "REGION_F",
    "OWNER_NAME_OLD_FORMAT", "MAIL_RECIPIENT", "TRIMMED_MARK",
]

# Owner mailing addresses are dropped rather than republished; see NOTICE.
OWNER_PII_COLUMNS = ["STREET_NAME", "STREET_NAME2", "CITY", "POSTAL_CODE", "CARE_OF"]


def _read_ccarcs_entry(zip_path: Path, entry: str, columns: list[str]) -> pd.DataFrame:
    """Read one headerless CCARCS export into a DataFrame, dropping the Oracle footer.

    The export ends with a bare "N rows selected." line and a blank line; both are
    narrower than the declared column count. Any *other* width mismatch is silent
    field loss, so it raises instead.
    """
    with zipfile.ZipFile(zip_path) as z:
        text = z.read(entry).decode("latin1")

    rows = []
    ragged = 0
    for row in csv.reader(io.StringIO(text)):
        if len(row) == len(columns):
            rows.append([cell.strip() for cell in row])
        elif len(row) <= 1:
            ragged += 1  # footer or trailing blank
        else:
            raise ValueError(
                f"{entry}: row with {len(row)} fields, expected {len(columns)}"
            )

    if ragged > 2:
        raise ValueError(f"{entry}: {ragged} ragged rows, expected at most 2")

    return pd.DataFrame(rows, columns=columns)


def tc_full_registration(mark: str) -> str:
    """Expand a trimmed CCARCS mark into the full Canadian registration.

    Three-character marks are vintage CF- registrations; everything else takes the
    modern C- prefix.
    """
    mark = (mark or "").strip().upper()
    if not mark:
        return ""
    return f"CF-{mark}" if len(mark) == 3 else f"C-{mark}"


def binary_to_hex(binary: str) -> str:
    """Convert a 24-bit Mode S binary string to uppercase hex."""
    binary = (binary or "").strip()
    if not binary or any(c not in "01" for c in binary):
        return ""
    return f"{int(binary, 2):06X}"


def _merge_owners(df_ownr: pd.DataFrame) -> pd.DataFrame:
    """Collapse one row per registered party into one row per mark.

    A co-owned mark repeats with a different party each time; keeping only the mail
    recipient would silently drop the rest. Each field is deduplicated independently
    and blanks are skipped, so values are not index-parallel across columns.
    """
    def join_unique(series: pd.Series) -> str:
        seen = []
        for value in series:
            value = (value or "").strip()
            if value and value not in seen:
                seen.append(value)
        return ", ".join(seen)

    grouped = df_ownr.groupby("TRIMMED_MARK", sort=False).agg(
        owner_name=("FULL_NAME", join_unique),
        owner_province_or_state=("PROVINCE_OR_STATE_E", join_unique),
        owner_country=("COUNTRY_E", join_unique),
        owner_type=("TYPE_OF_OWNER_E", join_unique),
        owner_party_count=("FULL_NAME", "size"),
    ).reset_index()

    # A party row states its own type ("Individual"); that stops being true of the
    # mark once several parties share it.
    grouped.loc[grouped["owner_party_count"] > 1, "owner_type"] = "Co-owner"
    return grouped


def convert_tc_ccarcs_to_df(zip_path: Path, date: str) -> pd.DataFrame:
    """Build the OpenAirframes Transport Canada frame from a CCARCS zip."""
    df = _read_ccarcs_entry(zip_path, "carscurr.txt", CARSCURR_COLUMNS)
    df_ownr = _read_ccarcs_entry(zip_path, "carsownr.txt", CARSOWNR_COLUMNS)
    df_ownr = df_ownr.drop(columns=OWNER_PII_COLUMNS)

    df = df.merge(_merge_owners(df_ownr), on="TRIMMED_MARK", how="left")

    out = pd.DataFrame({
        "download_date": date,
        "transponder_code_hex": df["MODE_S_TRANSPONDER_BINARY"].map(binary_to_hex),
        "registration_number": df["TRIMMED_MARK"].map(tc_full_registration),
        "mark": df["TRIMMED_MARK"],
        "aircraft_manufacturer": df["COMMON_NAME"],
        "aircraft_model": df["MODEL_NAME"],
        "serial_number": df["MANUFACTURERS_SERIAL_NUMBER"],
        "aircraft_category": df["AIRCRAFT_CATEGORY_E"],
        "engine_manufacturer": df["ENGINE_MANUF"],
        "engine_category": df["ENGINE_CATEGORY_E"],
        "number_of_engines": df["NUMBER_OF_ENGINES"],
        "number_of_seats": df["NUMBER_OF_SEATS"],
        "max_weight_kilos": df["AIR_WEIGHT_KILOS"],
        "registration_status": df["REGISTRATION_AUTH_STATUS_E"],
        "registration_sub_type": df["REGISTRATION_SUB_TYPE_E"],
        "basis_for_registration": df["BASIS_FOR_REGISTRATION"],
        "registered_purpose": df["REGISTERED_PURPOSE_E"],
        "flight_authority": df["FLIGHT_AUTHORITY_E"],
        "type_certificate_number": df["TYPE_CERTIFICATE_NUMBER"],
        "country_manufacture": df["COUNTRY_MANUFACTURE_ASS_E"],
        "date_manufacture_assembly": df["DATE_MANUFACTURE_ASSEMBLY"],
        "base_country": df["BASE_OF_OPERATIONS_CTRY_E"],
        "base_province_or_state": df["BASE_PROVINCE_OR_STATE_E"],
        "city_airport": df["CITY_AIRPORT"],
        "ex_military_mark": df["EX_MILITARY_MARK"],
        "multiple_owner_flag": df["MULTIPLE_OWNER_FLAG"],
        "owner_name": df["owner_name"],
        "owner_type": df["owner_type"],
        "owner_province_or_state": df["owner_province_or_state"],
        "owner_country": df["owner_country"],
        "issue_date": df["ISSUE_DATE"],
        "effective_date": df["EFFECTIVE_DATE"],
        "ineffective_date": df["INEFFECTIVE_DATE"],
        "modified_date": df["MODIFIED_DATE"],
    })

    out.insert(3, "openairframes_id", (
        normalize(out["aircraft_manufacturer"])
        + "|"
        + normalize(out["aircraft_model"])
        + "|"
        + normalize(out["serial_number"])
    ))

    out = out.fillna("")
    out = out.replace("None", "")
    return out
