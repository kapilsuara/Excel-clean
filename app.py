"""
Main Streamlit application entry point for Excel Data Cleaner
Run this file to start the application: streamlit run app.py
"""
import streamlit as st
import pandas as pd
import numpy as np
import json
import os
import tempfile
from datetime import datetime

# Import configuration
from config import APP_CONFIG, ANTHROPIC_API_KEY, MAX_FILE_SIZE_MB

# Import services
from llm_service import validate_anthropic_api_key, apply_user_query_to_df
from cleaning_functions import clean_excel_basic, clean_excel_with_analysis, process_all_sheets
from data_analyzer import analyze_dataset_metadata

# Configure Streamlit
st.set_page_config(
    layout=APP_CONFIG["layout"],
    page_title=APP_CONFIG["page_title"],
    page_icon=APP_CONFIG["page_icon"]
)

# Apply custom CSS for layout (reverted - chatbot scrolls with page)
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

def init_session_state():
    """Initialize session state variables"""
    if 'cleaned_df' not in st.session_state:
        st.session_state.cleaned_df = None
    if 'original_df' not in st.session_state:
        st.session_state.original_df = None
    if 'changes_log' not in st.session_state:
        st.session_state.changes_log = []
    if 'metadata' not in st.session_state:
        st.session_state.metadata = {}
    if 'llm_suggestions' not in st.session_state:
        st.session_state.llm_suggestions = {}
    if 'chat_history' not in st.session_state:
        st.session_state.chat_history = []
    if 'api_key' not in st.session_state:
        st.session_state.api_key = ANTHROPIC_API_KEY

def render_metadata_display(metadata):
    """Render metadata in an organized format"""
    if not metadata:
        return
    
    # Basic Information
    st.subheader("📊 Dataset Overview")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        st.metric("Total Rows", metadata.get('basic_info', {}).get('total_rows', 0))
    with col2:
        st.metric("Total Columns", metadata.get('basic_info', {}).get('total_columns', 0))
    with col3:
        st.metric("Memory Usage", metadata.get('basic_info', {}).get('memory_usage', 'N/A'))
    with col4:
        score = metadata.get('data_quality_score', 0)
        st.metric("Quality Score", f"{score}%", 
                 delta=f"{'Good' if score >= 70 else 'Needs Improvement'}")
    
    # Quality Metrics
    st.subheader("📈 Quality Metrics")
    metrics = metadata.get('quality_metrics', {})
    if metrics:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Completeness", f"{metrics.get('completeness', 0)}%")
        with col2:
            st.metric("Uniqueness", f"{metrics.get('uniqueness', 0)}%")
        with col3:
            st.metric("Consistency", f"{metrics.get('consistency', 0)}%")
    
    # Data Types Distribution
    if metadata.get('data_types'):
        st.subheader("🏷️ Data Types")
        dtype_counts = {}
        for dtype in metadata['data_types'].values():
            dtype_counts[dtype] = dtype_counts.get(dtype, 0) + 1
        
        dtype_df = pd.DataFrame(list(dtype_counts.items()), columns=['Type', 'Count'])
        st.bar_chart(dtype_df.set_index('Type'))
    
    # Potential Issues
    if metadata.get('potential_issues'):
        st.subheader("⚠️ Potential Issues")
        for issue in metadata['potential_issues']:
            st.warning(issue)
    
    # Data Patterns
    if metadata.get('data_patterns'):
        patterns = metadata['data_patterns']
        st.subheader("🔍 Detected Patterns")
        
        pattern_info = []
        if patterns.get('date_columns'):
            pattern_info.append(f"📅 Date columns: {', '.join(patterns['date_columns'])}")
        if patterns.get('categorical_columns'):
            pattern_info.append(f"📝 Categorical: {', '.join(patterns['categorical_columns'][:5])}")
        if patterns.get('numeric_columns'):
            pattern_info.append(f"🔢 Numeric: {', '.join(patterns['numeric_columns'][:5])}")
        if patterns.get('id_columns'):
            pattern_info.append(f"🆔 ID columns: {', '.join(patterns['id_columns'])}")
        if patterns.get('constant_columns'):
            pattern_info.append(f"⚪ Constant: {', '.join(patterns['constant_columns'])}")
        
        for info in pattern_info:
            st.info(info)

