from pathlib import Path
import csv
import io
import re
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

# Mailing address of the single designated recipient, matching the registrant_* address
# the FAA build already publishes. Addresses are per-party, so they are taken from the one
# MAIL_RECIPIENT row rather than merged across co-owners.
# registrant_zip_code holds the Canadian postal code: the name is the FAA's, and a union
# table needs one column per concept, not one per country's vocabulary.
OWNER_ADDRESS_COLUMNS = {
    "STREET_NAME": "registrant_street_1",
    "STREET_NAME2": "registrant_street_2",
    "CITY": "registrant_city",
    "POSTAL_CODE": "registrant_zip_code",
    "CARE_OF": "registrant_care_of",
}


FOOTER_RE = re.compile(r"\s*(\d+) rows selected\.\s*")

# Canada's register is ~35k aircraft. Any parse yielding less than this means the
# export was truncated upstream, which must not be published as a real snapshot.
MIN_EXPECTED_ROWS = 1000


def _read_ccarcs_entry(zip_path: Path, entry: str, columns: list[str]) -> pd.DataFrame:
    """Read one headerless CCARCS export into a DataFrame.

    Raises:
        ValueError: on any row whose width is neither the declared column count nor a
            blank/footer line, on a missing or disagreeing "N rows selected." footer, or
            on a row count below MIN_EXPECTED_ROWS.
    """
    with zipfile.ZipFile(zip_path) as z:
        text = z.read(entry).decode("latin1")

    rows = []
    declared = None
    # newline="" so a CRLF export does not leave \r on the final field of every row.
    for row in csv.reader(io.StringIO(text, newline="")):
        if len(row) == len(columns):
            rows.append([cell.strip() for cell in row])
            continue
        if not row or not any(cell.strip() for cell in row):
            continue  # trailing blank line
        match = FOOTER_RE.fullmatch(row[0]) if len(row) == 1 else None
        if match:
            declared = int(match.group(1))
            continue
        raise ValueError(
            f"{entry}: row with {len(row)} fields, expected {len(columns)}: {row[:3]!r}"
        )

    # The spool footer is a free checksum from the source; a short export is otherwise
    # indistinguishable from a genuinely smaller register.
    if declared is None:
        raise ValueError(f"{entry}: no 'N rows selected.' footer; export is truncated")
    if declared != len(rows):
        raise ValueError(f"{entry}: footer declares {declared} rows, parsed {len(rows)}")
    if len(rows) < MIN_EXPECTED_ROWS:
        raise ValueError(f"{entry}: only {len(rows)} rows, expected >= {MIN_EXPECTED_ROWS}")

    return pd.DataFrame(rows, columns=columns)


def tc_full_registration(mark: str) -> str:
    """Expand a trimmed CCARCS mark into the full Canadian registration.

    CCARCS stores the bare mark in both MARK and TRIMMED_MARK, so the prefix has to be
    reconstructed: three-character marks are vintage CF- registrations, everything else
    takes the modern C- prefix. Returns "" for a blank mark.
    """
    mark = (mark or "").strip().upper()
    if not mark:
        return ""
    return f"CF-{mark}" if len(mark) == 3 else f"C-{mark}"


def binary_to_hex(binary: str) -> str:
    """Convert a 24-bit Mode S binary string to a 6-digit uppercase hex address.

    Returns "" for empty, non-binary, or non-24-bit input. Width is checked because
    this column is the join key against ADS-B data: a short field would otherwise
    zero-pad into a plausible address belonging to a different aircraft.
    """
    binary = (binary or "").strip()
    if len(binary) != 24 or any(c not in "01" for c in binary):
        return ""
    return f"{int(binary, 2):06X}"


