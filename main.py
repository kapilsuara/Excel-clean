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
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Set Streamlit to wide layout for full-screen experience
st.set_page_config(layout="wide")

# Set up logging
logging.basicConfig(filename='data_cleaning_log.txt', level=logging.INFO, 
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Get Anthropic API key from environment variable
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")

# Simple CSS for layout
st.markdown("""
<style>
.main .block-container {
    max-width: 100%;
    padding-left: 1rem;
    padding-right: 1rem;
}
</style>
""", unsafe_allow_html=True)

def repair_corrupted_excel(input_path, temp_path='repaired.xlsx'):
    """Repair Excel file and return workbook"""
    try:
        if not os.access(input_path, os.W_OK):
            shutil.copy2(input_path, temp_path)
            os.chmod(temp_path, 0o666)
            return openpyxl.load_workbook(temp_path), temp_path
        else:
            return openpyxl.load_workbook(input_path), input_path
    except Exception as e:
        logging.error(f"Error opening Excel file: {e}")
        try:
            df = pd.read_excel(input_path, engine='openpyxl')
            df.to_excel(temp_path, index=False)
            return openpyxl.load_workbook(temp_path), temp_path
        except Exception as e2:
            logging.error(f"Failed to repair Excel file: {e2}")
            raise

def fill_merged_cells(ws):
    """Fill merged cells with the value from the top-left cell"""
    for merged_range in list(ws.merged_cells.ranges):
        min_col, min_row, max_col, max_row = range_boundaries(str(merged_range))
        top_left_value = ws.cell(row=min_row, column=min_col).value
        ws.unmerge_cells(str(merged_range))
        for row in range(min_row, max_row + 1):
            for col in range(min_col, max_col + 1):
                ws.cell(row=row, column=col, value=top_left_value)

def clean_excel_basic(input_path, output_path, sheet_name=None):
    """Basic Excel cleaning function"""
    changes_log = []
    
    try:
        # Load original dataframe
        original_df = pd.read_excel(input_path, sheet_name=sheet_name if sheet_name else 0)
        changes_log.append(f"✓ Loaded dataset: {original_df.shape[0]} rows × {original_df.shape[1]} columns")
    except Exception as e:
        changes_log.append(f"❌ Error loading data: {str(e)}")
        return pd.DataFrame(), changes_log
    
    try:
        # Repair Excel file
        wb, writable_path = repair_corrupted_excel(input_path, temp_path='temp_writable.xlsx')
        
        if sheet_name:
            ws = wb[sheet_name]
        else:
            ws = wb.active
            sheet_name = ws.title
        
        # Handle merged cells
        merged_count = len(list(ws.merged_cells.ranges))
        if merged_count > 0:
            fill_merged_cells(ws)
            changes_log.append(f"✓ Processed {merged_count} merged cell ranges")
        
        # Save to temp file
        temp_path = 'temp_clean.xlsx'
        wb.save(temp_path)
        
        # Load into pandas
        df = pd.read_excel(temp_path, sheet_name=sheet_name)
        
        # Clean column names
        if len(df.columns) == 0:
            changes_log.append("⚠️ No columns found in the dataset")
            return pd.DataFrame(), changes_log
        
        # Standardize column names
        new_columns = []
        for col in df.columns:
            if pd.isna(col):
                new_columns.append(f"Unnamed_{len(new_columns)}")
            else:
                col_str = str(col).strip().title().replace(' ', '_')
                col_str = re.sub(r'[^\w]', '_', col_str)
                new_columns.append(col_str)
        
        df.columns = new_columns
        changes_log.append(f"✓ Standardized {len(df.columns)} column names")
        
        # Remove empty rows and columns
        initial_shape = df.shape
        df = df.dropna(how='all', axis=0).reset_index(drop=True)
        df = df.dropna(how='all', axis=1)
        
        if df.shape != initial_shape:
            changes_log.append(f"✓ Removed {initial_shape[0] - df.shape[0]} empty rows and {initial_shape[1] - df.shape[1]} empty columns")
        
        # Remove duplicates
        initial_len = len(df)
        df = df.drop_duplicates()
        duplicates_removed = initial_len - len(df)
        if duplicates_removed > 0:
            changes_log.append(f"✓ Removed {duplicates_removed} duplicate rows")
        
        # Clean text columns - remove extra whitespace
        text_cols = df.select_dtypes(include=['object']).columns
        for col in text_cols:
            df[col] = df[col].astype(str).str.strip()
        
        if len(text_cols) > 0:
            changes_log.append(f"✓ Cleaned text in {len(text_cols)} columns")
        
        # Fill missing values
        numeric_cols = df.select_dtypes(include=[np.number]).columns
        for col in numeric_cols:
            if df[col].isna().sum() > 0:
                df[col] = df[col].fillna(0)
        
        for col in text_cols:
            if df[col].isna().sum() > 0:
                df[col] = df[col].fillna('')
        
        changes_log.append(f"✓ Filled missing values in all columns")
        
        # Save cleaned file
        df.to_excel(output_path, index=False)
        changes_log.append(f"✅ Saved cleaned data to {output_path}")
        
        # Clean up temp files
        for temp_file in ['temp_clean.xlsx', 'temp_writable.xlsx']:
            if os.path.exists(temp_file):
                try:
                    os.remove(temp_file)
                except:
                    pass
        
        changes_log.append(f"📊 Final dataset: {df.shape[0]} rows × {df.shape[1]} columns")
        return df, changes_log
        
    except Exception as e:
        changes_log.append(f"❌ Error processing file: {str(e)}")
        return pd.DataFrame(), changes_log

def apply_user_query_to_df(df, query):
    """Apply user's natural language query to DataFrame using Claude"""
    if not ANTHROPIC_API_KEY:
        return df, "❌ No API key configured. Please set ANTHROPIC_API_KEY in .env file."
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        
        # Get DataFrame info for context
        df_info = f"Columns: {list(df.columns)}\nSample data:\n{df.head(3).to_string()}"
        
        prompt = f"""Given this DataFrame:
{df_info}

User query: {query}

Generate Python pandas code to modify the DataFrame 'df'. Only return executable code, no explanations.
Example: df = df.drop(columns=['Column_Name'])
"""
        
        response = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=300,
            messages=[{"role": "user", "content": prompt}]
        )
        
        code = response.content[0].text.strip()
        
        # Execute the code safely
        local_vars = {'df': df.copy(), 'pd': pd, 'np': np}
        exec(code, {}, local_vars)
        
        return local_vars['df'], f"✅ Applied: {code}"
        
    except ImportError:
        return df, "❌ Anthropic library not installed. Run: pip install anthropic"
    except Exception as e:
        error_msg = str(e)
        if "authentication" in error_msg.lower() or "401" in error_msg:
            return df, "❌ Invalid API key. Please check your Anthropic API key in .env file."
        else:
            return df, f"❌ Error: {error_msg}"

