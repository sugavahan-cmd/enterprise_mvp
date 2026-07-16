import streamlit as st
import requests
import PyPDF2
import pandas as pd
import json
import os
import time
import base64
import tempfile
import plotly.express as px
from supabase import create_client, Client

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

STORAGE_BUCKET = "invoice-vault"

BACKEND_URL = os.getenv("BACKEND_URL", "http://127.0.0.1:8000")

st.set_page_config(page_title="Enterprise Data Extractor", layout="wide")

st.markdown("""
    <style>
    .stApp { background-color: #f8f9fa; }
    .stExpander {
        border: 1px solid #dee2e6 !important;
        border-radius: 8px !important;
        box-shadow: 0 4px 6px rgba(0,0,0,0.05) !important;
        margin-bottom: 10px !important;
    }
    h1 { color: #003366 !important; font-weight: 700 !important; }
    h2, h3 { color: #343a40 !important; }
    div.stButton > button {
        background-color: #003366 !important;
        color: white !important;
        border-radius: 5px !important;
        border: none !important;
        padding: 0.5rem 1rem !important;
        transition: all 0.3s ease !important;
    }
    div.stButton > button:hover { background-color: #00509e !important; }
    [data-testid="stMetricValue"] { color: #003366 !important; }
    .stSuccess, .stWarning, .stError { border-radius: 8px !important; }
    </style>
    """, unsafe_allow_html=True)

if "authenticated" not in st.session_state:
    st.session_state.authenticated = False

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

    uploaded_files = st.file_uploader(
        "Drag and drop PDFs here (Max 15 files per batch)",
        type=["pdf"],
        accept_multiple_files=True,
        key=st.session_state.uploader_key,
    )

    if uploaded_files and len(uploaded_files) > 15:
        st.error("Batch limit exceeded. Please upload a maximum of 15 invoices at a time.")
    elif uploaded_files:
        if st.button("Process Batch in Background",width="stretch"):
            st.info("Initiating asynchronous swarm. You may leave this page once the batch finishes queuing.")
            progress_bar = st.progress(0)

            for i, uploaded_file in enumerate(uploaded_files):
                file_name = f"{int(time.time())}_{uploaded_file.name}"

                file_bytes = uploaded_file.getbuffer().tobytes()
                tmp_path = None
                try:
                    with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp:
                        tmp.write(file_bytes)
                        tmp_path = tmp.name

                    supabase.storage.from_(STORAGE_BUCKET).upload(
                        file_name,
                        tmp_path,
                        file_options={"content-type": "application/pdf"},
                    )
                except Exception as e:
                    st.error(f"Failed to upload {uploaded_file.name} to storage: {e}")
                    continue
                finally:
                    if tmp_path and os.path.exists(tmp_path):
                        os.remove(tmp_path)

                    try:
                        uploaded_file.seek(0)
                        pdf_reader = PyPDF2.PdfReader(uploaded_file)
                        extracted_text = ""
                        for page in pdf_reader.pages:
                            extracted_text += page.extract_text()
                    
                        payload = {"raw_text": extracted_text, "file_path": file_name}

                        response = requests.post(f"{BACKEND_URL}/api/extract_async", json=payload, timeout=120)
                        response.raise_for_status()
                    
                         
                    
                    except Exception as e:
                        st.error(f"Failed to queue {uploaded_file.name}. Reason: {e}")

                progress_bar.progress((i + 1) / len(uploaded_files))

            st.success("Batch successfully pushed to the asynchronous queue.")
            st.session_state.uploader_key = str(time.time())
            st.rerun()

