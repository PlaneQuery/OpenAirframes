# OpenAirframes.org

OpenAirframes.org is an open-source, community-driven airframes database.

The data includes:
- Registration information from Civil Aviation Authorities (FAA)
- Airline data (e.g., Air France)
- Community contributions such as ownership details, military aircraft info, photos, and more

---

## For Users

A daily release is created at **06:00 UTC** and includes:

- **openairframes_community.csv**  
  All community submissions

- **openairframes_adsb.csv**  
  Airframes dataset derived from ADSB.lol network data. For each UTC day, a row is created for every icao observed in that day’s ADS-B messages, using registration data from [tar1090-db](https://github.com/wiedehopf/tar1090-db) (ADSBExchange & Mictronics).
Example Usage:
```python
import pandas as pd
url = "https://github.com/PlaneQuery/OpenAirframes/releases/download/openairframes-2026-03-18-main/openairframes_adsb_2024-01-01_2026-03-17.csv.gz" # 1GB
df = pd.read_csv(url)
df
```
![](docs/images/df_adsb_example_0.png)
- **openairframes_faa.csv**  
  All [FAA registration data](https://www.faa.gov/licenses_certificates/aircraft_certification/aircraft_registry/releasable_aircraft_download) from 2023-08-16 to present (~260 MB)


- **ReleasableAircraft_{date}.zip**  
  A daily snapshot of the FAA database, which updates at **05:30 UTC**

---

## For Contributors

Submit data via a [GitHub Issue](https://github.com/PlaneQuery/OpenAirframes/issues/new?template=community_submission.yaml) with your preferred attribution. Once approved, it will appear in the daily release. A leaderboard will be available in the future.
All data is valuable. Examples include:
- Celebrity ownership (with citations)
- Photos
- Internet capability
- Military aircraft information
- Unique facts (e.g., an airframe that crashed, performs aerobatics, etc.)

Please try to follow the submission formatting guidelines. If you are struggling with them, that is fine—submit your data anyway and it will be formatted for you.

---

## For Developers
All code, compute (GitHub Actions), and storage (releases) are in this GitHub repository Improvements are welcome. Potential features include:
- Web UI for data
- Web UI for contributors
- Additional export formats in the daily release
- Data fusion from multiple sources in the daily release
- Automated airframe data connectors, including (but not limited to) civil aviation authorities and airline APIs
