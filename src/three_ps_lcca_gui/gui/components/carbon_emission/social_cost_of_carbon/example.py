from ricke.cscc_explorer import CSCCExplorer

def main():
    # 1. Initialize the explorer
    # It automatically finds the .pkl file in the explorer folder
    explorer = CSCCExplorer()

    print("--- Ricke et al. CSCC Explorer Example ---")

    # 2. See what parameters you can filter by
    params = explorer.get_available_params()
    print(f"\nAvailable Parameters: {params}")

    # 3. List some available values for specific parameters
    countries = explorer.get_available_values('ISO3')
    ssps = explorer.get_available_values('SSP')
    
    print(f"\nTotal Countries: {len(countries)}")
    print(f"Sample Countries: {countries[:10]}")
    print(f"Available SSPs: {ssps}")

    # 4. Query the Social Cost of Carbon
    # Example: Get SCC for USA, under SSP2/RCP60 using the BHM Short-Run model
    print("\nQuerying: USA, SSP2, RCP60, bhm_sr...")
    results = explorer.get_scc(
        ISO3='USA', 
        SSP='SSP2', 
        RCP='rcp60', 
        run='bhm_sr'
    )

    # 5. Display the results
    # The columns 16.7%, 50%, and 83.3% represent the confidence interval and median
    if not results.empty:
        print("\nResults (First 5 rows):")
        # Selecting a few columns for cleaner output
        display_cols = ['ISO3', 'SSP', 'RCP', 'run', '50%']
        print(results[display_cols].head())
        
        median_val = results['50%'].median()
        print(f"\nAverage Median SCC for this scenario: ${median_val:.2f} per tCO2")
    else:
        print("No results found for these filters.")

if __name__ == "__main__":
    main()