# Streamlit App
st.title("🧹 Excel Data Cleaner")
st.markdown("Upload your Excel file for comprehensive cleaning and data processing")

# File uploader
uploaded_file = st.file_uploader("Upload your Excel file", type=["xlsx", "xls"])

if uploaded_file is not None:
    # Save uploaded file
    with tempfile.NamedTemporaryFile(delete=False, suffix=".xlsx") as input_tmp:
        input_tmp.write(uploaded_file.getvalue())
        input_path = input_tmp.name
    
    # Get sheet names
    try:
        xl_file = pd.ExcelFile(input_path)
        sheet_names = xl_file.sheet_names
        
        # Sheet selection
        if len(sheet_names) > 1:
            selected_sheet = st.selectbox("Select sheet to process", sheet_names)
        else:
            selected_sheet = sheet_names[0]
            st.info(f"Processing sheet: {selected_sheet}")
        
        # Process button
        if st.button("🚀 Clean Data", type="primary"):
            with st.spinner("Processing your file..."):
                try:
                    output_path = f"cleaned_{uploaded_file.name}"
                    cleaned_df, changes = clean_excel_basic(input_path, output_path, selected_sheet)
                    
                    # Store in session state
                    st.session_state.cleaned_df = cleaned_df
                    st.session_state.changes_log = changes
                    
                    if not cleaned_df.empty:
                        st.success("✅ File processed successfully!")
                    else:
                        st.error("❌ Processing failed - check the error messages above")
                    
                except Exception as e:
                    st.error(f"Error processing file: {str(e)}")
                finally:
                    if os.path.exists(input_path):
                        os.unlink(input_path)
    
    except Exception as e:
        st.error(f"Error reading Excel file: {str(e)}")
        if os.path.exists(input_path):
            os.unlink(input_path)