def _merge_owners(df_ownr: pd.DataFrame) -> pd.DataFrame:
    """Collapse the active registered parties for each mark into a single row.

    A co-owned mark repeats with a different party each time; keeping only the mail
    recipient would silently drop the rest.

    Each field is deduplicated and blank-skipped independently, so the values are NOT
    index-parallel: a mark with three owners can emit three names but one province.
    Consumers must not split on ", " and zip the columns together.
    """
    # ACTIVE_FLAG is "A"/"I", but "I" does not mean "former owner": 1,932 currently
    # Registered marks carry only "I" parties, and those rows are the MAIL_RECIPIENT.
    # So prefer active parties where a mark has any, and fall back to all of them
    # rather than publishing a registered aircraft with no owner at all.
    all_parties = df_ownr
    active = df_ownr[df_ownr["ACTIVE_FLAG"].str.upper() == "A"]
    marks_with_active = set(active["TRIMMED_MARK"])
    df_ownr = pd.concat([
        active,
        df_ownr[~df_ownr["TRIMMED_MARK"].isin(marks_with_active)],
    ])
    def join_unique(series: pd.Series) -> str:
        seen = []
        for value in series:
            value = (value or "").strip()
            if value and value not in seen:
                seen.append(value)
        return ", ".join(seen)

    def count_distinct(series: pd.Series) -> int:
        return len({v.strip() for v in series if v and v.strip()})

    grouped = df_ownr.groupby("TRIMMED_MARK", sort=False).agg(
        registrant_name=("FULL_NAME", join_unique),
        registrant_state=("PROVINCE_OR_STATE_E", join_unique),
        registrant_country=("COUNTRY_E", join_unique),
        registrant_type=("TYPE_OF_OWNER_E", join_unique),
        registrant_party_count=("FULL_NAME", count_distinct),
    ).reset_index()

    # A party row states its own type ("Individual"); that stops being true of the mark
    # once several parties share it. Counting distinct names rather than rows keeps this
    # consistent with owner_name, which is also deduplicated.
    grouped.loc[grouped["registrant_party_count"] > 1, "registrant_type"] = "Co-owner"

    # Taken from the unfiltered frame: the designated recipient is the designated
    # recipient even when its own party row is flagged inactive.
    recipient = (
        all_parties[all_parties["MAIL_RECIPIENT"].str.upper() == "Y"]
        .drop_duplicates(subset="TRIMMED_MARK", keep="first")
        .rename(columns=OWNER_ADDRESS_COLUMNS)
    )
    return grouped.merge(
        recipient[["TRIMMED_MARK", *OWNER_ADDRESS_COLUMNS.values()]],
        on="TRIMMED_MARK",
        how="left",
    )


def convert_tc_ccarcs_to_df(zip_path: Path, date: str) -> pd.DataFrame:
    """Build the OpenAirframes Transport Canada frame from a CCARCS zip."""
    df = _read_ccarcs_entry(zip_path, "carscurr.txt", CARSCURR_COLUMNS)
    df_ownr = _read_ccarcs_entry(zip_path, "carsownr.txt", CARSOWNR_COLUMNS)

    df = df.merge(_merge_owners(df_ownr), on="TRIMMED_MARK", how="left")

    out = pd.DataFrame({
        "download_date": date,
        # The FAA frame already carries `source`; it is the union discriminator.
        "source": "TC",
        "transponder_code_hex": df["MODE_S_TRANSPONDER_BINARY"].map(binary_to_hex),
        "registration_number": df["TRIMMED_MARK"].map(tc_full_registration),
        "mark": df["TRIMMED_MARK"],
        "aircraft_manufacturer": df["COMMON_NAME"],
        "aircraft_model": df["MODEL_NAME"],
        "serial_number": df["MANUFACTURERS_SERIAL_NUMBER"],
        "aircraft_category": df["AIRCRAFT_CATEGORY_E"],
        "engine_manufacturer": df["ENGINE_MANUF"],
        "engine_category": df["ENGINE_CATEGORY_E"],
        "aircraft_number_of_engines": df["NUMBER_OF_ENGINES"],
        "aircraft_number_of_seats": df["NUMBER_OF_SEATS"],
        "max_weight_kilos": df["AIR_WEIGHT_KILOS"],
        "status": df["REGISTRATION_AUTH_STATUS_E"],
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
        "registrant_name": df["registrant_name"],
        "registrant_type": df["registrant_type"],
        "registrant_state": df["registrant_state"],
        "registrant_country": df["registrant_country"],
        "registrant_care_of": df["registrant_care_of"],
        "registrant_street_1": df["registrant_street_1"],
        "registrant_street_2": df["registrant_street_2"],
        "registrant_city": df["registrant_city"],
        "registrant_zip_code": df["registrant_zip_code"],
        "issue_date": df["ISSUE_DATE"],
        "effective_date": df["EFFECTIVE_DATE"],
        "ineffective_date": df["INEFFECTIVE_DATE"],
        "modified_date": df["MODIFIED_DATE"],
    })

    # Position matches the FAA frame (after registration_number). Ordering is cosmetic:
    # concat_faa_historical_df reindexes df_new to the base's columns before merging.
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
