"""
Setup script to copy data files from parent project.

Run this after cloning v9_production to set up the data folder.

Usage:
    python setup_data.py
"""

import shutil
import os
from pathlib import Path

def main():
    # Determine paths
    script_dir = Path(__file__).parent
    data_dir = script_dir / 'data'
    parent_data_dir = script_dir.parent / 'data'
    parent_analysis_dir = script_dir.parent / 'analysis'
    analysis_dir = script_dir / 'analysis'

    # Create directories
    data_dir.mkdir(exist_ok=True)
    analysis_dir.mkdir(exist_ok=True)

    # Files to copy
    data_files = [
        'BTC.csv',
        'mvrv_coinmetrics.csv',
        'dvol_history.csv',
    ]

    analysis_files = [
        'FINAL_SUMMARY.md',
        'IMPLEMENTATION_VERIFICATION.md',
        'IMPLEMENTATION_SPEC.md',
        'WALK_FORWARD_VALIDATION.md',
    ]

    print("Setting up v9_production data files...\n")

    # Copy data files
    print("Copying data files:")
    for filename in data_files:
        src = parent_data_dir / filename
        dst = data_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  [OK] {filename}")
        else:
            print(f"  [SKIP] {filename} (not found in parent)")

    # Copy analysis files
    print("\nCopying analysis files:")
    for filename in analysis_files:
        src = parent_analysis_dir / filename
        dst = analysis_dir / filename
        if src.exists():
            shutil.copy2(src, dst)
            print(f"  [OK] {filename}")
        else:
            print(f"  [SKIP] {filename} (not found in parent)")

    print("\nSetup complete!")
    print("\nTo test the setup, run:")
    print("  python tests/test_v9_signal.py")
    print("  python src/v9_production.py data/BTC.csv")

if __name__ == '__main__':
    main()
