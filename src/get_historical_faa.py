'''Generated with ChatGPT 5.2 prompt
scrape-faa-releasable-aircraft
Every day it creates a new commit that takes ReleasableAircraft zip from FAA takes Master.txt to make these files (it does this so that all files stay under 100mb). For every commit day I want to recombine all the files into one Master.txt again. It has data/commits since 2023.
scrape-faa-releasable-aircraft % ls
ACFTREF.txt     DOCINDEX.txt    MASTER-1.txt    MASTER-3.txt    MASTER-5.txt    MASTER-7.txt    MASTER-9.txt    RESERVED.txt
DEALER.txt      ENGINE.txt      MASTER-2.txt    MASTER-4.txt    MASTER-6.txt    MASTER-8.txt    README.md       ardata.pdf
'''
import subprocess, re
from pathlib import Path
from collections import OrderedDict

REPO = "/Users/jonahgoode/Documents/PlaneQuery/Other-Code/scrape-faa-releasable-aircraft"
OUT_ROOT = Path("data/faa_releasable_historical")
OUT_ROOT.mkdir(parents=True, exist_ok=True)

def run_git(*args: str, text: bool = True) -> str:
    return subprocess.check_output(
        ["git", "-C", REPO, *args],
        text=text
    ).strip()

# Commits (oldest -> newest), restricted to master parts
log = run_git(
    "log",
    "--reverse",
    "--format=%H %cs",
    "--",
    "MASTER-1.txt"
)

lines = [ln for ln in log.splitlines() if ln.strip()]
if not lines:
    raise SystemExit("No commits found.")

# Map date -> last commit SHA on that date (only Feb 2024)
date_to_sha = OrderedDict()
for ln in lines:
    sha, date = ln.split()
    if date.startswith("2024-02"):
        date_to_sha[date] = sha

if not date_to_sha:
    raise SystemExit("No February 2024 commit-days found.")

master_re = re.compile(r"^MASTER-(\d+)\.txt$")

for date, sha in date_to_sha.items():
    names = run_git("ls-tree", "--name-only", sha).splitlines()

    parts = []
    for n in names:
        m = master_re.match(n)
        if m:
            parts.append((int(m.group(1)), n))
    parts.sort()

    if not parts:
        continue

    day_dir = OUT_ROOT / date
    day_dir.mkdir(parents=True, exist_ok=True)
    out_path = day_dir / "Master.txt"

    with out_path.open("wb") as w:
        for _, fname in parts:
            data = subprocess.check_output(
                ["git", "-C", REPO, "show", f"{sha}:{fname}"]
            )
            w.write(data)
            if data and not data.endswith(b"\n"):
                w.write(b"\n")

    print(f"{date} {sha[:7]} -> {out_path} ({len(parts)} parts)")

print(f"\nDone. Output root: {OUT_ROOT.resolve()}")
