#!/usr/bin/env python3
"""
Script to trigger adsb-to-aircraft-multiple-day-run workflow runs in monthly chunks.

Usage:
    python scripts/run_historical_adsb_action.py --start-date 2025-01-01 --end-date 2025-06-01
"""

import argparse
import subprocess
import sys
from datetime import datetime, timedelta
from calendar import monthrange


def generate_monthly_chunks(start_date_str, end_date_str):
    """Generate date ranges in monthly chunks from start to end date.
    
    End dates are exclusive (e.g., to process Jan 1-31, end_date should be Feb 1).
    """
    start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    
    chunks = []
    current = start_date
    
    while current < end_date:
        # Get the first day of the next month (exclusive end)
        _, days_in_month = monthrange(current.year, current.month)
        month_end = current.replace(day=days_in_month)
        next_month_start = month_end + timedelta(days=1)
        
        # Don't go past the global end date
        chunk_end = min(next_month_start, end_date)
        
        chunks.append({
            'start': current.strftime('%Y-%m-%d'),
            'end': chunk_end.strftime('%Y-%m-%d')
        })
        
        # Move to first day of next month
        if next_month_start >= end_date:
            break
        current = next_month_start
    
    return chunks


def trigger_workflow(start_date, end_date, repo='ggman12/OpenAirframes', branch='main', dry_run=False):
    """Trigger the adsb-to-aircraft-multiple-day-run workflow via GitHub CLI."""
    cmd = [
        'gh', 'workflow', 'run', 'adsb-to-aircraft-multiple-day-run.yaml',
        '--repo', repo,
        '--ref', branch,
        '-f', f'start_date={start_date}',
        '-f', f'end_date={end_date}'
    ]
    
    if dry_run:
        print(f"[DRY RUN] Would run: {' '.join(cmd)}")
        return True, None
    
    print(f"Triggering workflow: {start_date} to {end_date} (on {branch})")
    result = subprocess.run(cmd, capture_output=True, text=True)
    
    if result.returncode == 0:
        print(f"✓ Successfully triggered workflow for {start_date} to {end_date}")
        
        # Get the run ID of the workflow we just triggered
        # Wait a moment for it to appear
        import time
        time.sleep(2)
        
        # Get the most recent run (should be the one we just triggered)
        list_cmd = [
            'gh', 'run', 'list',
            '--repo', repo,
            '--workflow', 'adsb-to-aircraft-multiple-day-run.yaml',
            '--branch', branch,
            '--limit', '1',
            '--json', 'databaseId',
            '--jq', '.[0].databaseId'
        ]
        list_result = subprocess.run(list_cmd, capture_output=True, text=True)
        run_id = list_result.stdout.strip() if list_result.returncode == 0 else None
        
        return True, run_id
    else:
        print(f"✗ Failed to trigger workflow for {start_date} to {end_date}")
        print(f"Error: {result.stderr}")
        return False, None


def main():
    parser = argparse.ArgumentParser(
        description='Trigger adsb-to-aircraft-multiple-day-run workflow runs in monthly chunks'
    )
    parser.add_argument(
        '--start-date', '--start_date',
        dest='start_date',
        required=True,
        help='Start date in YYYY-MM-DD format (inclusive)'
    )
    parser.add_argument(
        '--end-date', '--end_date',
        dest='end_date',
        required=True,
        help='End date in YYYY-MM-DD format (exclusive)'
    )
    parser.add_argument(
        '--repo',
        type=str,
        default='ggman12/OpenAirframes',
        help='GitHub repository (default: ggman12/OpenAirframes)'
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
        if start > end:
            print("Error: start_date must be before or equal to end_date")
            sys.exit(1)
    except ValueError as e:
        print(f"Error: Invalid date format - {e}")
        sys.exit(1)
    
    # Generate monthly chunks
    chunks = generate_monthly_chunks(args.start_date, args.end_date)
    
    print(f"\nGenerating {len(chunks)} monthly workflow runs on branch '{args.branch}' (repo: {args.repo}):")
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
    triggered_runs = []
    
    for i, chunk in enumerate(chunks, 1):
        print(f"\n[{i}/{len(chunks)}] ", end='')
        
        success, run_id = trigger_workflow(
            chunk['start'],
            chunk['end'],
            repo=args.repo,
            branch=args.branch,
            dry_run=args.dry_run
        )
        
        if success:
            success_count += 1
            if run_id:
                triggered_runs.append({
                    'run_id': run_id,
                    'start': chunk['start'],
                    'end': chunk['end']
                })
        
        # Add delay between triggers (except for last one)
        if i < len(chunks) and not args.dry_run:
            time.sleep(args.delay)
    
    print(f"\n\nSummary: {success_count}/{len(chunks)} workflows triggered successfully")
    
    # Save triggered run IDs to a file
    if triggered_runs and not args.dry_run:
        import json
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        runs_file = f"./output/triggered_runs_{timestamp}.json"
        with open(runs_file, 'w') as f:
            json.dump({
                'start_date': args.start_date,
                'end_date': args.end_date,
                'repo': args.repo,
                'branch': args.branch,
                'runs': triggered_runs
            }, f, indent=2)
        print(f"\nRun IDs saved to: {runs_file}")
        print(f"\nTo download and concatenate these artifacts, run:")
        print(f"  python scripts/download_and_concat_runs.py {runs_file}")
    
    if success_count < len(chunks):
        sys.exit(1)


if __name__ == '__main__':
    main()
