"""
Data analysis and metadata generation functions
"""
import pandas as pd
import numpy as np
import logging

def analyze_dataset_metadata(df):
    """
    Generate comprehensive metadata about the dataset
    """
    metadata = {
        "basic_info": {
            "total_rows": len(df),
            "total_columns": len(df.columns),
            "memory_usage": f"{df.memory_usage(deep=True).sum() / 1024**2:.2f} MB",
            "duplicate_rows": df.duplicated().sum(),
            "duplicate_percentage": f"{(df.duplicated().sum() / len(df)) * 100:.2f}%"
        },
        "columns_info": {},
        "data_types": {},
        "missing_values": {},
        "statistical_summary": {},
        "potential_issues": [],
        "data_quality_score": 0,
        "quality_metrics": {}
    }
    
    # Analyze each column
    for col in df.columns:
        col_data = df[col]
        
        # Basic column info
        metadata["columns_info"][col] = {
            "dtype": str(col_data.dtype),
            "unique_values": col_data.nunique(),
            "missing_count": col_data.isna().sum(),
            "missing_percentage": f"{(col_data.isna().sum() / len(df)) * 100:.2f}%",
            "memory_usage": f"{col_data.memory_usage(deep=True) / 1024:.2f} KB"
        }
        
        # Data type analysis
        metadata["data_types"][col] = str(col_data.dtype)
        
        # Missing values analysis
        missing_count = col_data.isna().sum()
        if missing_count > 0:
            metadata["missing_values"][col] = {
                "count": missing_count,
                "percentage": f"{(missing_count / len(df)) * 100:.2f}%"
            }
        
        # Statistical summary for numeric columns
        if pd.api.types.is_numeric_dtype(col_data):
            metadata["statistical_summary"][col] = {
                "mean": float(col_data.mean()) if not col_data.isna().all() else None,
                "median": float(col_data.median()) if not col_data.isna().all() else None,
                "std": float(col_data.std()) if not col_data.isna().all() else None,
                "min": float(col_data.min()) if not col_data.isna().all() else None,
                "max": float(col_data.max()) if not col_data.isna().all() else None,
                "q1": float(col_data.quantile(0.25)) if not col_data.isna().all() else None,
                "q3": float(col_data.quantile(0.75)) if not col_data.isna().all() else None
            }
            
            # Check for negative values in potentially positive columns
            if any(keyword in col.lower() for keyword in ['price', 'amount', 'quantity', 'count', 'age']):
                if (col_data < 0).any():
                    negative_count = (col_data < 0).sum()
                    metadata["potential_issues"].append(
                        f"Column '{col}' contains {negative_count} negative values which might be errors"
                    )
        
        # Check for mixed data types (object columns that might be numeric)
        if str(col_data.dtype) == 'object':
            # Sample non-null values
            sample = col_data.dropna().astype(str).head(100)
            if len(sample) > 0:
                # Check if values look numeric
                numeric_pattern = sample.str.match(r'^-?\d+\.?\d*$')
                if numeric_pattern.any():
                    numeric_ratio = numeric_pattern.sum() / len(sample)
                    if numeric_ratio > 0.5:
                        metadata["potential_issues"].append(
                            f"Column '{col}' appears to contain numeric values but is stored as text"
                        )
        
        # Check for high cardinality in text columns
        if str(col_data.dtype) == 'object':
            unique_ratio = col_data.nunique() / len(df)
            if unique_ratio > 0.9 and col_data.nunique() > 50:
                metadata["potential_issues"].append(
                    f"Column '{col}' has very high cardinality ({col_data.nunique()} unique values)"
                )
    
    # Calculate data quality score
    quality_score = 100
    
    # Deduct points for issues
    missing_percentage = df.isna().sum().sum() / (len(df) * len(df.columns)) * 100
    quality_score -= min(missing_percentage * 2, 30)  # Max 30 points deduction for missing values
    
    duplicate_percentage = (df.duplicated().sum() / len(df)) * 100
    quality_score -= min(duplicate_percentage * 2, 20)  # Max 20 points deduction for duplicates
    
    # Deduct for potential issues
    quality_score -= min(len(metadata["potential_issues"]) * 5, 30)  # Max 30 points deduction
    
    quality_score = max(quality_score, 0)  # Ensure non-negative
    
    metadata["data_quality_score"] = round(quality_score, 2)
    
    # Add quality metrics
    metadata["quality_metrics"] = {
        "completeness": round(100 - missing_percentage, 2),
        "uniqueness": round(100 - duplicate_percentage, 2),
        "consistency": round(100 - min(len(metadata["potential_issues"]) * 10, 100), 2),
        "missing_percentage": round(missing_percentage, 2),
        "duplicate_rows": df.duplicated().sum()
    }
    
    # Add data patterns and anomalies
    metadata["data_patterns"] = detect_data_patterns(df)
    
    return metadata

