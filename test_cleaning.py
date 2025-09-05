#!/usr/bin/env python3
"""
Test script to find the exact line causing the Series ambiguity error
"""

import pandas as pd
import numpy as np
import tempfile
import traceback
import sys
import os

# Create a test Excel file with potential problematic data
test_data = pd.DataFrame({
    'Name': ['Alice', 'Bob', 'Charlie', None, 'David'],
    'Amount': [100, -50, 200, None, 300],
    'Price': [10.5, 20, -5, 30, None],
    'Date': ['2024-01-01', '2024-01-02', 'invalid', None, '2024-01-05'],
    'Units': ['$100', '200kg', '50%', 'test', None],
    'Special': ['test©', 'normal', 'test™', None, 'test®']
})

# Save to Excel
test_file = 'test_data.xlsx'
test_data.to_excel(test_file, index=False)

print("✅ Test Excel file created")
print(f"Shape: {test_data.shape}")
print(f"Columns: {list(test_data.columns)}")
print()

# Now test the cleaning function
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    from main import clean_excel_basic
    
    print("🧪 Testing clean_excel_basic function...")
    
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as output_tmp:
        output_path = output_tmp.name
    
    # Call the function
    cleaned_df, changes = clean_excel_basic(test_file, output_path)
    
    print("✅ Function completed successfully!")
    print(f"Cleaned shape: {cleaned_df.shape}")
    print(f"Number of changes: {len(changes)}")
    
    # Clean up
    os.unlink(test_file)
    os.unlink(output_path)
    
except Exception as e:
    print(f"❌ Error occurred: {e}")
    print("\n📍 Traceback:")
    traceback.print_exc()
    
    # Try to identify the exact issue
    print("\n🔍 Debugging hints:")
    if "ambiguous" in str(e):
        print("- Series comparison issue detected")
        print("- Check all 'if' statements with DataFrame columns")
        print("- Ensure .any(), .all(), or len() is used for Series comparisons")
    
    # Clean up
    if os.path.exists(test_file):
        os.unlink(test_file)