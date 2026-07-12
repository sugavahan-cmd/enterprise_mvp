from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import sqlite3
import json
import time
from typing import Optional
from core_logic.extraction import process_document_text
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

DB_PATH = os.path.join(BASE_DIR, "invoices.db")
app = FastAPI()

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invoice_records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            vendor_name TEXT,
            invoice_number TEXT,
            total_amount REAL,
            date TEXT,
            status TEXT,
            audit_reason TEXT,
            raw_data TEXT,
            file_path TEXT
        )
    """)
    conn.commit()
    conn.close()

init_db()

class DocumentRequest(BaseModel):
    raw_text: str
    file_path: str

class OverrideRequest(BaseModel):
    id: int
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    date: Optional[str] = None

def background_processing(raw_text: str, file_path: str, record_id: int):
    time.sleep(3)
    try:
        result = process_document_text(raw_text)
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        
        if result.get("status") == "error":
            cursor.execute("UPDATE invoice_records SET status = 'Failed', audit_reason = ? WHERE id = ?", (result.get("message"), record_id))
        elif result.get("status") == "flagged":
            raw_dump = json.dumps(result.get("raw_extraction", {}))
            cursor.execute("UPDATE invoice_records SET status = 'Requires Review', audit_reason = ?, raw_data = ? WHERE id = ?", (result.get("message"), raw_dump, record_id))
        else:
            cursor.execute("UPDATE invoice_records SET vendor_name = ?, invoice_number = ?, total_amount = ?, date = ?, status = 'Approved' WHERE id = ?", 
            (result.get("vendor_name"), result.get("invoice_number"), result.get("total_amount"), result.get("date"), record_id))
        
        conn.commit()
        conn.close()
    except Exception as e:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("UPDATE invoice_records SET status = 'Failed', audit_reason = ? WHERE id = ?", (str(e), record_id))
        conn.commit()
        conn.close()

@app.post("/api/extract_async")
async def queue_extraction(request: DocumentRequest, background_tasks: BackgroundTasks):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO invoice_records (status, file_path)
            VALUES (?, ?)
        """, ("Processing", request.file_path))
        record_id = cursor.lastrowid
        conn.commit()
        conn.close()

        background_tasks.add_task(background_processing, request.raw_text, request.file_path, record_id)
        return {"status": "queued", "id": record_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/override")
async def approve_override(request: OverrideRequest):
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE invoice_records
            SET vendor_name = ?, invoice_number = ?, total_amount = ?, date = ?, status = 'Approved', audit_reason = 'Manual Override'
            WHERE id = ?
        """, (request.vendor_name, request.invoice_number, request.total_amount, request.date, request.id))
        conn.commit()
        conn.close()
        return {"status": "success"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))