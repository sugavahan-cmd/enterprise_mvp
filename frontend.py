import streamlit as st
import pandas as pd
import os
import tempfile
from supabase import create_client, Client

# --- 1. PROFESSIONAL UI CONFIGURATION ---
st.set_page_config(
    page_title="Automated Invoice Processing Swarm", 
    page_icon="🏢",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CUSTOM CSS INJECTION ---
st.markdown("""
    <style>
    /* Hide Streamlit default headers and footers for a white-label look */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    
    /* Professional Header Styling */
    h1 {
        color: #0f4c81;
        font-family: 'Helvetica Neue', sans-serif;
        padding-bottom: 20px;
    }
    
    /* Custom Button Styling */
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
    
    /* Metric Card Styling */
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

# --- 3. DATABASE INITIALIZATION ---
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 4. MAIN INTERFACE ---
col1, col2 = st.columns([8, 1])
with col1:
    st.title("Automated Invoice Processing Swarm")
with col2:
    st.write("") # Spacing
    if st.button("Logout"):
        st.success("Logged out successfully.")

tab1, tab2, tab3 = st.tabs(["📤 Upload & Process", "⚠️ Human Review Queue", "📊 Executive Analytics"])

# --- TAB 1: UPLOAD ---
with tab1:
    st.markdown("### Secure Document Upload")
    uploaded_file = st.file_uploader("Upload PDF Invoice", type=["pdf"], label_visibility="collapsed")
    
    if uploaded_file is not None:
        if st.button("Process Invoice"):
            with st.spinner("Encrypting and transmitting to Swarm..."):
                file_bytes = uploaded_file.read()
                file_name = uploaded_file.name
                
                with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                    tmp_file.write(file_bytes)
                    tmp_path = tmp_file.name

                try:
                    supabase.storage.from_("invoice-vault").upload(
                        path=file_name, 
                        file=tmp_path,
                        file_options={"content-type": "application/pdf"}
                    )
                    
                    supabase.table("invoice_records").insert({
                        "pdf_filename": file_name,
                        "status": "Processing"
                    }).execute()
                    
                    st.success(f"File '{file_name}' uploaded successfully. Processing initiated.")
                    
                except Exception as e:
                    st.error(f"Upload failed: {e}")
                finally:
                    if os.path.exists(tmp_path):
                        os.remove(tmp_path)

# --- TAB 2: HUMAN REVIEW ---
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

# --- TAB 3: EXECUTIVE ANALYTICS ---
with tab3:
    col_a, col_b = st.columns([8, 2])
    with col_a:
        st.markdown("### Swarm Performance Metrics")
    with col_b:
        if st.button("🔄 Refresh Data"):
            st.rerun()
            
    try:
        response = supabase.table("invoice_records").select("*").execute()
        df_all = pd.DataFrame(response.data)
        
        if df_all.empty:
            df_all = pd.DataFrame(columns=['status', 'vendor_name', 'total_amount'])

        df_clean = df_all[(df_all['status'] == 'Approved') & (df_all['vendor_name'].notnull()) & (df_all['vendor_name'] != '')]
        df_pending = df_all[df_all['status'] == 'Processing']
        df_flagged = df_all[df_all['status'] == 'Requires Review']
        
        # Metrics Row
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Approved", len(df_clean))
        col2.metric("Processing", len(df_pending))
        col3.metric("Flagged", len(df_flagged))
        
        total_cap = pd.to_numeric(df_clean['total_amount'], errors='coerce').sum() if not df_clean.empty else 0.0
        col4.metric("Capital Processed", f"₹{total_cap:,.2f}")

        st.divider()
        
        # Data Table
        if not df_all.empty:
            st.markdown("**Master Ledger**")
            st.dataframe(df_all, use_container_width=True, hide_index=True)

    except Exception as e:
        st.error(f"Error loading dashboard metrics: {e}")