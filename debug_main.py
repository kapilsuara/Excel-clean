#!/usr/bin/env python3
"""
Debug wrapper to find the exact location of the Series ambiguity error
"""

import sys
import traceback
from main import *

# Override the clean_excel_basic function with debugging
original_clean_excel_basic = clean_excel_basic

def debug_clean_excel_basic(input_path, output_path, sheet_name=None, llm_api_key=ANTHROPIC_API_KEY):
    """
    Wrapped version with detailed debugging
    """
    changes_log = []
    print(f"DEBUG: Starting clean_excel_basic for sheet: {sheet_name}")
    
    try:
        print("DEBUG: Loading original dataframe...")
        original_df = pd.read_excel(input_path, sheet_name=sheet_name if sheet_name else 0)
        print(f"DEBUG: Loaded {original_df.shape}")
    except Exception as e:
        print(f"DEBUG ERROR at loading: {e}")
        changes_log.append(f"❌ Error loading data: {str(e)}")
        logging.error(f"Error loading data: {str(e)}")
        return pd.DataFrame(), changes_log
    
    print("DEBUG: Repairing Excel...")
    wb, writable_path = repair_corrupted_excel(input_path, temp_path='temp_writable.xlsx')
    
    if sheet_name:
        ws = wb[sheet_name]
    else:
        ws = wb.active
        sheet_name = ws.title
    
    print(f"DEBUG: Processing sheet: {sheet_name}")
    
    try:
        print("DEBUG: Handling hidden rows/columns...")
        handle_hidden_rows_columns(ws)
        
        print("DEBUG: Filling merged cells...")
        merged_count = len(list(ws.merged_cells.ranges))
        fill_merged_cells(ws)
        
        print("DEBUG: Saving temp file...")
        temp_path = 'temp_clean.xlsx'
        wb.save(temp_path)
        
        print("DEBUG: Loading into pandas...")
        df = pd.read_excel(temp_path, sheet_name=sheet_name)
        print(f"DEBUG: DataFrame shape: {df.shape}")
        print(f"DEBUG: DataFrame columns: {list(df.columns)}")
        
        print("DEBUG: Processing columns...")
        original_columns = list(df.columns)
        
        # Add detailed debugging for each operation
        print("DEBUG: Checking for empty columns...")
        if df.columns.empty:
            print("DEBUG: Empty columns detected")
        else:
            print(f"DEBUG: Normalizing {len(df.columns)} columns...")
            # Check each column name
            for i, col in enumerate(df.columns):
                print(f"  Column {i}: {col} (type: {type(col)})")
            
            # This might be problematic
            print("DEBUG: About to normalize column names...")
            try:
                df.columns = df.columns.str.strip().str.title().str.replace(r'\s+', ' ', regex=True).str.replace(' ', '_')
            except AttributeError as e:
                print(f"DEBUG: Column normalization failed: {e}")
                print(f"DEBUG: Column types: {[type(c) for c in df.columns]}")
                # Fallback normalization
                new_cols = []
                for col in df.columns:
                    if pd.isna(col):
                        new_cols.append(f"Unnamed_{len(new_cols)}")
                    else:
                        new_cols.append(str(col).strip().title().replace(' ', '_'))
                df.columns = new_cols
        
        print("DEBUG: Dropping empty rows/columns...")
        initial_rows = len(df)
        initial_cols = len(df.columns)
        df = df.dropna(how='all', axis=0).reset_index(drop=True)
        df = df.dropna(how='all', axis=1)
        
        print(f"DEBUG: After dropping empties - shape: {df.shape}")
        
        # Continue with more debugging...
        print("DEBUG: Processing complete for basic operations")
        
    except Exception as e:
        print(f"DEBUG ERROR: {e}")
        print(f"DEBUG: Error at line: {traceback.format_exc()}")
        raise
    
    return df, changes_log

# Replace the function
clean_excel_basic = debug_clean_excel_basic

print("Debug mode enabled. Run your Streamlit app now to see detailed debugging output.")