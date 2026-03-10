#!/usr/bin/env python3
"""Validate the generated theairtraffic JSON output."""
import json
import glob
import sys

# Find the latest output
files = sorted(glob.glob("community/2026-02-*/theairtraffic_*.json"))
if not files:
    print("No output files found!")
    sys.exit(1)

path = files[-1]
print(f"Validating: {path}")

with open(path) as f:
    data = json.load(f)

print(f"Total entries: {len(data)}")

# Check military serial handling
mil = [d for d in data if "openairframes_id" in d]
print(f"\nEntries using openairframes_id: {len(mil)}")
for m in mil[:10]:
    print(f"  {m['openairframes_id']} -> owner: {m['tags'].get('owner','?')}")

# Check youtuber entries
yt = [d for d in data if d["tags"].get("owner_category_0") == "youtuber"]
print(f"\nYouTuber entries: {len(yt)}")
for y in yt[:5]:
    reg = y.get("registration_number", y.get("openairframes_id"))
    c0 = y["tags"].get("owner_category_0")
    c1 = y["tags"].get("owner_category_1")
    print(f"  {reg} -> owner: {y['tags']['owner']}, cat0: {c0}, cat1: {c1}")

# Check US Govt / military
gov = [d for d in data if d["tags"].get("owner") == "United States of America 747/757"]
print(f"\nUSA 747/757 entries: {len(gov)}")
for g in gov:
    oid = g.get("openairframes_id", g.get("registration_number"))
    print(f"  {oid}")

# Schema validation
issues = 0
for i, d in enumerate(data):
    has_id = any(k in d for k in ["registration_number", "transponder_code_hex", "openairframes_id"])
    if not has_id:
        print(f"  Entry {i}: no identifier!")
        issues += 1
    if "tags" not in d:
        print(f"  Entry {i}: no tags!")
        issues += 1
    # Check tag key format
    for k in d.get("tags", {}):
        import re
        if not re.match(r"^[a-z][a-z0-9_]{0,63}$", k):
            print(f"  Entry {i}: invalid tag key '{k}'")
            issues += 1

print(f"\nSchema issues: {issues}")

# Category breakdown
cats = {}
for s in data:
    c = s["tags"].get("owner_category_0", "NONE")
    cats[c] = cats.get(c, 0) + 1
print("\nCategory breakdown:")
for c, n in sorted(cats.items(), key=lambda x: -x[1]):
    print(f"  {c}: {n}")