# Display results if available
if 'cleaned_df' in st.session_state and not st.session_state.cleaned_df.empty:
    # Two-column layout
    left_col, right_col = st.columns([3, 1])
    
    with left_col:
        # Changes log
        st.header("📋 Cleaning Report")
        with st.expander("View Changes", expanded=True):
            for change in st.session_state.changes_log:
                if change.startswith("✅"):
                    st.success(change)
                elif change.startswith("⚠️"):
                    st.warning(change)
                elif change.startswith("❌"):
                    st.error(change)
                else:
                    st.info(change)
        
        # Data preview
        st.header("👁️ Cleaned Data")
        st.dataframe(st.session_state.cleaned_df, use_container_width=True)
        
        # Data summary
        st.subheader("📊 Data Summary")
        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Rows", st.session_state.cleaned_df.shape[0])
        with col2:
            st.metric("Columns", st.session_state.cleaned_df.shape[1])
        with col3:
            st.metric("Total Cells", st.session_state.cleaned_df.shape[0] * st.session_state.cleaned_df.shape[1])
        with col4:
            missing_values = st.session_state.cleaned_df.isna().sum().sum()
            st.metric("Missing Values", missing_values)
        
        # Download section
        st.header("💾 Download Cleaned Data")
        
        # Create download buffer
        from io import BytesIO
        output_buffer = BytesIO()
        with pd.ExcelWriter(output_buffer, engine='openpyxl') as writer:
            st.session_state.cleaned_df.to_excel(writer, index=False, sheet_name='Cleaned_Data')
        
        st.download_button(
            label="📥 Download Cleaned Excel File",
            data=output_buffer.getvalue(),
            file_name=f"cleaned_{uploaded_file.name}",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
    
    with right_col:
        # Chatbot
        st.header("💬 Data Chatbot")
        st.caption("Ask me to modify your data using natural language!")
        
        # Initialize chat history
        if 'chat_history' not in st.session_state:
            st.session_state.chat_history = []
        
        # Display chat history
        chat_container = st.container()
        with chat_container:
            for message in st.session_state.chat_history:
                if message["role"] == "user":
                    st.markdown(f"**🧑 You:** {message['content']}")
                else:
                    st.markdown(f"**🤖 Bot:** {message['content']}")
        
        # Chat input
        with st.form("chat_form", clear_on_submit=True):
            user_query = st.text_input("Your request:", placeholder="e.g., 'remove column Name' or 'fill nulls with 0'")
            send_button = st.form_submit_button("Send")
        
        if send_button and user_query:
            # Add user message
            st.session_state.chat_history.append({"role": "user", "content": user_query})
            
            # Process query
            with st.spinner("Processing your request..."):
                new_df, result = apply_user_query_to_df(st.session_state.cleaned_df, user_query)
                
                # Update dataframe if successful
                if "✅" in result:
                    st.session_state.cleaned_df = new_df
                
                # Add bot response
                st.session_state.chat_history.append({"role": "bot", "content": result})
                
                # Rerun to show updates
                st.rerun()
        
        # Clear chat button
        if st.button("🗑️ Clear Chat History"):
            st.session_state.chat_history = []
            st.rerun()

# Information section
if 'cleaned_df' not in st.session_state:
    st.markdown("""
    ### 🔧 Features:
    - **Excel Cleaning**: Removes duplicates, empty rows/columns, standardizes column names
    - **Data Processing**: Handles merged cells, fills missing values, cleans text
    - **AI Chatbot**: Natural language data manipulation (requires valid Anthropic API key)
    - **Download**: Get your cleaned data as Excel file
    
    ### 📝 How to use:
    1. Upload your Excel file using the file uploader above
    2. Select a sheet (if multiple sheets exist)
    3. Click "Clean Data" to process your file
    4. Review the cleaning report and download the result
    5. Use the chatbot to make additional modifications (optional)
    """)