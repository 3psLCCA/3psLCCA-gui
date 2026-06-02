import pandas as pd
import os

# Get path to the pkl file in the parent directory
ricke_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
pkl_path = os.path.join(ricke_dir, 'cscc_full_v1.pkl')

if not os.path.exists(pkl_path):
    print(f"Error: Pickle file not found at {pkl_path}")
else:
    # Load the pickle file
    df = pd.read_pickle(pkl_path)

    print(f"{'Column':<15} | {'Unique Count':<12} | {'Sample Unique Values (up to 5)'}")
    print("-" * 60)

    for col in df.columns:
        unique_vals = df[col].unique()
        count = len(unique_vals)
        
        # Format the unique values for display
        sample = [str(v) for v in unique_vals[:5]]
        sample_str = ", ".join(sample)
        if count > 5:
            sample_str += " ..."
        
        print(f"{col:<15} | {count:<12} | {sample_str}")
