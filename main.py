import streamlit as st
import pandas as pd
import openpyxl
from openpyxl.utils import range_boundaries
import numpy as np
import re
import logging
import os
import tempfile
import shutil
import json
import anthropic

# Set Streamlit to wide layout for full-screen experience
st.set_page_config(layout="wide")

# Set up logging
logging.basicConfig(filename='data_cleaning_log.txt', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Hardcoded Anthropic API key
ANTHROPIC_API_KEY = "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"

# CSS for layout (reverted to original - chatbot scrolls with page)
st.markdown("""
<style>
/* Main container adjustment */
.main .block-container {
    max-width: 100%;
    padding-left: 1rem;
    padding-right: 1rem;
}
</style>
""", unsafe_allow_html=True)

def validate_anthropic_api_key(api_key):
    """
    Test if Anthropic API key is valid
    """
    if not api_key or not api_key.startswith('sk-ant-'):
        return False, "Invalid API key format (should start with 'sk-ant-')"
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-sonnet-20240620",
            max_tokens=5,
            messages=[{"role": "user", "content": "test"}]
        )
        return True, "API key is valid"
    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "401" in error_msg:
            return False, "Invalid API key - please check your key"
        elif "insufficient_quota" in error_msg.lower():
            return False, "Insufficient quota - please add credits to your Anthropic account"
        elif "rate_limit" in error_msg.lower():
            return False, "Rate limit exceeded - please try again in a moment"
        else:
            return False, f"API validation error: {error_msg}"

def check_and_make_writable(input_path, temp_path):
    """
    Check if file is read-only and make it writable
    """
    if not os.access(input_path, os.W_OK):
        logging.info(f"File {input_path} is read-only. Copying to writable temporary file.")
        try:
            shutil.copy2(input_path, temp_path)
            os.chmod(temp_path, 0o666)  # Ensure write permissions
            logging.info(f"Copied to writable file: {temp_path}")
            return temp_path, True
        except Exception as e:
            logging.error(f"Failed to copy read-only file: {str(e)}")
            raise ValueError(f"Cannot make file writable: {str(e)}")
    return input_path, False

def repair_corrupted_excel(input_path, temp_path='repaired.xlsx'):
    """
    Attempt to repair a corrupted Excel file and handle read-only status
    """
    writable_path, was_read_only = check_and_make_writable(input_path, temp_path)
    
    try:
        wb = openpyxl.load_workbook(writable_path)
        logging.info(f"File loaded successfully{' (was read-only)' if was_read_only else ''}.")
        if was_read_only:
            wb.save(writable_path)  # Save to ensure format compatibility
        return wb, writable_path
    except Exception as e:
        logging.warning(f"Failed to load file normally: {str(e)}. Attempting repair.")
    
    try:
        with open(writable_path, 'r', encoding='utf-16', errors='ignore') as f:
            data = f.readlines()
        wb = openpyxl.Workbook()
        ws = wb.active
        for i, row in enumerate(data):
            cells = row.strip().split('\t')
            for j, val in enumerate(cells):
                ws.cell(row=i+1, column=j+1, value=val)
        wb.save(temp_path)
        logging.info(f"Repaired file saved to {temp_path}.")
        return openpyxl.load_workbook(temp_path), temp_path
    except Exception as e:
        logging.error(f"Repair failed: {str(e)}")
        raise ValueError("Unable to repair the file. Please check manually.")

def fill_merged_cells(ws):
    """
    Fill values in merged cells for pandas compatibility
    """
    merged_ranges = list(ws.merged_cells.ranges)
    for merged in merged_ranges:
        try:
            # Validate merged range format
            if not re.match(r'^[A-Z]+\d+:[A-Z]+\d+$', merged.coord):
                logging.warning(f"Skipping invalid merged range: {merged.coord}")
                continue
            min_col, min_row, max_col, max_row = range_boundaries(merged.coord)
            top_left_value = ws.cell(min_row, min_col).value
            # Unmerge first to avoid modifying MergedCell objects
            ws.unmerge_cells(merged.coord)
            # Assign value to all cells in the range
            for row in range(min_row, max_row + 1):
                for col in range(min_col, max_col + 1):
                    ws.cell(row=row, column=col).value = top_left_value
        except Exception as e:
            logging.error(f"Error processing merged range {merged.coord}: {str(e)}")
            continue
    logging.info(f"Processed {len(merged_ranges)} merged cell ranges")

def handle_hidden_rows_columns(ws):
    """
    Unhide all rows and columns
    """
    for row_dim in ws.row_dimensions.values():
        row_dim.hidden = False
    for col_dim in ws.column_dimensions.values():
        col_dim.hidden = False

