"""
Configuration module for Excel cleaning Streamlit application
"""
import os
import logging

# API Configuration - Hardcoded
ANTHROPIC_API_KEY = "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"
ANTHROPIC_MODEL = "claude-3-5-sonnet-20240620"

# Logging Configuration
logging.basicConfig(
    filename='data_cleaning_log.txt', 
    level=logging.INFO, 
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Application Settings
APP_CONFIG = {
    "layout": "wide",
    "page_title": "Excel Data Cleaner",
    "page_icon": "🧹",
}

# File Processing Settings
MAX_FILE_SIZE_MB = 100
SUPPORTED_EXTENSIONS = ['.xlsx', '.xls', '.csv']
TEMP_DIR = "temp_files"

# Create temp directory if it doesn't exist
os.makedirs(TEMP_DIR, exist_ok=True)