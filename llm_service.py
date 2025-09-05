"""
LLM Service module for Anthropic Claude integration
"""
import anthropic
import json
import logging
import re
import pandas as pd
import numpy as np
from config import ANTHROPIC_API_KEY, ANTHROPIC_MODEL

def validate_anthropic_api_key(api_key):
    """
    Test if Anthropic API key is valid
    """
    if not api_key or not api_key.startswith('sk-ant-'):
        return False, "Invalid API key format (should start with 'sk-ant-')"
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
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

def standardize_units_with_llm(series, api_key=ANTHROPIC_API_KEY, model=ANTHROPIC_MODEL):
    """
    Use LLM to standardize units in a column
    """
    if not api_key:
        return series, []
    
    unique_values = series.dropna().unique()[:20]
    
    prompt = f"""Analyze these values from a data column and identify if they contain mixed units or formats:
    {list(unique_values)}
    
    If units are mixed, provide a JSON response with:
    1. "has_mixed_units": true/false
    2. "standardization_map": a dictionary mapping original values to standardized values
    3. "standard_unit": the recommended standard unit
    
    Only respond with valid JSON."""
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=model,
            max_tokens=500,
            messages=[{"role": "user", "content": prompt}]
        )
        
        result = json.loads(response.content[0].text)
        
        if result.get('has_mixed_units') and result.get('standardization_map'):
            standardized = series.map(result['standardization_map']).fillna(series)
            changes = [f"Standardized units to {result.get('standard_unit', 'standard format')}"]
            return standardized, changes
    except Exception as e:
        logging.warning(f"LLM standardization failed: {e}")
    
    return series, []

def generate_llm_cleaning_suggestions(metadata, api_key=ANTHROPIC_API_KEY):
    """
    Generate cleaning suggestions based on dataset metadata using Claude API
    """
    if not api_key or not api_key.startswith('sk-ant-'):
        return {
            "confidence": "error",
            "suggestions": ["LLM not available - Invalid or missing Anthropic API key"],
            "full_content": ""
        }
    
    try:
        client = anthropic.Anthropic(api_key=api_key)
        
        # Prepare the prompt with metadata
        prompt = f"""Analyze this Excel dataset metadata and provide cleaning recommendations:

DATASET METADATA:
{json.dumps(metadata, indent=2)}

Please provide:
1. Data quality assessment (score 1-10)
2. Identified issues
3. Specific cleaning recommendations
4. Python code suggestions for pandas operations

Focus on:
- Data type consistency
- Missing values handling
- Outlier detection
- Format standardization
- Column naming conventions

Format your response with clear sections and include executable Python code where appropriate.
Make sure any Python code uses the DataFrame variable name 'df'."""

        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        llm_response = response.content[0].text
        
        # Parse key suggestions
        suggestions = []
        lines = llm_response.split('\n')
        for line in lines:
            if any(keyword in line.lower() for keyword in ['recommend', 'suggest', 'should', 'consider']):
                suggestions.append(line.strip())
        
        # Determine confidence based on issues found
        total_issues = (
            metadata.get('quality_metrics', {}).get('missing_percentage', 0) +
            metadata.get('quality_metrics', {}).get('duplicate_rows', 0) +
            len(metadata.get('potential_issues', []))
        )
        
        if total_issues > 20:
            confidence = "low"
        elif total_issues > 10:
            confidence = "medium"
        else:
            confidence = "high"
        
        return {
            "confidence": confidence,
            "suggestions": suggestions[:5] if suggestions else ["Dataset appears clean"],
            "full_content": llm_response
        }
        
    except Exception as e:
        logging.error(f"LLM API error: {str(e)}")
        return {
            "confidence": "error",
            "suggestions": [f"LLM Error: {str(e)}"],
            "full_content": ""
        }

def apply_user_query_to_df(df, query, api_key=ANTHROPIC_API_KEY):
    """
    Apply user's natural language query to DataFrame using LLM
    """
    if not api_key:
        return df, "API key not configured", []
    
    # Get DataFrame info for context
    df_info = {
        "shape": df.shape,
        "columns": list(df.columns),
        "dtypes": {col: str(df[col].dtype) for col in df.columns},
        "sample": df.head(3).to_dict()
    }
    
    prompt = f"""You are a data manipulation assistant. Convert the user's request into executable Python pandas code.

DataFrame Info:
{json.dumps(df_info, indent=2)}

User Request: {query}

Provide ONLY the Python code to modify the DataFrame 'df'. 
- Use proper pandas operations
- The code should return the modified DataFrame
- Include error handling
- Start code with ```python and end with ```

Example format:
```python
# Your code here
df = df.operation()
```"""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        
        llm_response = response.content[0].text
        
        # Extract code from response
        code_match = re.search(r'```python\n(.*?)```', llm_response, re.DOTALL)
        if code_match:
            code = code_match.group(1)
            
            # Execute the code
            local_vars = {'df': df.copy(), 'pd': pd, 'np': np}
            exec(code, {}, local_vars)
            
            modified_df = local_vars.get('df', df)
            changes = []
            
            # Detect changes
            if not modified_df.equals(df):
                if modified_df.shape != df.shape:
                    changes.append(f"Shape changed from {df.shape} to {modified_df.shape}")
                if list(modified_df.columns) != list(df.columns):
                    changes.append(f"Columns modified")
                changes.append(f"Applied: {query}")
            
            return modified_df, "Success", changes
        else:
            return df, "Could not extract code from LLM response", []
            
    except Exception as e:
        return df, f"Error: {str(e)}", []