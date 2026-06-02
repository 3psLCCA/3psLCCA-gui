import pandas as pd
import time
import os

# Get paths relative to this script
ricke_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
csv_file = os.path.join(ricke_dir, 'cscc_full_v1.csv')
pkl_file = os.path.join(ricke_dir, 'cscc_full_v1.pkl')

if not os.path.exists(csv_file):
    print(f"Error: CSV file not found at {csv_file}")
else:
    print(f"Reading {csv_file}...")
    start_time = time.time()
    df = pd.read_csv(csv_file)
    end_time = time.time()
    print(f"CSV Read Time: {end_time - start_time:.4f} seconds")

    print(f"Saving to {pkl_file}...")
    start_time = time.time()
    df.to_pickle(pkl_file)
    end_time = time.time()
    print(f"Pickle Write Time: {end_time - start_time:.4f} seconds")

    # Verification read
    print(f"Verifying Pickle read...")
    start_time = time.time()
    df_check = pd.read_pickle(pkl_file)
    end_time = time.time()
    print(f"Pickle Read Time: {end_time - start_time:.4f} seconds")
    print(f"Verification successful: {len(df) == len(df_check)} rows")
