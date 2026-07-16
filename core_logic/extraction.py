import json
import requests
import os
import time
from dotenv import load_dotenv
from typing import Optional
from pydantic import BaseModel, ValidationError

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
CEREBRAS_API_KEY = os.getenv("CEREBRAS_API_KEY")
TERTIARY_API_KEY = os.getenv("TERTIARY_API_KEY")

class InvoiceSchema(BaseModel):
    vendor_name: Optional[str] = None
    invoice_number: Optional[str] = None
    total_amount: Optional[float] = None
    date: Optional[str] = None

class RateLimitError(Exception):
    pass

def call_primary_llm(prompt: str, require_json: bool = True) -> str:
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.1-8b-instant",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post("https://api.groq.com/openai/v1/chat/completions", headers=headers, json=payload)
    
    if response.status_code == 429:
        raise RateLimitError()
        
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_secondary_llm(prompt: str, require_json: bool = True) -> str:
    headers = {
        "Authorization": f"Bearer {CEREBRAS_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "llama-3.3-70b",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post("https://api.cerebras.ai/v1/chat/completions", headers=headers, json=payload)
    
    if response.status_code == 429:
        raise RateLimitError()
        
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_tertiary_llm(prompt: str, require_json: bool = True) -> str:
    headers = {
        "Authorization": f"Bearer {TERTIARY_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post("https://api.together.xyz/v1/chat/completions", headers=headers, json=payload)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_llm(prompt: str, require_json: bool = True) -> str:
    use_fallback = os.getenv("ENABLE_FALLBACK", "false").lower() == "true"
    print(f"[SENTINEL] Fallback Mode Active: {use_fallback}")
    max_retries = 5
    
    for attempt in range(max_retries):
        try:
            print(f"[SENTINEL] Routing to Primary (Groq) - Attempt {attempt + 1}")
            return call_primary_llm(prompt, require_json)
            
        except RateLimitError:
            print("[SENTINEL] 429 Rate Limit hit on Primary.")
            
            if use_fallback:
                try:
                    print("[SENTINEL] Cascading to Secondary (Cerebras)...")
                    return call_secondary_llm(prompt, require_json)
                except Exception as e:
                    print(f"[SENTINEL] Secondary Failed: {e}")
                    try:
                        print("[SENTINEL] Cascading to Tertiary (Together AI)...")
                        return call_tertiary_llm(prompt, require_json)
                    except Exception as e2:
                        print(f"[SENTINEL] Tertiary Failed: {e2}")
                        
            wait_time = (2 ** attempt)
            print(f"[SENTINEL] Sleeping for {wait_time} seconds before retry...")
            time.sleep(wait_time)
            continue
            
        except Exception as e:
            raise e
            
    raise Exception("Max retries exceeded. API rate limit exhausted.")

def process_document_text(raw_text: str) -> dict:
    if not raw_text.strip():
        return {"status": "error", "message": "No readable text found."}

    extractor_prompt = f"""
        You are an elite Data Extraction Agent. Extract the following fields from the invoice text below:
        vendor_name, invoice_number, total_amount, date.

        CRITICAL RULES FOR NUMBERS:
        - For 'total_amount', you MUST preserve the exact decimal placement found in the text.
        - Do not strip decimals, do not move decimals, and do not append '.00' unless the original text explicitly has it.
        - Remove currency symbols and commas, but keep the fractional value perfectly intact.

        INVOICE TEXT:
        \"\"\"
        {raw_text}
        \"\"\"

        Return ONLY a raw JSON object with keys: vendor_name, invoice_number, total_amount, date.
        """

    try:
        extracted_data_str = call_llm(extractor_prompt, require_json=True)
        extracted_json = json.loads(extracted_data_str)

        auditor_prompt = f"""
        You are an elite Data Auditor Agent. Your job is to verify whether the
        extracted JSON below is fully and accurately supported by the original
        invoice text. You are NOT extracting from scratch — you are checking
        someone else's work.

        ANTI-HALLUCINATION PROTOCOL:
        - Flag as invalid if any field appears to be invented, guessed, or a
          generic placeholder (e.g., "ABC Corp", "INV-001", "1234.56") that
          does not literally appear/derive from the invoice text.
        - Flag as invalid if 'total_amount' decimal placement does not match
          the source text exactly.
        - A field being null is fine as long as it's genuinely absent from
          the source text — do not penalize legitimate nulls.
        
        You are the Audit Agent. Your ONLY job is to verify the 4 extracted fields against the Original Text.
        Original Text: {raw_text}
        Extracted JSON: {extracted_data_str}
        
        CRITICAL RULES:
        1. Only evaluate the following fields: vendor_name, invoice_number, total_amount, date. 
        2. DO NOT flag the JSON for missing fields like 'client_name', 'items', 'VAT', or 'taxes'. We do not want those fields.
        3. For 'total_amount', ignore commas, currency symbols (like $, INR, Rs), and minor rounding differences under 1.0. 
        4. Does the total_amount in the JSON numerically match the final total in the text?
        
        Return ONLY a JSON object with two keys: 
        "is_valid" (boolean true/false) and "reason" (string explaining why).
        """

        audit_result_str = call_llm(auditor_prompt, require_json=True)
        audit_json = json.loads(audit_result_str)

        if audit_json.get("is_valid"):
            validated_invoice = InvoiceSchema(**extracted_json)
            result = validated_invoice.model_dump()
            result["audit_status"] = "Approved"
            return result
        else:
            return {
                "status": "flagged",
                "message": f"Agent Auditor rejected data. Reason: {audit_json.get('reason')}",
                "raw_extraction": extracted_json
            }

    except ValidationError as e:
        return {"status": "error", "message": f"Validation Error: {str(e)}"}
    except Exception as e:
        return {"status": "error", "message": f"System Error: {str(e)}"}