with tab2:
    df_flagged = pd.DataFrame(columns=["id", "audit_reason", "raw_data", "file_path"])
    fetch_error = None
    try:
        response = (
            supabase.table("invoice_records")
            .select("id, audit_reason, raw_data, file_path")
            .in_("status", ["Requires Review", "Failed"])
            .execute()
        )
        if response.data:
            df_flagged = pd.DataFrame(response.data)
    except Exception as e:
        fetch_error = str(e)

    if fetch_error:
        st.error(f"Error fetching flagged invoices: {fetch_error}")
    elif df_flagged.empty:
        st.success("The queue is empty. No anomalies detected.")
    else:
        st.write(f"Flagged by Sentinel: {len(df_flagged)}")

        for index, row in df_flagged.head(50).iterrows():
            clean_filename = row['file_path'].split('\\')[-1].split('/')[-1]

            with st.expander(f"Review Error ID: {row['id']} | {clean_filename}"):
                st.error(row['audit_reason'] if row['audit_reason'] else "Unknown processing error")

                try:
                    signed = supabase.storage.from_(STORAGE_BUCKET).create_signed_url(row['file_path'], 3600)
                    pdf_url = signed.get("signedURL") or signed.get("signedUrl")
                    if pdf_url:
                        st.markdown(
                            f'<iframe src="{pdf_url}" width="100%" height="300"></iframe>',
                            unsafe_allow_html=True,
                        )
                    else:
                        st.warning("Original document unavailable.")
                except Exception:
                    st.warning("Original document unavailable.")

                st.divider()

                raw = {}
                if row['raw_data']:
                    try:
                        raw = json.loads(row['raw_data']) if isinstance(row['raw_data'], str) else row['raw_data']
                    except Exception:
                        pass

                edit_vendor = st.text_input("Vendor Name", value=raw.get("vendor_name") or "", key=f"v_{row['id']}")
                edit_inv = st.text_input("Invoice Number", value=raw.get("invoice_number") or "", key=f"i_{row['id']}")
                try:
                    default_total = float(raw.get("total_amount") or 0.0)
                except (TypeError, ValueError):
                    default_total = 0.0
                edit_total = st.number_input("Total Amount", value=default_total, key=f"t_{row['id']}")
                edit_date = st.text_input("Date", value=raw.get("date") or "", key=f"d_{row['id']}")

                if st.button("Approve & Push to DB", key=f"btn_{row['id']}"):
                    payload = {
                        "id": row['id'],
                        "vendor_name": edit_vendor,
                        "invoice_number": edit_inv,
                        "total_amount": edit_total,
                        "date": edit_date,
                    }
                    try:
                        res = requests.post(f"{BACKEND_URL}/api/override", json=payload, timeout=10)
                        if res.status_code == 200:
                            st.rerun()
                        else:
                            st.error(f"Override failed: server returned {res.status_code}")
                    except requests.RequestException as e:
                        st.error(f"Could not reach backend: {e}")

with tab3:
    if st.button("🔄 Refresh Analytics Dashboard"):
        st.rerun()

    fetch_error = None
    clean_records = []
    
    try:
        response = supabase.table("invoice_records").select("status, vendor_name, invoice_number, total_amount, invoice_date").execute()
        if response.data:
            for row in response.data:
                clean_records.append({
                    'status': str(row.get('status') or 'Unknown'),
                    'vendor_name': str(row.get('vendor_name') or 'Unknown'),
                    'invoice_number': str(row.get('invoice_number') or 'Pending'),
                    'total_amount': float(row.get('total_amount') or 0.0),
                    'invoice_date': str(row.get('invoice_date') or 'Pending')
                })
    except Exception as e:
        fetch_error = str(e)

    if fetch_error:
        st.error(f"Error loading dashboard metrics: {fetch_error}")
    else:
        df_all = pd.DataFrame(clean_records)
        
        if df_all.empty:
            df_all = pd.DataFrame(columns=['status', 'vendor_name', 'invoice_number', 'total_amount', 'invoice_date'])

        df_clean = df_all[
            (df_all['status'] == 'Approved') & 
            (df_all['vendor_name'] != 'Unknown')
        ].copy()
        
        df_pending = df_all[df_all['status'] == 'Processing']
        
        df_flagged_view = df_all[df_all['status'].isin(['Requires Review', 'Failed'])]

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Approved", len(df_clean))
        col2.metric("Processing", len(df_pending))
        col3.metric("Flagged", len(df_flagged_view))

        st.divider()

        if not df_clean.empty:
            col_chart1, col_chart2 = st.columns([1, 1])
            with col_chart1:
                vendor_sums = df_clean.groupby('vendor_name')['total_amount'].sum().reset_index()
                fig_pie = px.pie(vendor_sums, values='total_amount', names='vendor_name', title="Expenditure Distribution")
                st.plotly_chart(fig_pie)

            with col_chart2:
                st.write("### 📜 Enterprise Ledger")
                st.dataframe(df_clean[['vendor_name', 'invoice_number', 'total_amount', 'invoice_date']], width="stretch")

                csv = df_clean.to_csv(index=False).encode('utf-8')
                st.download_button(
                    label="📥 Download Clean Ledger (CSV)",
                    data=csv,
                    file_name='enterprise_ledger_clean.csv',
                    mime='text/csv',
                    width="stretch",
                )
        else:
            st.info("No valid approved records to visualize.")