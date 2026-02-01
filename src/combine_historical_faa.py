#unique_regulatory_id
# 1. read historoical and output
# 2. read sequentially

# Instead of reading all csvs I can read just the latest release csv to get everything.

from pathlib import Path

base = Path("data/faa_releasable_historical")
for day_dir in sorted(base.glob("2024-02-*")):
    master = day_dir / "Master.txt"
    if master.exists():
        out_csv = master_txt_to_releasable_csv(master, out_dir="data/faa_releasable_historical_csv")
        print(day_dir.name, "->", out_csv)