def render_llm_suggestions(suggestions):
    """Render LLM suggestions"""
    if not suggestions or suggestions.get('confidence') == 'error':
        return
    
    st.subheader("🤖 AI Analysis")
    
    # Confidence indicator
    confidence = suggestions.get('confidence', 'unknown')
    confidence_colors = {
        'high': 'green',
        'medium': 'orange',
        'low': 'red',
        'error': 'red'
    }
    
    st.markdown(f"**Confidence Level:** "
               f"<span style='color: {confidence_colors.get(confidence, 'gray')}'>"
               f"{confidence.upper()}</span>", 
               unsafe_allow_html=True)
    
    # Display suggestions
    if suggestions.get('suggestions'):
        st.write("**Recommendations:**")
        for i, suggestion in enumerate(suggestions['suggestions'][:5], 1):
            st.write(f"{i}. {suggestion}")
    
    # Full analysis in expander
    if suggestions.get('full_content'):
        with st.expander("View Full AI Analysis"):
            st.markdown(suggestions['full_content'])

def render_chatbot():
    """Render the chatbot interface for data modifications"""
    st.markdown("### 💬 Chatbot for Data Modifications")
    st.markdown("Ask me to modify your data using natural language!")
    
    # Display chat history
    for message in st.session_state.chat_history:
        if message['role'] == 'user':
            st.markdown(f"**You:** {message['content']}")
        else:
            st.markdown(f"**Assistant:** {message['content']}")
    
    # Chat input
    user_query = st.text_input("Type your request here...", key="chat_input")
    
    if st.button("Send", key="send_button"):
        if user_query and st.session_state.cleaned_df is not None:
            # Add user message to history
            st.session_state.chat_history.append({
                'role': 'user',
                'content': user_query
            })
            
            # Process the query
            with st.spinner("Processing your request..."):
                modified_df, status, changes = apply_user_query_to_df(
                    st.session_state.cleaned_df,
                    user_query,
                    st.session_state.api_key
                )
                
                # Update dataframe if successful
                if status == "Success":
                    st.session_state.cleaned_df = modified_df
                    response = f"✅ {status}. Changes: {', '.join(changes) if changes else 'Data modified as requested'}"
                else:
                    response = f"❌ {status}"
                
                # Add assistant response to history
                st.session_state.chat_history.append({
                    'role': 'assistant',
                    'content': response
                })
                
                # Rerun to update display
                st.rerun()
        elif st.session_state.cleaned_df is None:
            st.warning("Please upload and process a file first!")
    
    # Clear chat button
    if st.button("Clear Chat", key="clear_chat"):
        st.session_state.chat_history = []
        st.rerun()

