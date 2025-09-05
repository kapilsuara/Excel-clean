"""
Main cleaning functions that orchestrate the cleaning process
"""
import pandas as pd
import numpy as np
import logging
import os
import tempfile
import re
from excel_processor import (
    repair_corrupted_excel, fill_merged_cells, handle_hidden_rows_columns,
    clean_text_column, detect_and_convert_dates, clean_numeric_column,
    detect_outliers, standardize_column_names, remove_duplicate_rows,
    handle_missing_values
)
from data_analyzer import analyze_dataset_metadata, extract_and_execute_code_from_suggestions
from llm_service import standardize_units_with_llm, generate_llm_cleaning_suggestions
from config import ANTHROPIC_API_KEY

def clean_excel_basic(input_path, output_path, sheet_name=None, llm_api_key=ANTHROPIC_API_KEY):
    """
    Basic Excel cleaning without LLM analysis
    """
    changes_log = []
    
    try:
        # Load original dataframe for comparison
        original_df = pd.read_excel(input_path, sheet_name=sheet_name if sheet_name else 0)
    except Exception as e:
        changes_log.append(f"❌ Error loading data: {str(e)}")
        logging.error(f"Error loading data: {str(e)}")
        return pd.DataFrame(), changes_log
    
    # Repair and prepare Excel file
    wb, writable_path = repair_corrupted_excel(input_path, temp_path='temp_writable.xlsx')
    
    if sheet_name:
        ws = wb[sheet_name]
    else:
        ws = wb.active
        sheet_name = ws.title
    
    # Process Excel-specific issues
    handle_hidden_rows_columns(ws)
    merged_count = len(list(ws.merged_cells.ranges))
    if merged_count > 0:
        fill_merged_cells(ws)
        changes_log.append(f"✓ Unmerged and filled {merged_count} merged cell ranges")
    
    # Save temporary file
    temp_path = 'temp_clean.xlsx'
    wb.save(temp_path)
    
    # Load into pandas
    df = pd.read_excel(temp_path, sheet_name=sheet_name)
    
    # Clean column names
    original_columns = list(df.columns)
    
    if len(df.columns) == 0:
        changes_log.append("⚠️ No columns found in the dataset")
    else:
        new_columns = standardize_column_names(df.columns)
        if new_columns != list(df.columns):
            df.columns = new_columns
            changes_log.append(f"✓ Standardized {len(df.columns)} column names")
    
    # Remove empty rows and columns
    initial_shape = df.shape
    df = df.dropna(how='all', axis=0).reset_index(drop=True)
    df = df.dropna(how='all', axis=1)
    
    if df.shape != initial_shape:
        changes_log.append(f"✓ Removed {initial_shape[0] - df.shape[0]} empty rows and {initial_shape[1] - df.shape[1]} empty columns")
    
    # Clean text columns
    text_cols_cleaned = 0
    for col in df.columns:
        if str(df[col].dtype) == 'object':
            original_col = df[col].copy()
            df[col] = clean_text_column(df[col])
            if not df[col].equals(original_col):
                text_cols_cleaned += 1
    
    if text_cols_cleaned > 0:
        changes_log.append(f"✓ Cleaned special characters from {text_cols_cleaned} text columns")
    
    # Convert date columns
    date_cols_converted = 0
    for col in df.columns:
        original_col = df[col].copy()
        df[col] = detect_and_convert_dates(df[col])
        if not df[col].equals(original_col):
            date_cols_converted += 1
    
    if date_cols_converted > 0:
        changes_log.append(f"✓ Converted {date_cols_converted} columns to datetime format")
    
    # Clean numeric columns
    numeric_cols_cleaned = 0
    for col in df.columns:
        if str(df[col].dtype) == 'object':
            original_col = df[col].copy()
            df[col] = clean_numeric_column(df[col])
            if not df[col].equals(original_col):
                numeric_cols_cleaned += 1
    
    if numeric_cols_cleaned > 0:
        changes_log.append(f"✓ Converted {numeric_cols_cleaned} columns from text to numeric")
    
    # Remove duplicates
    df, removed_rows = remove_duplicate_rows(df)
    if removed_rows > 0:
        changes_log.append(f"✓ Removed {removed_rows} duplicate rows")
    
    # Handle missing values
    df, missing_changes = handle_missing_values(df, strategy='auto')
    if missing_changes:
        changes_log.extend([f"✓ {change}" for change in missing_changes[:3]])  # Limit to 3 messages
    
    # Detect outliers
    outliers = detect_outliers(df)
    if outliers:
        for col, info in list(outliers.items())[:3]:  # Report top 3
            changes_log.append(f"⚠️ Column '{col}' has {info['count']} outliers ({info['percentage']:.1f}%)")
    
    # Standardize units with LLM if available
    if llm_api_key:
        for col in df.columns:
            if str(df[col].dtype) == 'object':
                col_sample = df[col].dropna().astype(str).head(20)
                # Check if column might contain units
                if col_sample.str.contains(r'[%$€£kg|lb|m²|ft|cm|mm|°]', regex=True).any():
                    df[col], unit_changes = standardize_units_with_llm(df[col], llm_api_key)
                    if unit_changes:
                        changes_log.extend([f"✓ {change}" for change in unit_changes])
    
    # Check for negative values in amount/price columns
    for col in df.columns:
        if any(keyword in col.lower() for keyword in ['amount', 'price', 'cost', 'revenue']):
            if pd.api.types.is_numeric_dtype(df[col]):
                negative_count = (df[col] < 0).sum()
                if negative_count > 0:
                    df.loc[df[col] < 0, col] = df[col].abs()
                    changes_log.append(f"✓ Fixed {negative_count} negative values in '{col}'")
    
    # Save the cleaned file
    try:
        df.to_excel(output_path, index=False, sheet_name=sheet_name)
        changes_log.append(f"✅ Saved cleaned data to {output_path}")
        logging.info(f"Successfully cleaned and saved: {output_path}")
    except Exception as e:
        changes_log.append(f"❌ Error saving file: {str(e)}")
        logging.error(f"Error saving file: {str(e)}")
    
    # Clean up temporary files
    for temp_file in ['temp_clean.xlsx', 'temp_writable.xlsx']:
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except:
                pass
    
    # Add summary
    changes_log.insert(0, f"📊 Final dataset: {df.shape[0]} rows × {df.shape[1]} columns")
    
    return df, changes_log

