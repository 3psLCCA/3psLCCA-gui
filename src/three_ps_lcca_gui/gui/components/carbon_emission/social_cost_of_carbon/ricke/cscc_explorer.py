import pandas as pd
import os

class CSCCExplorer:
    """
    A tool to explore the Ricke et al. (2018) Country-level Social Cost of Carbon database.
    """
    
    def __init__(self, pkl_path=None):
        if pkl_path is None:
            # Default to the pkl file in the same directory as this script
            base_dir = os.path.dirname(os.path.abspath(__file__))
            pkl_path = os.path.join(base_dir, 'cscc_full_v1.pkl')
        
        if not os.path.exists(pkl_path):
            raise FileNotFoundError(f"Pickle file not found at {pkl_path}. Please run conversion first.")
        
        self.df = pd.read_pickle(pkl_path)
        # Identify categorical/parameter columns vs result columns
        self.result_cols = ['16.7%', '50%', '83.3%']
        self.param_cols = [c for c in self.df.columns if c not in self.result_cols]

    def get_available_params(self):
        """Returns a list of all parameter names."""
        return self.param_cols

    def get_available_values(self, param):
        """Returns a sorted list of unique values for a given parameter."""
        if param not in self.df.columns:
            raise ValueError(f"Parameter '{param}' not found in dataset. Available: {self.param_cols}")
        
        # Get unique values, dropping NaNs for clean lists
        values = self.df[param].dropna().unique().tolist()
        return sorted(values, key=lambda x: str(x))

    def get_options(self):
        """
        Returns a dictionary where keys are parameter names and values 
        are lists of available unique values for that parameter.
        """
        return {param: self.get_available_values(param) for param in self.param_cols}

    def is_country_available(self, iso_code):
        """
        Checks if a country (by its ISO3 code) is available in the dataset.
        Returns True if found, False otherwise.
        """
        return iso_code.upper() in self.get_available_values('ISO3')

    def get_scc(self, **filters):
        """
        Retrieves the Social Cost of Carbon based on provided filters.
        Example: get_scc(ISO3='USA', SSP='SSP2', RCP='rcp60')
        """
        query_df = self.df.copy()
        
        for key, value in filters.items():
            if key not in self.df.columns:
                print(f"Warning: Filter '{key}' ignored (not in dataset).")
                continue
            
            # Handle list of values or single value
            if isinstance(value, list):
                query_df = query_df[query_df[key].isin(value)]
            else:
                query_df = query_df[query_df[key] == value]
        
        return query_df

if __name__ == "__main__":
    # Quick test
    explorer = CSCCExplorer()
    print("Available Parameters:", explorer.get_available_params())
    
    # Test get_options
    options = explorer.get_options()
    print("\nAvailable Options for 'run':", options['run'])
    print("Available Options for 'SSP':", options['SSP'])
    
    # Test is_country_available
    print("\nIs 'USA' available?", explorer.is_country_available('USA'))
    print("Is 'XYZ' available?", explorer.is_country_available('XYZ'))
    
    # Example query
    print("\nQuerying USA, SSP2, RCP60, BHM SR:")
    res = explorer.get_scc(ISO3='USA', SSP='SSP2', RCP='rcp60', run='bhm_sr')
    print(res[['ISO3', 'SSP', 'RCP', 'run', '50%']].head())
