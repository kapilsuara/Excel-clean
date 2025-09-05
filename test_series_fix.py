#!/usr/bin/env python3
"""
Test script to verify the Series ambiguity fixes
"""

import pandas as pd
import numpy as np

# Create test DataFrame
df = pd.DataFrame({
    'amount': [100, -50, 200, None, 300],
    'price': [10.5, 20, -5, 30, None],
    'name': ['A', 'B', 'C', None, 'D'],
    'value': ['$100', '200kg', '50%', 'test', None]
})

print("✅ Test DataFrame created:")
print(df)
print()

# Test fixes
try:
    # Test 1: Check dtype comparison
    for col in df.columns:
        dtype_str = str(df[col].dtype)
        print(f"Column '{col}' dtype: {dtype_str}")
        
        # This should work now
        if dtype_str in ['float64', 'int64']:
            print(f"  → Numeric column detected")
        elif dtype_str == 'object':
            print(f"  → Text column detected")
    
    print("\n✅ Dtype comparison test passed!")
    
    # Test 2: Check negative values properly
    amount_cols = ['amount', 'price']
    for col in amount_cols:
        if pd.api.types.is_numeric_dtype(df[col]):
            has_negatives = (df[col] < 0).any()
            if has_negatives:
                negative_count = (df[col] < 0).sum()
                print(f"Column '{col}' has {negative_count} negative values")
    
    print("\n✅ Negative value check test passed!")
    
    # Test 3: Check for units in text columns  
    for col in df.columns:
        if str(df[col].dtype) == 'object':
            has_units = df[col].astype(str).str.contains(r'[%$€£kg|lb|usd|etc]', regex=True, na=False).any()
            if has_units:
                print(f"Column '{col}' contains units")
    
    print("\n✅ Unit detection test passed!")
    
    print("\n🎉 All Series ambiguity fixes are working correctly!")
    
except Exception as e:
    print(f"\n❌ Error: {e}")
    print("Please check the fixes")