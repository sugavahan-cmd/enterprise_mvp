import streamlit as st
import pandas as pd
import os
import tempfile
import plotly.express as px
import requests
import PyPDF2
import time
from supabase import create_client, Client

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = "1"

st.set_page_config(
    page_title="Automated Invoice Processing Swarm", 
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

st.markdown("""
    <style>
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    h1 {
        color: #0f4c81;
        font-family: 'Helvetica Neue', sans-serif;
        padding-bottom: 20px;
    }
    
    .stButton>button {
        background-color: #0f4c81;
        color: white;
        border-radius: 6px;
        padding: 0.5rem 1.5rem;
        font-weight: 600;
        border: none;
        transition: all 0.3s ease;
    }
    .stButton>button:hover {
        background-color: #1a5f9c;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    div[data-testid="metric-container"] {
        background-color: #ffffff;
        border: 1px solid #e2e8f0;
        padding: 15px;
        border-radius: 8px;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        border-left: 4px solid #0f4c81;
    }
    </style>
""", unsafe_allow_html=True)

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

col1, col2 = st.columns([8, 1])
with col1:
    st.title("Automated Invoice Processing Swarm")
with col2:
    st.write("")
    if st.button("Logout"):
        st.success("Logged out successfully.")

tab1, tab2, tab3 = st.tabs(["📤 Upload & Process", "⚠️ Human Review Queue", "📊 Executive Analytics"])

with tab1:
    st.write("Upload PDF invoices to extract, vault, and route financial data asynchronously.")
    
    uploaded_files = st.file_uploader("Drag and drop PDFs here (Max 15 files per batch)", type=["pdf"], accept_multiple_files=True, key=st.session_state.uploader_key)

    if uploaded_files and len(uploaded_files) > 15:
        st.error("Batch limit exceeded. Please upload a maximum of 15 invoices at a time.")
    
    elif uploaded_files:
        if st.button("Process Batch in Background"):
            st.info("Initiating asynchronous swarm. You may leave this page.")
            progress_bar = st.progress(0)
            
            for i, uploaded_file in enumerate(uploaded_files):
                file_name = f"{int(time.time())}_{uploaded_file.name}"
                file_bytes = uploaded_file.getbuffer()
                
                try:
                    data = supabase.table("invoice_records").select("*").limit(1).execute()
                except Exception as e:
                    pass
                    
                supabase.storage.from_("invoice-vault").upload(file_name, file_bytes)
                
                try:
                    pdf_reader = PyPDF2.PdfReader(uploaded_file)
                    extracted_text = ""
                    for page in pdf_reader.pages:
                        extracted_text += page.extract_text()
                    
                    payload = {"raw_text": extracted_text, "file_path": file_name}
                    requests.post("http://127.0.0.1:8000/api/extract_async", json=payload)
                except Exception as e:
                    st.error(f"Failed to queue {uploaded_file.name}")
                
                progress_bar.progress((i + 1) / len(uploaded_files))
            
            st.success("Batch successfully pushed to the asynchronous queue.")
            
            st.session_state.uploader_key = str(time.time())
            st.rerun()

with tab2:
    st.markdown("### Attention Required")
    try:
        response = (
            supabase.table("invoice_records")
            .select("id, audit_reason, raw_data, file_path")
            .in_("status", ["Requires Review", "Failed"])
            .execute()
        )
        
        df_flagged = pd.DataFrame(response.data)
        
        if df_flagged.empty:
            st.info("The queue is empty. No anomalies detected by the swarm.")
        else:
            st.dataframe(df_flagged, use_container_width=True, hide_index=True)
            
    except Exception as e:
        st.error(f"Error fetching flagged invoices: {e}")

with tab3:
    col_a, col_b = st.columns([8, 2])
    with col_a:
        st.markdown("### Executive Analytics Dashboard")
    with col_b:
        if st.button("🔄 Refresh Data"):
            st.rerun()
            
    try:
        response = supabase.table("invoice_records").select("*").execute()
        df_all = pd.DataFrame(response.data)
        
        if df_all.empty:
            df_all = pd.DataFrame(columns=['status', 'vendor_name', 'total_amount', 'invoice_number', 'date'])

        df_clean = df_all[(df_all['status'] == 'Approved') & (df_all['vendor_name'].notnull()) & (df_all['vendor_name'] != '')]
        df_pending = df_all[df_all['status'] == 'Processing']
        df_flagged = df_all[df_all['status'] == 'Requires Review']
        
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Approved", len(df_clean))
        col2.metric("Processing", len(df_pending))
        col3.metric("Flagged", len(df_flagged))
        
        total_cap = pd.to_numeric(df_clean['total_amount'], errors='coerce').sum() if not df_clean.empty else 0.0
        col4.metric("Capital Processed", f"₹{total_cap:,.2f}")

        st.divider()
        
        if not df_clean.empty:
            col_chart1, col_chart2 = st.columns([1, 1])
            with col_chart1:
                df_clean['numeric_total'] = pd.to_numeric(df_clean['total_amount'], errors='coerce').fillna(0)
                vendor_sums = df_clean.groupby('vendor_name')['numeric_total'].sum().reset_index()
                fig_pie = px.pie(vendor_sums, values='numeric_total', names='vendor_name', title="Expenditure Distribution")
                st.plotly_chart(fig_pie, use_container_width=True)
            
            with col_chart2:
                st.write("### 📜 Enterprise Ledger")
                st.dataframe(df_clean[['vendor_name', 'invoice_number', 'total_amount', 'date']], use_container_width=True, hide_index=True)
                
                csv = df_clean.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Clean Ledger (CSV)",
                    data=csv,
                    file_name='enterprise_ledger_clean.csv',
                    mime='text/csv',
                    use_container_width=True
                )
        else:
            st.info("No valid approved records to visualize.")

    except Exception as e:
        st.error(f"Error loading dashboard metrics: {e}")