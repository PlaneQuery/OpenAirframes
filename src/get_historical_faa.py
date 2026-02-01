"""
For each commit-day in Feb 2024 (last commit per day):
- Write ALL FAA text files from that commit into: data/faa_releasable_historical/YYYY-MM-DD/
    ACFTREF.txt, DEALER.txt, DOCINDEX.txt, ENGINE.txt, RESERVED.txt
- Recombine MASTER-*.txt into Master.txt
- Produce Master.csv via convert_faa_master_txt_to_csv

Assumes the non-master files are present in every commit.
"""
import subprocess, re
from pathlib import Path
from collections import OrderedDict
from derive_from_faa_master_txt import convert_faa_master_txt_to_csv
import zipfile

REPO = "/Users/jonahgoode/Documents/PlaneQuery/Other-Code/scrape-faa-releasable-aircraft"
OUT_ROOT = Path("data/faa_releasable_historical")
OUT_ROOT.mkdir(parents=True, exist_ok=True)

def run_git_text(*args: str) -> str:
    return subprocess.check_output(["git", "-C", REPO, *args], text=True).strip()

def run_git_bytes(*args: str) -> bytes:
    return subprocess.check_output(["git", "-C", REPO, *args])

# All commits in Feb 2024 (oldest -> newest)
log = run_git_text(
    "log",
    "--reverse",
    "--format=%H %cs",
    "--since=2024-02-01",
    "--until=2024-02-29",
)
lines = [ln for ln in log.splitlines() if ln.strip()]
if not lines:
    raise SystemExit("No commits found in February 2024.")

# date -> last SHA that day
date_to_sha = OrderedDict()
for ln in lines:
    sha, date = ln.split()
    date_to_sha[date] = sha

OTHER_FILES = ["ACFTREF.txt", "DEALER.txt", "DOCINDEX.txt", "ENGINE.txt", "RESERVED.txt"]
master_re = re.compile(r"^MASTER-(\d+)\.txt$")

for date, sha in date_to_sha.items():
    day_dir = OUT_ROOT / date
    day_dir.mkdir(parents=True, exist_ok=True)

    # Write auxiliary files (assumed present)
    for fname in OTHER_FILES:
        (day_dir / fname).write_bytes(run_git_bytes("show", f"{sha}:{fname}"))

    # Recombine MASTER parts
    names = run_git_text("ls-tree", "--name-only", sha).splitlines()
    parts = []
    for n in names:
        m = master_re.match(n)
        if m:
            parts.append((int(m.group(1)), n))
    parts.sort()
    if not parts:
        raise RuntimeError(f"{date} {sha[:7]}: no MASTER-*.txt parts found")

    master_path = day_dir / "MASTER.txt"
    with master_path.open("wb") as w:
        for _, fname in parts:
            data = run_git_bytes("show", f"{sha}:{fname}")
            w.write(data)
            if data and not data.endswith(b"\n"):
                w.write(b"\n")

    # 3) Zip the day's files
    zip_path = day_dir / f"ReleasableAircraft.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for p in day_dir.iterdir():
            z.write(p, arcname=p.name)

    # 4) Convert ZIP -> CSV
    out_csv = day_dir / f"ReleasableAircraft_{date}.csv"
    convert_faa_master_txt_to_csv(zip_path, out_csv)


    print(f"{date} {sha[:7]} -> {day_dir} (master parts: {len(parts)})")

print(f"\nDone. Output root: {OUT_ROOT.resolve()}")