def detect_data_patterns(df):
    """
    Detect common data patterns and anomalies
    """
    patterns = {
        "date_columns": [],
        "categorical_columns": [],
        "numeric_columns": [],
        "text_columns": [],
        "binary_columns": [],
        "id_columns": [],
        "constant_columns": [],
        "highly_correlated_pairs": []
    }
    
    for col in df.columns:
        col_data = df[col].dropna()
        
        if len(col_data) == 0:
            patterns["constant_columns"].append(col)
            continue
        
        # Check for constant columns
        if col_data.nunique() == 1:
            patterns["constant_columns"].append(col)
        
        # Check for binary columns
        elif col_data.nunique() == 2:
            patterns["binary_columns"].append(col)
        
        # Check for ID columns (high cardinality, possibly sequential)
        elif col_data.nunique() / len(col_data) > 0.95 and len(col_data) > 10:
            patterns["id_columns"].append(col)
        
        # Check for date columns
        elif str(df[col].dtype) == 'object':
            sample = col_data.astype(str).head(10)
            date_patterns = [
                r'\d{4}-\d{2}-\d{2}',  # YYYY-MM-DD
                r'\d{2}/\d{2}/\d{4}',  # MM/DD/YYYY
                r'\d{2}-\d{2}-\d{4}',  # DD-MM-YYYY
            ]
            if any(sample.str.match(pattern).any() for pattern in date_patterns):
                patterns["date_columns"].append(col)
            elif col_data.nunique() < len(col_data) * 0.5:
                patterns["categorical_columns"].append(col)
            else:
                patterns["text_columns"].append(col)
        
        # Numeric columns
        elif pd.api.types.is_numeric_dtype(df[col]):
            patterns["numeric_columns"].append(col)
    
    # Find highly correlated numeric columns
    if len(patterns["numeric_columns"]) > 1:
        numeric_df = df[patterns["numeric_columns"]].dropna()
        if len(numeric_df) > 0:
            corr_matrix = numeric_df.corr()
            high_corr_pairs = []
            for i in range(len(corr_matrix.columns)):
                for j in range(i+1, len(corr_matrix.columns)):
                    if abs(corr_matrix.iloc[i, j]) > 0.9:
                        high_corr_pairs.append({
                            "column1": corr_matrix.columns[i],
                            "column2": corr_matrix.columns[j],
                            "correlation": round(corr_matrix.iloc[i, j], 3)
                        })
            patterns["highly_correlated_pairs"] = high_corr_pairs
    
    return patterns

def extract_and_execute_code_from_suggestions(full_content, df):
    """
    Extract and execute Python code from LLM suggestions
    """
    import re
    
    # Extract code blocks from the LLM response
    code_blocks = re.findall(r'```python\n(.*?)```', full_content, re.DOTALL)
    
    executed_changes = []
    
    for code in code_blocks:
        try:
            # Create a safe execution environment
            local_vars = {'df': df.copy(), 'pd': pd, 'np': np}
            
            # Execute the code
            exec(code, {}, local_vars)
            
            # Check if DataFrame was modified
            if 'df' in local_vars:
                modified_df = local_vars['df']
                if not modified_df.equals(df):
                    executed_changes.append({
                        'code': code,
                        'success': True,
                        'result': 'Code executed successfully'
                    })
                    df = modified_df
            
        except Exception as e:
            executed_changes.append({
                'code': code,
                'success': False,
                'error': str(e)
            })
            logging.warning(f"Failed to execute LLM suggested code: {e}")
    
    return df, executed_changes