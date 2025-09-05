"""
Configuration module for Excel cleaning Streamlit application
"""
import os
import logging

# Try to load dotenv if available
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    # dotenv not installed, will use os.environ directly
    pass

# API Configuration
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
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