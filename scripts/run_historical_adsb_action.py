#!/usr/bin/env python3
"""
Script to trigger historical-adsb workflow runs in 1-month chunks. Since github actions does not do well with downloading many artifacts for adsb-reduce

Usage:
    python scripts/run_historical_adsb_action.py --start-date 2025-01-01 --end-date 2025-06-01
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta


def add_months(date, months):
    """Add months to a date, handling month/year overflow."""
    month = date.month + months
    year = date.year + month // 12
    month = month % 12
    if month == 0:
        month = 12
        year -= 1
    
    # Handle day overflow (e.g., Jan 31 + 1 month = Feb 28/29)
    day = min(date.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0) else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    
    return date.replace(year=year, month=month, day=day)


def generate_monthly_chunks(start_date_str, end_date_str):
    """Generate monthly date ranges from start to end date."""
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    chunks = []
    current = start_date
    
    while current < end_date:
        # Calculate end of current chunk (start of next month)
        chunk_end = add_months(current, 1)
        
        # Don't go past the global end date
        if chunk_end > end_date:
            chunk_end = end_date
        
        chunks.append({
            'start': current.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d')
        })
        
        current = chunk_end
    
    return chunks


def trigger_workflow(start_date, end_date, chunk_days=3, branch='main', dry_run=False):
    """Trigger the historical-adsb workflow via GitHub CLI."""
    cmd = [
        'gh', 'workflow', 'run', 'historical-adsb.yaml',
        '--ref', branch,
        '-f', f'start_date={start_date}',
        '-f', f'end_date={end_date}',
        '-f', f'chunk_days={chunk_days}'
    ]
    
    if dry_run:
        print(f"[DRY RUN] Would run: {' '.join(cmd)}")
        return True
    
    print(f"Triggering workflow: {start_date} to {end_date} (on {branch})")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✓ Successfully triggered workflow for {start_date} to {end_date}")
        return True
    else:
        print(f"✗ Failed to trigger workflow for {start_date} to {end_date}")
        print(f"Error: {result.stderr}")
        return False


def main():
    parser = argparse.ArgumentParser(
        description='Trigger historical-adsb workflow runs in monthly chunks'
    )
    parser.add_argument(
        '--start-date',
        required=True,
        help='Start date in YYYY-MM-DD format (inclusive)'
    )
    parser.add_argument(
        '--end-date',
        required=True,
        help='End date in YYYY-MM-DD format (exclusive)'
    )
    parser.add_argument(
        '--chunk-days',
        type=int,
        default=7,
        help='Days per job chunk within each workflow run (default: 7)'
    )
    parser.add_argument(
        '--branch',
        type=str,
        default='main',
        help='Branch to run the workflow on (default: main)'
    )
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Print commands without executing them'
    )
    parser.add_argument(
        '--delay',
        type=int,
        default=5,
        help='Delay in seconds between workflow triggers (default: 5)'
    )
    
    args = parser.parse_args()
    
    # Validate dates
    try:
        start = datetime.strptime(args.start_date, '%Y-%m-%d')
        end = datetime.strptime(args.end_date, '%Y-%m-%d')
        if start >= end:
            print("Error: start_date must be before end_date")
            sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid date format - {e}")
        sys.exit(1)
    
    # Generate monthly chunks
    chunks = generate_monthly_chunks(args.start_date, args.end_date)
    
    print(f"\nGenerating {len(chunks)} monthly workflow runs on branch '{args.branch}':")
    for i, chunk in enumerate(chunks, 1):
        print(f"  {i}. {chunk['start']} to {chunk['end']}")
    
    if not args.dry_run:
        response = input(f"\nProceed with triggering {len(chunks)} workflows on '{args.branch}'? [y/N]: ")
        if response.lower() != 'y':
            print("Cancelled.")
            sys.exit(0)
    
    print()
    
    # Trigger workflows
    import time
    success_count = 0
    
    for i, chunk in enumerate(chunks, 1):
        print(f"\n[{i}/{len(chunks)}] ", end='')
        
        if trigger_workflow(
            chunk['start'],
            chunk['end'],
            chunk_days=args.chunk_days,
            branch=args.branch,
            dry_run=args.dry_run
        ):
            success_count += 1
        
        # Add delay between triggers (except for last one)
        if i < len(chunks) and not args.dry_run:
            time.sleep(args.delay)
    
    print(f"\n\nSummary: {success_count}/{len(chunks)} workflows triggered successfully")
    
    if success_count < len(chunks):
        sys.exit(1)


if __name__ == '__main__':
    main()
