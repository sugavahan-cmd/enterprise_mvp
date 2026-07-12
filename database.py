import os
from supabase import create_client, Client
from dotenv import load_dotenv

load_dotenv()
SUPABASE_URL = os.getenv("PUBLIC_URL")
SUPABASE_KEY = os.getenv("ANON_API")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

def save_invoice_to_db(vendor, inv_number, total, date, filename):
    """Pushes extracted JSON data to the Supabase Cloud PostgreSQL DB"""
    data = {
        "vendor_name": vendor,
        "invoice_number": inv_number,
        "total_amount": total,
        "invoice_date": date,
        "pdf_filename": filename
    }
    
    response = supabase.table("invoices").insert(data).execute()
    return response