def standardize_units_with_llm(series, api_key=ANTHROPIC_API_KEY, model='claude-3-5-sonnet-20240620'):
    """
    Use Claude to standardize units in a series
    """
    if not api_key:
        logging.warning("No API key available for LLM. Skipping.")
        return series
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        logging.error(f"Failed to initialize Anthropic client: {e}")
        return series
    
    def standardize_value(value):
        if pd.isna(value):
            return value
        prompt = f"""
        Standardize the following value to a consistent unit format.
        Detect units like %, $, currency, measurements (e.g., kg to grams if needed).
        For financial data, assume USD if not specified, and standardize to numeric if possible.
        If no unit, leave as is. Return only the standardized value.
        
        Value: {value}
        """
        try:
            response = client.messages.create(
                model=model,
                max_tokens=50,
                temperature=0.2,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text.strip()
        except Exception as e:
            logging.error(f"LLM error: {str(e)}")
            return value
    
    return series.apply(standardize_value)

def analyze_dataset_metadata(df):
    """
    Comprehensive metadata analysis of the dataset
    """
    metadata = {
        "basic_info": {
            "shape": df.shape,
            "total_cells": df.shape[0] * df.shape[1],
            "memory_usage": df.memory_usage(deep=True).sum(),
            "dtypes": df.dtypes.value_counts().to_dict()
        },
        "sample_data": {
            "random_rows": df.sample(n=min(10, len(df))).to_dict('records') if len(df) > 0 else [],
            "first_rows": df.head(5).to_dict('records') if len(df) > 0 else [],
            "column_names": list(df.columns)
        },
        "columns": {},
        "data_quality": {
            "total_null_values": df.isnull().sum().sum(),
            "null_percentage": (df.isnull().sum().sum() / (df.shape[0] * df.shape[1])) * 100,
            "duplicate_rows": df.duplicated().sum(),
            "completely_empty_rows": df.isnull().all(axis=1).sum(),
            "completely_empty_cols": df.isnull().all(axis=0).sum()
        },
        "potential_issues": []
    }
    
    for col in df.columns:
        col_data = df[col]
        col_info = {
            "dtype": str(col_data.dtype),
            "null_count": col_data.isnull().sum(),
            "null_percentage": (col_data.isnull().sum() / len(col_data)) * 100,
            "unique_count": col_data.nunique(),
            "unique_percentage": (col_data.nunique() / len(col_data)) * 100,
            "sample_values": col_data.dropna().head(5).tolist(),
            "memory_usage": col_data.memory_usage(deep=True)
        }
        
        if str(col_data.dtype) == 'object':
            non_null_data = col_data.dropna()
            if len(non_null_data) > 0:
                col_info.update({
                    "max_length": non_null_data.astype(str).str.len().max(),
                    "min_length": non_null_data.astype(str).str.len().min(),
                    "avg_length": non_null_data.astype(str).str.len().mean(),
                    "contains_numbers": non_null_data.astype(str).str.contains(r'\d', na=False).any(),
                    "contains_special_chars": non_null_data.astype(str).str.contains(r'[^\w\s]', na=False).any(),
                    "whitespace_issues": {
                        "leading_spaces": non_null_data.astype(str).str.startswith(' ').sum(),
                        "trailing_spaces": non_null_data.astype(str).str.endswith(' ').sum(),
                        "multiple_spaces": non_null_data.astype(str).str.contains(r'\s{2,}', na=False).sum()
                    },
                    "potential_categories": col_info["unique_count"] < 20,
                    "mixed_case": (non_null_data.astype(str).str.islower().sum() > 0) and (non_null_data.astype(str).str.isupper().sum() > 0),
                    "contains_emails": non_null_data.astype(str).str.contains(r'\S+@\S+', na=False).any(),
                    "contains_phones": non_null_data.astype(str).str.contains(r'\d{3}-\d{3}-\d{4}', na=False).any(),
                    "case_variations": len(non_null_data.astype(str).str.lower().unique()) < col_info["unique_count"]
                })
                date_patterns = [r'\d{4}-\d{2}-\d{2}', r'\d{2}/\d{2}/\d{4}', r'\d{2}-\d{2}-\d{4}']
                col_info["potential_dates"] = any(non_null_data.astype(str).str.contains(pattern, na=False).any() for pattern in date_patterns)
                col_info["contains_currency"] = non_null_data.astype(str).str.contains(r'[$€£¥₹]', na=False).any()
                col_info["contains_percentage"] = non_null_data.astype(str).str.contains(r'%', na=False).any()
        
        elif str(col_data.dtype) in ['int64', 'float64']:
            non_null_data = col_data.dropna()
            if len(non_null_data) > 0:
                col_info.update({
                    "min_value": non_null_data.min(),
                    "max_value": non_null_data.max(),
                    "mean": non_null_data.mean(),
                    "median": non_null_data.median(),
                    "std": non_null_data.std(),
                    "skew": non_null_data.skew(),
                    "kurtosis": non_null_data.kurt(),
                    "negative_count": (non_null_data < 0).sum(),
                    "zero_count": (non_null_data == 0).sum(),
                    "outliers_iqr": len(non_null_data[(non_null_data < non_null_data.quantile(0.25) - 1.5 * (non_null_data.quantile(0.75) - non_null_data.quantile(0.25))) | 
                                                    (non_null_data > non_null_data.quantile(0.75) + 1.5 * (non_null_data.quantile(0.75) - non_null_data.quantile(0.25)))]),
                    "outliers_zscore": len(non_null_data[np.abs((non_null_data - non_null_data.mean()) / non_null_data.std()) > 3])
                })
        
        metadata["columns"][col] = col_info
    
    for col, info in metadata["columns"].items():
        if info["null_percentage"] > 50:
            metadata["potential_issues"].append(f"Column '{col}' has {info['null_percentage']:.1f}% missing values - consider imputation or removal")
        if info["dtype"] == "object" and "whitespace_issues" in info:
            total_whitespace = sum(info["whitespace_issues"].values())
            if total_whitespace > 0:
                metadata["potential_issues"].append(f"Column '{col}' has {total_whitespace} whitespace formatting issues - trim and normalize")
        if info.get("potential_dates", False):
            metadata["potential_issues"].append(f"Column '{col}' contains potential date strings - convert to datetime with format detection")
        if info["unique_count"] == 1 and info["null_count"] == 0:
            metadata["potential_issues"].append(f"Column '{col}' has only one unique value - consider removing constant column")
        if info.get("skew", 0) > 2 or info.get("skew", 0) < -2:
            metadata["potential_issues"].append(f"Column '{col}' has high skew ({info['skew']:.2f}) - consider log transformation")
        if info.get("outliers_iqr", 0) > 0.05 * metadata["basic_info"]["shape"][0]:
            metadata["potential_issues"].append(f"Column '{col}' has many outliers ({info['outliers_iqr']}) - handle with winsorization or removal")
        if info.get("contains_emails", False):
            metadata["potential_issues"].append(f"Column '{col}' contains emails - validate format and anonymize if needed")
    
    return metadata

def generate_llm_cleaning_suggestions(metadata, api_key=ANTHROPIC_API_KEY):
    """
    Generate data cleaning suggestions using Claude, limited to cleaning processes only
    """
    if not api_key:
        return {
            "suggestions": ["No API key provided"],
            "full_content": "No API key provided",
            "confidence": "error"
        }
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        logging.error(f"Failed to initialize Anthropic client: {e}")
        return {
            "suggestions": [f"Failed to initialize Anthropic client: {str(e)}"],
            "full_content": f"Failed to initialize Anthropic client: {str(e)}",
            "confidence": "error"
        }
    
    prompt = f"""
As a data cleaning expert, analyze this dataset metadata and provide specific, actionable cleaning recommendations. Focus only on data cleaning processes such as handling missing values, standardizing formats, removing duplicates, normalizing text, and validating data types. Do not suggest machine learning, feature engineering, or any other processes beyond basic data cleaning.

DATASET OVERVIEW:
- Shape: {metadata['basic_info']['shape'][0]} rows × {metadata['basic_info']['shape'][1]} columns
- Total cells: {metadata['basic_info']['total_cells']:,}
- Null values: {metadata['data_quality']['total_null_values']} ({metadata['data_quality']['null_percentage']:.2f}%)
- Duplicate rows: {metadata['data_quality']['duplicate_rows']}
- Empty rows: {metadata['data_quality']['completely_empty_rows']}
- Empty columns: {metadata['data_quality']['completely_empty_cols']}

SAMPLE DATA (10 random rows):
{json.dumps(metadata['sample_data']['random_rows'], indent=2, default=str)[:2000]}

COLUMN DETAILS:
"""
    for col, info in metadata["columns"].items():
        prompt += f"""
Column: '{col}'
- Type: {info['dtype']}
- Null: {info['null_count']} ({info['null_percentage']:.1f}%)
- Unique: {info['unique_count']} ({info['unique_percentage']:.1f}%)
- Sample values: {info['sample_values']}
"""
        if info['dtype'] == 'object':
            prompt += f"""
- Length range: {info.get('min_length', 'N/A')}-{info.get('max_length', 'N/A')}
- Contains numbers: {info.get('contains_numbers', False)}
- Whitespace issues: {sum(info.get('whitespace_issues', {}).values())}
- Potential dates: {info.get('potential_dates', False)}
- Contains currency: {info.get('contains_currency', False)}
- Contains percentage: {info.get('contains_percentage', False)}
"""
        elif info['dtype'] in ['int64', 'float64']:
            prompt += f"""
- Range: {info.get('min_value', 'N/A')} to {info.get('max_value', 'N/A')}
- Mean: {info.get('mean', 'N/A'):.2f}
- Negative values: {info.get('negative_count', 0)}
- Zero values: {info.get('zero_count', 0)}
- Outliers: {info.get('outliers_iqr', 0)}
"""
        prompt += "\n"
    
    if metadata.get("potential_issues"):
        prompt += f"\nIDENTIFIED ISSUES:\n{chr(10).join(f'- {issue}' for issue in metadata['potential_issues'])}\n"
    
    prompt += """
Provide comprehensive data cleaning recommendations only:
1. **IMMEDIATE PRIORITIES**: Critical issues and pandas operations to fix them (e.g., remove duplicates, trim whitespace).
2. **DATA TYPE OPTIMIZATIONS**: Columns needing type conversion with reasoning (e.g., string to date).
3. **CONTENT STANDARDIZATION**: Text cleaning, date/time format standardization, numeric value formatting.
4. **MISSING VALUE HANDLING**: Simple imputation strategies like mean/median fill or constant fill.
5. **PANDAS CODE RECOMMENDATIONS**: Specific code snippets for each cleaning step (in ```python ... ``` blocks).
6. **DATA QUALITY METRICS**: Key metrics to track before/after cleaning.

Do not suggest ML, feature engineering, or advanced analytics.
"""
    
    try:
        response = client.messages.create(
            model='claude-3-5-sonnet-20240620',
            max_tokens=1500,
            temperature=0.3,
            messages=[{"role": "user", "content": prompt}]
        )
        content = response.content[0].text.strip()
        return {
            "suggestions": content.split('\n'),
            "full_content": content,
            "confidence": "high",
            "model_used": "claude-3-5-sonnet-20240620"
        }
    except Exception as e:
        error_msg = str(e)
        logging.error(f"LLM suggestion error: {error_msg}")
        if "authentication" in error_msg.lower():
            error_message = "Invalid API key. Please check your Anthropic API key."
        elif "insufficient_quota" in error_msg.lower():
            error_message = "Insufficient Anthropic quota. Please add credits to your account."
        elif "rate_limit" in error_msg.lower():
            error_message = "Rate limit exceeded. Please try again in a moment."
        else:
            error_message = f"API Error: {error_msg}"
        return {
            "suggestions": [error_message],
            "full_content": error_message,
            "confidence": "error"
        }

def extract_and_execute_code_from_suggestions(full_content, df):
    """
    Extract pandas code snippets from LLM suggestions and execute them safely
    """
    code_blocks = re.findall(r'```python\n(.*?)\n```', full_content, re.DOTALL)
    executed_changes = []
    modified_df = df.copy()
    for code in code_blocks:
        try:
            code = code.strip()
            namespace = {'df': modified_df.copy(), 'pd': pd, 'np': np}
            exec(code, namespace)
            modified_df = namespace['df']
            executed_changes.append(f"✓ Executed: {code}")
        except Exception as e:
            executed_changes.append(f"❌ Error executing code: {str(e)}\nCode: {code}")
    return modified_df, executed_changes

def clean_excel_basic(input_path, output_path, sheet_name=None, llm_api_key=ANTHROPIC_API_KEY):
    """
    Basic cleaning function with enhanced error tracking
    """
    changes_log = []
    
    try:
        original_df = pd.read_excel(input_path, sheet_name=sheet_name if sheet_name else 0)
    except Exception as e:
        changes_log.append(f"❌ Error loading data: {str(e)}")
        logging.error(f"Error loading data: {str(e)}")
        import traceback
        logging.error(f"Traceback: {traceback.format_exc()}")
        return pd.DataFrame(), changes_log
    
    try:
        wb, writable_path = repair_corrupted_excel(input_path, temp_path='temp_writable.xlsx')
        
        if sheet_name:
            ws = wb[sheet_name]
        else:
            ws = wb.active
            sheet_name = ws.title
    except Exception as e:
        changes_log.append(f"❌ Error in Excel repair/sheet selection: {str(e)}")
        logging.error(f"Error in repair/sheet: {str(e)}")
        return pd.DataFrame(), changes_log
    
    handle_hidden_rows_columns(ws)
    changes_log.append("✓ Unhidden all hidden rows and columns")
    
    merged_count = len(list(ws.merged_cells.ranges))
    fill_merged_cells(ws)
    if merged_count > 0:
        changes_log.append(f"✓ Processed {merged_count} merged cell ranges")
    
    if len(wb.sheetnames) > 1:
        logging.info(f"Extra sheets found: {wb.sheetnames}. Processing only '{sheet_name}'.")
        changes_log.append(f"ℹ️ Found {len(wb.sheetnames)} sheets, processing only '{sheet_name}'")
    
    temp_path = 'temp_clean.xlsx'
    try:
        wb.save(temp_path)
        df = pd.read_excel(temp_path, sheet_name=sheet_name)
    except Exception as e:
        changes_log.append(f"❌ Error loading processed Excel: {str(e)}")
        logging.error(f"Error loading processed Excel: {str(e)}")
        return pd.DataFrame(), changes_log
    
    original_columns = list(df.columns)
    if len(df.columns) == 0:
        logging.warning("No headers found. Assuming first row as headers.")
        df = pd.read_excel(temp_path, sheet_name=sheet_name, header=None)
        df.columns = [f"col_{i}" for i in range(df.shape[1])]
        changes_log.append(f"✓ Generated headers for {len(df.columns)} columns")
    else:
        # Handle potential NaN or non-string column names
        new_columns = []
        for col in df.columns:
            if pd.isna(col):
                new_columns.append(f"Unnamed_{len(new_columns)}")
            else:
                col_str = str(col).strip().title().replace(' ', '_')
                col_str = re.sub(r'\s+', '_', col_str)
                new_columns.append(col_str)
        
        renamed_cols = [(old, new) for old, new in zip(original_columns, new_columns) if str(old) != str(new)]
        df.columns = new_columns
        
        if renamed_cols:
            changes_log.append(f"✓ Normalized {len(renamed_cols)} column names")
            for old, new in renamed_cols[:3]:
                changes_log.append(f"  • '{old}' → '{new}'")
            if len(renamed_cols) > 3:
                changes_log.append(f"  • ... and {len(renamed_cols) - 3} more")
    
    initial_rows = len(df)
    initial_cols = len(df.columns)
    df = df.dropna(how='all', axis=0).reset_index(drop=True)
    df = df.dropna(how='all', axis=1)
    rows_removed = initial_rows - len(df)
    cols_removed = initial_cols - len(df.columns)
    if rows_removed > 0:
        changes_log.append(f"✓ Removed {rows_removed} completely blank rows")
    if cols_removed > 0:
        changes_log.append(f"✓ Removed {cols_removed} completely blank columns")
    
    obj_cols = df.select_dtypes(include=['object']).columns
    if len(obj_cols) > 0:
        # Safely trim whitespace from object columns
        for col in obj_cols:
            try:
                df[col] = df[col].astype(str).str.strip()
            except Exception as e:
                logging.warning(f"Could not trim whitespace in column {col}: {e}")
        changes_log.append(f"✓ Trimmed whitespace in {len(obj_cols)} text columns")
    
    null_filled_numeric = 0
    null_filled_text = 0
    for col in df.columns:
        null_count = df[col].isna().sum()
        if null_count > 0:
            if str(df[col].dtype) in ['float64', 'int64']:
                try:
                    non_null_values = df[col].dropna()
                    if len(non_null_values) > 0 and (non_null_values >= 0).all():
                        df[col] = df[col].fillna(0)
                        null_filled_numeric += null_count
                    else:
                        df[col] = df[col].fillna(np.nan)
                except Exception as e:
                    logging.error(f"Error handling nulls in {col}: {str(e)}")
            else:
                df[col] = df[col].fillna('MISSING')
                null_filled_text += null_count
    if null_filled_numeric > 0:
        changes_log.append(f"✓ Filled {null_filled_numeric} null numeric values with 0")
    if null_filled_text > 0:
        changes_log.append(f"✓ Filled {null_filled_text} null text values with 'MISSING'")
    
    try:
        df = df.convert_dtypes()
    except Exception as e:
        logging.warning(f"Could not convert dtypes automatically: {e}")
    
    date_cols = [col for col in df.columns if 'date' in col.lower()]
    if date_cols:
        for col in date_cols:
            df[col] = pd.to_datetime(df[col], errors='coerce', format='%Y-%m-%d')
        changes_log.append(f"✓ Standardized {len(date_cols)} date columns")
    
    initial_len = len(df)
    df = df.drop_duplicates(keep='first')
    duplicates_removed = initial_len - len(df)
    if duplicates_removed > 0:
        changes_log.append(f"✓ Removed {duplicates_removed} duplicate rows")
    logging.info(f"Removed {duplicates_removed} duplicate rows.")
    
    amount_cols = [col for col in df.columns if 'amount' in col.lower() or 'price' in col.lower()]
    negative_found = []
    for col in amount_cols:
        try:
            if col in df.columns and pd.api.types.is_numeric_dtype(df[col]):
                has_negatives = (df[col] < 0).any()
                if has_negatives:
                    negative_count = (df[col] < 0).sum()
                    negative_found.append((col, negative_count))
                    logging.warning(f"Negative values found in {col}. Flagging.")
        except Exception as e:
            logging.error(f"Error checking negatives in {col}: {str(e)}")
    if negative_found:
        changes_log.append(f"⚠️ Found negative values in {len(negative_found)} amount/price columns:")
        for col, count in negative_found:
            changes_log.append(f"  • {col}: {count} negative values")
    
    for col in df.columns:
        try:
            if col in df.columns and str(df[col].dtype) == 'object':
                # Check if column contains units
                has_units = df[col].astype(str).str.contains(r'[%$€£kg|lb|usd|etc]', regex=True, na=False).any()
                if has_units:
                    df[col] = standardize_units_with_llm(df[col], llm_api_key)
        except Exception as e:
            logging.error(f"Error standardizing units in {col}: {str(e)}")
    
    delimiter_fixed = 0
    for col in obj_cols:
        if col in df.columns:
            try:
                semicolon_count = df[col].str.contains(';', na=False).sum()
                if semicolon_count > 0:
                    df[col] = df[col].str.replace(';', ',', regex=False)
                    delimiter_fixed += semicolon_count
            except Exception as e:
                logging.error(f"Error fixing delimiters in {col}: {str(e)}")
    if delimiter_fixed > 0:
        changes_log.append(f"✓ Fixed {delimiter_fixed} inconsistent delimiters (semicolons → commas)")
    
    special_char_pattern = r'[^\x00-\x7F]+'
    special_char_cols = []
    for col in obj_cols:
        if col in df.columns:
            try:
                if df[col].astype(str).str.contains(special_char_pattern, regex=True, na=False).any():
                    special_char_cols.append(col)
                    logging.info(f"Special characters found in {col}. Cleaning.")
                    df[col] = df[col].str.replace(special_char_pattern, '', regex=True)
            except Exception as e:
                logging.error(f"Error removing special chars in {col}: {str(e)}")
    if special_char_cols:
        changes_log.append(f"✓ Removed special characters from {len(special_char_cols)} columns")
    
    df.to_excel(output_path, index=False)
    logging.info(f"Cleaned file saved to {output_path}")
    
    changes_log.append("\n📊 **Summary:**")
    if original_df is not None:
        changes_log.append(f"  • Original shape: {original_df.shape[0]} rows × {original_df.shape[1]} columns")
    changes_log.append(f"  • Cleaned shape: {df.shape[0]} rows × {df.shape[1]} columns")
    changes_log.append(f"  • Total cells processed: {df.shape[0] * df.shape[1]:,}")
    
    os.remove(temp_path)
    if writable_path != input_path:
        os.remove(writable_path)
    
    return df, changes_log

def clean_excel_with_analysis(input_path, output_path, sheet_name=None, llm_api_key=ANTHROPIC_API_KEY):
    """
    Enhanced cleaning with advanced analysis and auto-implementation for a single sheet
    """
    changes_log = [f"📊 **PHASE 1: Dataset Analysis for Sheet '{sheet_name}'**"]
    
    try:
        original_df = pd.read_excel(input_path, sheet_name=sheet_name if sheet_name else 0)
        changes_log.append(f"✓ Loaded dataset: {original_df.shape[0]} rows × {original_df.shape[1]} columns")
        metadata = analyze_dataset_metadata(original_df)
        changes_log.append("✓ Completed advanced metadata analysis")
        llm_suggestions = generate_llm_cleaning_suggestions(metadata, api_key=llm_api_key)
        changes_log.append(f"✓ Generated advanced LLM cleaning suggestions (confidence: {llm_suggestions['confidence']})")
    except Exception as e:
        changes_log.append(f"❌ Error in analysis phase: {str(e)}")
        cleaned_df, basic_changes = clean_excel_basic(input_path, output_path, sheet_name, llm_api_key)
        # Return empty metadata and llm_suggestions when there's an error
        return cleaned_df, changes_log + basic_changes, {}, {"confidence": "error", "suggestions": [], "full_content": ""}
    
    changes_log.append(f"\n🔧 **PHASE 2: Applying Basic Cleaning Operations for Sheet '{sheet_name}'**")
    cleaned_df, basic_changes = clean_excel_basic(input_path, output_path, sheet_name, llm_api_key)
    
    changes_log.append(f"\n🤖 **PHASE 3: Auto-Implementing Advanced Suggestions for Sheet '{sheet_name}'**")
    cleaned_df, implemented_changes = extract_and_execute_code_from_suggestions(llm_suggestions['full_content'], cleaned_df)
    
    all_changes = changes_log + basic_changes + implemented_changes
    
    return cleaned_df, all_changes, metadata, llm_suggestions

def process_all_sheets(input_path, llm_api_key=ANTHROPIC_API_KEY):
    """
    Process all sheets in the Excel file
    """
    wb, writable_path = repair_corrupted_excel(input_path, temp_path='temp_writable.xlsx')
    sheet_data = {}
    for sheet_name in wb.sheetnames:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as output_tmp:
            output_path = output_tmp.name
        cleaned_df, changes, metadata, llm_suggestions = clean_excel_with_analysis(writable_path, output_path, sheet_name, llm_api_key)
        sheet_data[sheet_name] = {
            "cleaned_df": cleaned_df,
            "changes": changes,
            "metadata": metadata,
            "llm_suggestions": llm_suggestions
        }
        os.unlink(output_path)
    if writable_path != input_path:
        os.unlink(writable_path)
    return sheet_data, wb.sheetnames

def apply_user_query_to_df(df, query, api_key=ANTHROPIC_API_KEY):
    """
    Use Claude to generate and execute pandas code based on user query
    """
    if not api_key:
        return df, "No API key provided for LLM."
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
    except Exception as e:
        logging.error(f"Failed to initialize Anthropic client: {e}")
        return df, f"Failed to initialize Anthropic client: {str(e)}"
    
    df_description = f"Columns: {', '.join(df.columns)}\nSample data:\n{df.head(5).to_string()}"
    prompt = f"""
Given this DataFrame description:
{df_description}

User query: {query}

Generate a Python code snippet using pandas to modify the 'df' accordingly. 
Focus only on data cleaning operations (e.g., removing columns, filling nulls, standardizing formats).
Do not include machine learning or feature engineering.
Only output the executable code (e.g., df = df.drop(columns=['Column'])).
Do not include imports or explanations. Assume pd and np are imported.
Handle errors gracefully.
"""
    try:
        response = client.messages.create(
            model='claude-3-5-sonnet-20240620',
            max_tokens=300,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}]
        )
        code = response.content[0].text.strip()
        
        # Execute the code safely
        namespace = {'df': df.copy(), 'pd': pd, 'np': np}
        exec(code, namespace)
        new_df = namespace['df']
        return new_df, f"Applied change: {code}"
    except Exception as e:
        logging.error(f"Error applying query: {str(e)}")
        return df, f"Error applying change: {str(e)}"

