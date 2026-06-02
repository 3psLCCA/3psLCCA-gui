import pandas as pd
import random
import os
import sys

# Add the project root to sys.path to allow importing from 'ricke'
# This script is in ricke/utils/validate_explorer.py
base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if base_dir not in sys.path:
    sys.path.append(base_dir)

from ricke.cscc_explorer import CSCCExplorer

def run_validation():
    print("--- Validation: CSV vs. Pickle Explorer ---")
    
    # Path to the original CSV
    ricke_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    csv_path = os.path.join(ricke_dir, 'cscc_full_v1.csv')
    
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found at {csv_path}")
        return

    print(f"Reading {csv_path} for sampling...")
    df_csv = pd.read_csv(csv_path)
    
    # 2. Initialize the Explorer
    explorer = CSCCExplorer()
    
    # 3. Select 5 random rows for testing
    num_tests = 5
    random_indices = random.sample(range(len(df_csv)), num_tests)
    
    print(f"\nRunning {num_tests} random test cases...\n")
    
    passed = 0
    for idx in random_indices:
        row = df_csv.iloc[idx]
        
        # Prepare filters
        filters = {
            'run': row['run'],
            'dmgfuncpar': row['dmgfuncpar'],
            'climate': row['climate'],
            'SSP': row['SSP'],
            'RCP': row['RCP'],
            'ISO3': row['ISO3'],
            'prtp': row['prtp'],
            'eta': row['eta'],
            'dr': row['dr']
        }
        
        # Filter out NaN values
        filters = {k: v for k, v in filters.items() if pd.notna(v)}
        
        # Query explorer
        results = explorer.get_scc(**filters)
        csv_median = row['50%']
        
        # Match check
        match_found = any(abs(results['50%'] - csv_median) < 1e-9)
        
        status = "PASSED" if match_found else "FAILED"
        if match_found: passed += 1
        
        print(f"Test Index {idx}: {row['ISO3']} | {row['SSP']} | {row['run']} -> Median: {csv_median:.4f} [{status}]")

    print(f"\nValidation Summary: {passed}/{num_tests} tests passed.")

if __name__ == "__main__":
    run_validation()
