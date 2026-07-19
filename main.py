import os
import json
import threading
from typing import Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
from supabase import create_client, Client
from core_logic.extraction import process_document_text

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

extraction_lock = threading.Lock()

class DocumentRequest(BaseModel):
    raw_text: str
    file_path: str
    session_id: str

class OverrideRequest(BaseModel):
    id: int
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    date: Optional[str] = None

@app.get("/")
def read_root():
    return {"status": "Swarm Backend Active", "version": "1.0"}

def background_processing(raw_text: str, file_path: str):
    with extraction_lock:
        try:
            result = process_document_text(raw_text)
            
            if result.get("status") == "error":
                supabase.table("invoice_records").update({
                    "status": "Failed",
                    "audit_reason": result.get("message")
                }).eq("file_path", file_path).execute()
                
            elif result.get("status") == "flagged":
                raw_dump = json.dumps(result.get("raw_extraction", {}))
                supabase.table("invoice_records").update({
                    "status": "Requires Review",
                    "audit_reason": result.get("message"),
                    "raw_data": raw_dump
                }).eq("file_path", file_path).execute()
                
            else:
                supabase.table("invoice_records").update({
                    "vendor_name": result.get("vendor_name"),
                    "invoice_number": result.get("invoice_number"),
                    "total_amount": result.get("total_amount"),
                    "invoice_date": result.get("date"),
                    "status": "Approved"
                }).eq("file_path", file_path).execute()

        except Exception as e:
            supabase.table("invoice_records").update({
                "status": "Failed",
                "audit_reason": str(e)
            }).eq("file_path", file_path).execute()

@app.post("/api/extract_async")
async def queue_extraction(request: DocumentRequest, background_tasks: BackgroundTasks):
    try:
        supabase.table("invoice_records").insert({
            "status": "Processing",
            "file_path": request.file_path,
            "session_id": request.session_id
        }).execute()

        background_tasks.add_task(background_processing, request.raw_text, request.file_path)
        
        return {"status": "success", "message": "Extraction queued"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/override")
async def approve_override(request: OverrideRequest):
    try:
        supabase.table("invoice_records").update({
            "vendor_name": request.vendor_name,
            "invoice_number": request.invoice_number,
            "total_amount": request.total_amount,
            "invoice_date": request.date,
            "status": "Approved",
            "audit_reason": "Manual Override"
        }).eq("id", request.id).execute()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))