# Streamlit App
st.title("🧹 Advanced Excel Data Cleaner with AI Analysis")

# Validate API key at startup
with st.spinner("Validating API key..."):
    is_valid, message = validate_anthropic_api_key(ANTHROPIC_API_KEY)
if is_valid:
    st.success("🔑 API key validated successfully")
else:
    st.error(f"❌ {message}")
    st.stop()

# File uploader
uploaded_file = st.file_uploader("Upload your Excel file", type=["xlsx", "xls"])

if uploaded_file is not None:
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as input_tmp:
            input_tmp.write(uploaded_file.getvalue())
            input_path = input_tmp.name
        
        # Process all sheets
        with st.spinner("Analyzing all sheets..."):
            sheet_data, sheet_names = process_all_sheets(input_path)
        
        # Initialize session state
        if 'sheet_data' not in st.session_state:
            st.session_state.sheet_data = sheet_data
        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = {name: [] for name in sheet_names}
        
        # Dropdown to select sheet
        selected_sheet = st.selectbox("Select Sheet", sheet_names)
        
        # Split-screen layout
        left_col, right_col = st.columns([3, 1])
        
        with left_col:
            st.header(f"📊 Sheet: {selected_sheet}")
            
            # Dataset Analysis
            metadata = st.session_state.sheet_data[selected_sheet]["metadata"]
            st.subheader("Dataset Analysis")
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Total Rows", metadata["basic_info"]["shape"][0])
            with col2:
                st.metric("Total Columns", metadata["basic_info"]["shape"][1])
            with col3:
                st.metric("Null Values", f"{metadata['data_quality']['null_percentage']:.1f}%")
            
            with st.expander("📋 Sample Data (Used for AI Analysis)", expanded=False):
                if metadata["sample_data"]["random_rows"]:
                    st.subheader("Random Sample (10 rows)")
                    st.json(metadata["sample_data"]["random_rows"][:3], expanded=False)
                    st.caption("This sample data is sent to AI for intelligent cleaning recommendations")
                if metadata["sample_data"]["first_rows"]:
                    st.subheader("First 5 Rows")
                    st.json(metadata["sample_data"]["first_rows"], expanded=False)
            
            with st.expander("📋 Column Details", expanded=False):
                for col_name, col_info in metadata["columns"].items():
                    st.subheader(f"Column: {col_name}")
                    col_col1, col_col2 = st.columns(2)
                    with col_col1:
                        st.write(f"**Type:** {col_info['dtype']}")
                        st.write(f"**Null Count:** {col_info['null_count']} ({col_info['null_percentage']:.1f}%)")
                        st.write(f"**Unique Values:** {col_info['unique_count']} ({col_info['unique_percentage']:.1f}%)")
                    with col_col2:
                        st.write(f"**Sample Values:** {col_info['sample_values'][:3]}")
                        if col_info['dtype'] == 'object' and 'max_length' in col_info:
                            st.write(f"**Length Range:** {col_info['min_length']}-{col_info['max_length']}")
                        elif col_info['dtype'] in ['int64', 'float64'] and 'min_value' in col_info:
                            st.write(f"**Value Range:** {col_info['min_value']:.2f} to {col_info['max_value']:.2f}")
                            st.write(f"**Skew/Kurtosis:** {col_info.get('skew', 'N/A'):.2f}/{col_info.get('kurtosis', 'N/A'):.2f}")
                    st.divider()
            
            if metadata["potential_issues"]:
                st.subheader("⚠️ Issues Identified")
                for issue in metadata["potential_issues"]:
                    st.warning(issue)
            
            st.subheader("🤖 Advanced AI Cleaning Recommendations")
            llm_suggestions = st.session_state.sheet_data[selected_sheet]["llm_suggestions"]
            confidence_color = {"high": "🟢", "medium": "🟡", "low": "🔴", "error": "❌"}
            st.write(f"Confidence Level: {confidence_color.get(llm_suggestions['confidence'], '❓')} {llm_suggestions['confidence'].title()}")
            
            with st.expander("View AI Suggestions", expanded=True):
                for suggestion in llm_suggestions["suggestions"]:
                    if suggestion.strip():
                        st.write(suggestion)
            
            st.subheader("📝 Cleaning Operations Applied (Including Auto-Implemented)")
            with st.expander("View all changes", expanded=True):
                for change in st.session_state.sheet_data[selected_sheet]["changes"]:
                    if change.startswith("\n") or change.startswith("📊") or change.startswith("🔧") or change.startswith("🤖"):
                        st.subheader(change.replace("\n", ""))
                    elif change.startswith("  •"):
                        st.text(change)
                    elif change.startswith("✓"):
                        st.success(change)
                    elif change.startswith("⚠️"):
                        st.warning(change)
                    elif change.startswith("ℹ️"):
                        st.info(change)
                    elif "Executed:" in change:
                        st.success(change)
                    elif "Error executing" in change:
                        st.error(change)
                    else:
                        st.text(change)
            
            st.subheader("🔍 Cleaned Data Preview")
            st.dataframe(st.session_state.sheet_data[selected_sheet]["cleaned_df"], use_container_width=True)
            
            col1, col2, col3 = st.columns(3)
            with col1:
                st.metric("Current Rows", st.session_state.sheet_data[selected_sheet]["cleaned_df"].shape[0])
            with col2:
                st.metric("Current Columns", st.session_state.sheet_data[selected_sheet]["cleaned_df"].shape[1])
            with col3:
                st.metric("Total Cells", f"{st.session_state.sheet_data[selected_sheet]['cleaned_df'].shape[0] * st.session_state.sheet_data[selected_sheet]['cleaned_df'].shape[1]:,}")
            
            # Download all sheets as a single Excel file
            st.subheader("Download")
            with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as download_tmp:
                with pd.ExcelWriter(download_tmp.name, engine='openpyxl') as writer:
                    for sheet_name, data in st.session_state.sheet_data.items():
                        data["cleaned_df"].to_excel(writer, sheet_name=sheet_name, index=False)
                with open(download_tmp.name, "rb") as f:
                    st.download_button(
                        label="📥 Download All Sheets",
                        data=f,
                        file_name="cleaned_excel.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                    )
                os.unlink(download_tmp.name)
        
        with right_col:
            # Fixed chatbot container
            with st.container(height=600, border=True):
                st.header("💬 Chatbot for Data Modifications")
                st.caption(f"Enter queries like 'remove column Name' or 'fill nulls in Age with mean' to modify '{selected_sheet}'.")
                
                # Display chat history for the selected sheet
                for message in st.session_state.chat_history[selected_sheet]:
                    with st.chat_message(message["role"]):
                        st.markdown(message["content"])
                
                # User input at the bottom
                user_query = st.chat_input(f"Your query for '{selected_sheet}':")
                if user_query:
                    # Append user message
                    st.session_state.chat_history[selected_sheet].append({"role": "user", "content": user_query})
                    with st.chat_message("user"):
                        st.markdown(user_query)
                    
                    # Apply query
                    with st.spinner("Processing query..."):
                        new_df, result = apply_user_query_to_df(st.session_state.sheet_data[selected_sheet]["cleaned_df"], user_query)
                        if "Error" in result:
                            st.error(result)
                        else:
                            st.session_state.sheet_data[selected_sheet]["cleaned_df"] = new_df
                            st.session_state.chat_history[selected_sheet].append({"role": "assistant", "content": result})
                            with st.chat_message("assistant"):
                                st.markdown(result)
                    
                    # Rerun to update preview
                    st.rerun()
        
        # Clean up initial temp file
        os.unlink(input_path)
        
    except Exception as e:
        st.error(f"Error processing file: {str(e)}")
        logging.error(f"Error: {str(e)}")