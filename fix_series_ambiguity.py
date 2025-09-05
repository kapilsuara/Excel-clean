#!/usr/bin/env python3
"""
Script to find and fix all Series ambiguity issues in main.py
"""

import re

# Read the main.py file
with open('main.py', 'r') as f:
    lines = f.readlines()

# Track all fixes made
fixes = []

# Fix patterns
for i, line in enumerate(lines):
    original = line
    
    # Fix 1: df.columns.empty -> len(df.columns) == 0
    if 'df.columns.empty' in line:
        line = line.replace('df.columns.empty', 'len(df.columns) == 0')
        fixes.append(f"Line {i+1}: Fixed df.columns.empty")
    
    # Fix 2: if df[col] patterns without aggregation
    if re.search(r'if\s+df\[[^\]]+\]\s*:', line) and not any(x in line for x in ['.any()', '.all()', 'len(', '.sum()', '.mean()']):
        fixes.append(f"Line {i+1}: Potential issue - {line.strip()}")
    
    # Fix 3: x.dtype == -> str(x.dtype) ==
    if '.dtype ==' in line or '.dtype in' in line:
        if 'str(' not in line:
            line = re.sub(r'(\w+)\.dtype\s*(==|in)', r'str(\1.dtype) \2', line)
            fixes.append(f"Line {i+1}: Fixed dtype comparison")
    
    lines[i] = line

# Write back if fixes were made
if fixes:
    print("Found and fixed the following issues:")
    for fix in fixes:
        print(f"  - {fix}")
    
    with open('main_fixed.py', 'w') as f:
        f.writelines(lines)
    
    print(f"\n✅ Fixed file saved as main_fixed.py")
    print("Run: mv main_fixed.py main.py to apply the fixes")
else:
    print("No obvious Series ambiguity issues found")

# Additional checks
print("\n🔍 Additional recommendations:")
print("1. Ensure all DataFrame column comparisons use .any() or .all()")
print("2. Use pd.api.types.is_numeric_dtype() for type checking")
print("3. Always check len(series) > 0 before operations")
print("4. Use try-except blocks around pandas operations")