def main():
    """Main application function"""
    # Initialize session state
    init_session_state()
    
    # Title and description
    st.title("🧹 Excel Data Cleaner with AI Analysis")
    st.markdown("Upload your Excel file for comprehensive cleaning and AI-powered insights")
    
    # Create main layout with columns
    col1, col2 = st.columns([3, 1])
    
    with col1:
        # API Key configuration
        with st.expander("🔑 Configure Anthropic API Key", expanded=not st.session_state.api_key):
            api_key_input = st.text_input(
                "Enter your Anthropic API Key",
                value=st.session_state.api_key or "",
                type="password",
                help="Get your API key from https://console.anthropic.com/"
            )
            
            if st.button("Validate API Key"):
                if api_key_input:
                    is_valid, message = validate_anthropic_api_key(api_key_input)
                    if is_valid:
                        st.session_state.api_key = api_key_input
                        st.success(message)
                    else:
                        st.error(message)
                else:
                    st.warning("Please enter an API key")
        
        # File upload section
        st.header("📁 Upload Excel File")
        uploaded_file = st.file_uploader(
            "Choose an Excel file",
            type=['xlsx', 'xls'],
            help=f"Maximum file size: {MAX_FILE_SIZE_MB}MB"
        )
        
        if uploaded_file:
            # Check file size
            file_size_mb = uploaded_file.size / (1024 * 1024)
            if file_size_mb > MAX_FILE_SIZE_MB:
                st.error(f"File size ({file_size_mb:.2f}MB) exceeds maximum allowed size ({MAX_FILE_SIZE_MB}MB)")
                return
            
            # Save uploaded file temporarily
            with tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx') as tmp_file:
                tmp_file.write(uploaded_file.read())
                input_path = tmp_file.name
            
            # Get sheet names
            xl_file = pd.ExcelFile(input_path)
            sheet_names = xl_file.sheet_names
            
            # Sheet selection
            if len(sheet_names) > 1:
                selected_sheet = st.selectbox("Select sheet to process", sheet_names)
            else:
                selected_sheet = sheet_names[0]
                st.info(f"Processing sheet: {selected_sheet}")
            
            # Processing options
            st.subheader("⚙️ Processing Options")
            col_opt1, col_opt2 = st.columns(2)
            
            with col_opt1:
                use_llm = st.checkbox("Enable AI Analysis", value=True, 
                                     disabled=not st.session_state.api_key,
                                     help="Requires valid Anthropic API key")
            
            with col_opt2:
                process_all = st.checkbox("Process All Sheets", value=False)
            
            # Process button
            if st.button("🚀 Clean Data", type="primary"):
                with st.spinner("Processing your file..."):
                    try:
                        # Create output path
                        output_path = f"cleaned_{uploaded_file.name}"
                        
                        if process_all:
                            # Process all sheets
                            all_sheets_data = process_all_sheets(input_path, 
                                                                st.session_state.api_key if use_llm else None)
                            
                            # Display results for each sheet
                            for sheet, data in all_sheets_data.items():
                                with st.expander(f"Sheet: {sheet}"):
                                    st.write(f"Shape: {data['dataframe'].shape}")
                                    st.write("Changes:", data['changes'][:5])
                        else:
                            # Process selected sheet
                            if use_llm and st.session_state.api_key:
                                cleaned_df, changes, metadata, suggestions = clean_excel_with_analysis(
                                    input_path, output_path, selected_sheet, st.session_state.api_key
                                )
                            else:
                                cleaned_df, changes = clean_excel_basic(
                                    input_path, output_path, selected_sheet, st.session_state.api_key
                                )
                                metadata = analyze_dataset_metadata(cleaned_df)
                                suggestions = {}
                            
                            # Store in session state
                            st.session_state.cleaned_df = cleaned_df
                            st.session_state.original_df = pd.read_excel(input_path, sheet_name=selected_sheet)
                            st.session_state.changes_log = changes
                            st.session_state.metadata = metadata
                            st.session_state.llm_suggestions = suggestions
                            
                            st.success("✅ File processed successfully!")
                            
                    except Exception as e:
                        st.error(f"Error processing file: {str(e)}")
                    finally:
                        # Clean up temp file
                        if os.path.exists(input_path):
                            os.unlink(input_path)
        
        # Display results if available
        if st.session_state.cleaned_df is not None:
            # Changes log
            st.header("📋 Cleaning Report")
            with st.expander("View Changes Log", expanded=True):
                for change in st.session_state.changes_log:
                    if change.startswith("✅"):
                        st.success(change)
                    elif change.startswith("⚠️"):
                        st.warning(change)
                    elif change.startswith("❌"):
                        st.error(change)
                    else:
                        st.info(change)
            
            # Metadata display
            if st.session_state.metadata:
                st.header("📊 Data Analysis")
                render_metadata_display(st.session_state.metadata)
            
            # LLM suggestions
            if st.session_state.llm_suggestions:
                render_llm_suggestions(st.session_state.llm_suggestions)
            
            # Data preview
            st.header("👁️ Data Preview")
            tab1, tab2, tab3 = st.tabs(["Cleaned Data", "Original Data", "Comparison"])
            
            with tab1:
                st.dataframe(st.session_state.cleaned_df.head(100))
                st.caption(f"Showing first 100 rows of {len(st.session_state.cleaned_df)} total rows")
            
            with tab2:
                if st.session_state.original_df is not None:
                    st.dataframe(st.session_state.original_df.head(100))
                    st.caption(f"Showing first 100 rows of {len(st.session_state.original_df)} total rows")
            
            with tab3:
                if st.session_state.original_df is not None:
                    col_comp1, col_comp2 = st.columns(2)
                    with col_comp1:
                        st.metric("Original Shape", 
                                 f"{st.session_state.original_df.shape[0]} × {st.session_state.original_df.shape[1]}")
                    with col_comp2:
                        st.metric("Cleaned Shape", 
                                 f"{st.session_state.cleaned_df.shape[0]} × {st.session_state.cleaned_df.shape[1]}")
            
            # Download button
            st.header("💾 Download Cleaned File")
            output_buffer = pd.ExcelWriter('cleaned_output.xlsx', engine='openpyxl')
            st.session_state.cleaned_df.to_excel(output_buffer, index=False)
            output_buffer.close()
            
            with open('cleaned_output.xlsx', 'rb') as f:
                st.download_button(
                    label="📥 Download Cleaned Excel",
                    data=f.read(),
                    file_name=f"cleaned_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
                )
    
    with col2:
        # Chatbot interface
        if st.session_state.cleaned_df is not None:
            render_chatbot()
        else:
            st.info("💬 Upload a file to start using the chatbot")

if __name__ == "__main__":
    main()