def clean_excel_with_analysis(input_path, output_path, sheet_name=None, llm_api_key=ANTHROPIC_API_KEY):
    """
    Clean Excel file with LLM-powered analysis
    """
    changes_log = []
    
    try:
        # First perform basic cleaning
        cleaned_df, basic_changes = clean_excel_basic(input_path, output_path, sheet_name, llm_api_key)
        changes_log.extend(basic_changes)
        
        if cleaned_df.empty:
            return cleaned_df, changes_log, {}, {"confidence": "error", "suggestions": [], "full_content": ""}
        
        # Generate metadata
        metadata = analyze_dataset_metadata(cleaned_df)
        
        # Get LLM suggestions if API key is available
        llm_suggestions = {"confidence": "none", "suggestions": [], "full_content": ""}
        if llm_api_key:
            llm_suggestions = generate_llm_cleaning_suggestions(metadata, llm_api_key)
            
            # Try to execute LLM suggested code
            if llm_suggestions.get('full_content'):
                cleaned_df, code_changes = extract_and_execute_code_from_suggestions(
                    llm_suggestions['full_content'], 
                    cleaned_df
                )
                for change in code_changes:
                    if change['success']:
                        changes_log.append(f"✓ Applied LLM suggested transformation")
                    else:
                        changes_log.append(f"⚠️ Failed to apply LLM suggestion: {change.get('error', 'Unknown error')}")
        
        # Save the final cleaned file
        cleaned_df.to_excel(output_path, index=False, sheet_name=sheet_name if sheet_name else 'Sheet1')
        
        return cleaned_df, changes_log, metadata, llm_suggestions
        
    except Exception as e:
        error_msg = f"Error processing file: {str(e)}"
        changes_log.append(f"❌ {error_msg}")
        logging.error(error_msg)
        # Return 4 values even on error
        return pd.DataFrame(), changes_log + [error_msg], {}, {"confidence": "error", "suggestions": [], "full_content": ""}

def process_all_sheets(input_path, llm_api_key=ANTHROPIC_API_KEY):
    """
    Process all sheets in an Excel file
    """
    all_sheets_data = {}
    
    try:
        xl_file = pd.ExcelFile(input_path)
        sheet_names = xl_file.sheet_names
        
        for sheet in sheet_names:
            output_path = f"cleaned_{sheet}.xlsx"
            cleaned_df, changes, metadata, suggestions = clean_excel_with_analysis(
                input_path, output_path, sheet, llm_api_key
            )
            
            all_sheets_data[sheet] = {
                'dataframe': cleaned_df,
                'changes': changes,
                'metadata': metadata,
                'suggestions': suggestions
            }
            
    except Exception as e:
        logging.error(f"Error processing sheets: {str(e)}")
        
    return all_sheets_data