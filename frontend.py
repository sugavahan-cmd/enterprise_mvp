import streamlit as st
import requests
import PyPDF2
import sqlite3
import pandas as pd
import json
import os
import time
import base64
import plotly.express as px
import supabase

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

import streamlit as st
from supabase import create_client, Client

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
st.set_page_config(page_title="Enterprise Data Extractor", layout="wide")


st.markdown("""
    <style>
    /* Global Dashboard Font and Background */
    .stApp { background-color: #f8f9fa; }
    
    /* Modern Card Style for Human Review Queue */
    .stExpander {
        border: 1px solid #dee2e6 !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important;
        margin-bottom: 10px !important;
    }
    
    /* Header and Title Styling */
    h1 { color: #003366 !important; font-weight: 700 !important; }
    h2, h3 { color: #343a40 !important; }
    
    /* Buttons */
    div.stButton > button {
        background-color: #003366 !important;
        color: white !important;
        border-radius: 5px !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover { background-color: #00509e !important; }
    
    /* Metrics and Success Boxes */
    [data-testid="stMetricValue"] { color: #003366 !important; }
    .stSuccess, .stWarning, .stError { border-radius: 8px !important; }
    </style>
    """, unsafe_allow_html=True)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

VAULT_DIR = "secure_vault"
os.makedirs(VAULT_DIR, exist_ok=True)

if "uploader_key" not in st.session_state:
    st.session_state.uploader_key = "1"

def login():
    st.title("System Authentication")
    username = st.text_input("Username")
    password = st.text_input("Password", type="password")
    if st.button("Login"):
        if username == "admin" and password == "secure123":
            st.session_state.authenticated = True
            st.rerun()
        else:
            st.error("Unauthorized Access")

if not st.session_state.authenticated:
    login()
    st.stop()

st.title("Automated Invoice Processing Swarm")
if st.button("Logout"):
    st.session_state.authenticated = False
    st.rerun()

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
                # Add this above the line that gives the error
                try:
                    data = supabase.table("invoice_records").select("*").limit(1).execute()
                    print("Database connection test successful!")
                except Exception as e:
                    print(f"DEBUG ERROR: {e}")
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
            
            # --- THE MAGIC RESET CODE ---
            # Change the key to force the widget to rebuild itself empty
            st.session_state.uploader_key = str(time.time())
            st.rerun()

with tab2:
    try:
    # Fetch data from Supabase instead of SQLite
        response = (
        supabase.table("invoice_records")
        .select("id, audit_reason, raw_data, file_path")
        .in_("status", ["Requires Review", "Failed"])
        .execute()
    )
    
    # Convert the returned list of rows directly into a Pandas DataFrame
        df_flagged = pd.DataFrame(response.data)
    
    # Handle case where no records match to prevent DataFrame empty errors
        if df_flagged.empty:
            df_flagged = pd.DataFrame(columns=["id", "audit_reason", "raw_data", "file_path"])

    except Exception as e:
        st.error(f"Error fetching flagged invoices: {e}")
        df_flagged = pd.DataFrame(columns=["id", "audit_reason", "raw_data", "file_path"])
        
        if df_flagged.empty:
            st.success("The queue is empty. No anomalies detected.")
        else:
            st.write(f"Flagged by Sentinel: {len(df_flagged)}")
            
            for index, row in df_flagged.head(50).iterrows():
                clean_filename = row['file_path'].split('\\')[-1].split('/')[-1]
                
                with st.expander(f"Review Error ID: {row['id']} | {clean_filename}"):
                    st.error(row['audit_reason'] if row['audit_reason'] else "Unknown processing error")
                    
                    try:
                        with open(row['file_path'], "rb") as f:
                            base64_pdf = base64.b64encode(f.read()).decode('utf-8')
                        pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="300" type="application/pdf"></iframe>'
                        st.markdown(pdf_display, unsafe_allow_html=True)
                    except Exception:
                        st.warning("Original document unavailable.")
                    
                    st.divider()
                    
                    # --- THE FIX: Safe JSON Parsing ---
                    raw = {}
                    if row['raw_data']:
                        try:
                            raw = json.loads(row['raw_data'])
                        except Exception:
                            pass # If JSON is corrupted, default to empty boxes
                    
                    edit_vendor = st.text_input("Vendor Name", value=raw.get("vendor_name") or "", key=f"v_{row['id']}")
                    edit_inv = st.text_input("Invoice Number", value=raw.get("invoice_number") or "", key=f"i_{row['id']}")
                    edit_total = st.number_input("Total Amount", value=float(raw.get("total_amount") or 0.0), key=f"t_{row['id']}")
                    edit_date = st.text_input("Date", value=raw.get("date") or "", key=f"d_{row['id']}")
                    
                    if st.button("Approve & Push to DB", key=f"btn_{row['id']}"):
                        payload = {
                            "id": row['id'],
                            "vendor_name": edit_vendor,
                            "invoice_number": edit_inv,
                            "total_amount": edit_total,
                            "date": edit_date
                        }
                        res = requests.post("http://127.0.0.1:8000/api/override", json=payload)
                        if res.status_code == 200:
                            st.rerun()
                            
    except sqlite3.OperationalError:
        st.warning("Database is currently busy processing the swarm. Please wait a moment...")
    except Exception as e:
        st.error(f"System Error: {e}")

with tab3:
    if st.button("🔄 Refresh Analytics Dashboard"):
        st.rerun()
        
    try:
        response = supabase.table("invoice_records").select("*").execute()
        df_all = pd.DataFrame(response.data)
    
        if df_all.empty:
            df_all = pd.DataFrame(columns=['status', 'vendor_name', 'total_amount'])

        df_clean = df_all[(df_all['status'] == 'Approved') & (df_all['vendor_name'].notnull()) & (df_all['vendor_name'] != '')]
        df_pending = df_all[df_all['status'] == 'Processing']
        df_flagged = df_all[df_all['status'] == 'Requires Review']
    
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Approved", len(df_clean))
        col2.metric("Processing", len(df_pending))
        col3.metric("Flagged", len(df_flagged))
    
        total_cap = df_clean['total_amount'].sum() if not df_clean.empty else 0.0
        col4.metric("Capital Processed", f"₹{total_cap:,.2f}")

        st.divider()

    except Exception as e:
        st.error(f"Error loading dashboard metrics: {e}")
        
        if not df_clean.empty:
            col_chart1, col_chart2 = st.columns([1, 1])
            with col_chart1:
                vendor_sums = df_clean.groupby('vendor_name')['total_amount'].sum().reset_index()
                fig_pie = px.pie(vendor_sums, values='total_amount', names='vendor_name', title="Expenditure Distribution")
                st.plotly_chart(fig_pie, use_container_width=True)
            
            with col_chart2:
                st.write("### 📜 Enterprise Ledger")
                # Show only clean data
                st.dataframe(df_clean[['vendor_name', 'invoice_number', 'total_amount', 'date']], use_container_width=True)
                
                # Excel Download uses cleaned data
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
        st.error(f"Dashboard Error: {e}")