#!/usr/bin/env python3
"""
copy_best_recordings.py

Copies the highest-confidence recording for each bird species from
~/BirdSongs/Extracted/By_Date/ into ~/BirdSongs/BestRecordings/By_Date/,
preserving the full directory structure so files can be restored by
copying them straight back to ~/BirdSongs/Extracted/.

Safe to re-run: skips files already present in the destination.

Usage:
    python3 copy_best_recordings.py [--dry-run]

Restore:
    cp -rn ~/BirdSongs/BestRecordings/By_Date/ ~/BirdSongs/Extracted/By_Date/
    (-n skips files already present so nothing gets overwritten)
"""

import argparse
import os
import shutil
import sqlite3


DB_PATH = os.path.expanduser("~/BirdNET-Pi/scripts/birds.db")
BY_DATE_DIR = os.path.expanduser("~/BirdSongs/Extracted/By_Date")
DEST_BASE = os.path.expanduser("~/BirdSongs/BestRecordings/By_Date")

# For each species (Sci_Name), find the single detection row that has the
# maximum Confidence. We use a subquery so we get the correct File_Name /
# Date that actually belongs to that max-confidence row, not an arbitrary
# row that SQLite might return from a bare GROUP BY + MAX() aggregate.
QUERY = """
    SELECT d.Com_Name, d.Sci_Name, d.Date, d.File_Name, d.Confidence
    FROM detections d
    INNER JOIN (
        SELECT Sci_Name, MAX(Confidence) AS MaxConf
        FROM detections
        GROUP BY Sci_Name
    ) best ON d.Sci_Name = best.Sci_Name AND d.Confidence = best.MaxConf
    -- When multiple rows tie on max confidence, take the most recent.
    GROUP BY d.Sci_Name
    ORDER BY d.Com_Name ASC
"""


def common_name_to_dir(com_name: str) -> str:
    """Matches the naming logic in reporting.py / stats.php."""
    return com_name.replace("'", "").replace(" ", "_")


def _dest_size_mb(dest_base: str) -> float:
    total_bytes = 0
    for dirpath, _, filenames in os.walk(dest_base):
        for f in filenames:
            total_bytes += os.path.getsize(os.path.join(dirpath, f))
    return total_bytes / 1_048_576


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--dry-run", action="store_true", help="Print what would be copied without copying anything")
    args = parser.parse_args()

    if not os.path.isfile(DB_PATH):
        raise SystemExit(f"Database not found: {DB_PATH}")

    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    rows = con.execute(QUERY).fetchall()
    con.close()

    total_species = len(rows)
    copied = 0
    skipped_exists = 0
    skipped_missing = 0

    for row in rows:
        com_name = row["Com_Name"]
        date = row["Date"]
        file_name = row["File_Name"]
        confidence = row["Confidence"]

        dir_name = common_name_to_dir(com_name)
        src_dir = os.path.join(BY_DATE_DIR, date, dir_name)
        src = os.path.join(src_dir, file_name)

        if not os.path.isfile(src):
            print(f"  MISSING  {com_name!r} — source file not found: {src}")
            skipped_missing += 1
            continue

        dest_dir = os.path.join(DEST_BASE, date, dir_name)
        dest = os.path.join(dest_dir, file_name)

        if os.path.isfile(dest):
            skipped_exists += 1
            continue

        conf_pct = round(confidence * 100)
        if args.dry_run:
            print(f"  DRY-RUN  {com_name} ({conf_pct}%)  →  {dest}")
        else:
            os.makedirs(dest_dir, exist_ok=True)
            shutil.copy2(src, dest)
            png_src = src + ".png"
            if os.path.isfile(png_src):
                shutil.copy2(png_src, dest + ".png")
            print(f"  COPIED   {com_name} ({conf_pct}%)  →  {dest}")
        copied += 1

    # Summary
    print()
    print(f"Species in DB:       {total_species}")
    if args.dry_run:
        print(f"Would copy:          {copied}")
    else:
        print(f"Copied:              {copied}")
    print(f"Already present:     {skipped_exists}")
    print(f"Source file missing: {skipped_missing}")

    if not args.dry_run and os.path.isdir(DEST_BASE):
        dest_root = os.path.dirname(DEST_BASE)
        print(f"Output folder size:  {_dest_size_mb(DEST_BASE):.1f} MB  ({dest_root})")


if __name__ == "__main__":
    main()
