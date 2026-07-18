import json
import requests
import os
import time
from dotenv import load_dotenv
from typing import Optional
from pydantic import BaseModel, ValidationError

load_dotenv()
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
SAMBANOVA_API_KEY = os.getenv("SAMBANOVA_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

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
        "Authorization": f"Bearer {SAMBANOVA_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "Meta-Llama-3.3-70B-Instruct",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post("https://api.sambanova.ai/v1/chat/completions", headers=headers, json=payload)
    
    if response.status_code == 429:
        raise RateLimitError()
        
    response.raise_for_status()
    return response.json()["choices"][0]["message"]["content"]

def call_tertiary_llm(prompt: str, require_json: bool = True) -> str:
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openrouter/free",
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
    }
    if require_json:
        payload["response_format"] = {"type": "json_object"}

    response = requests.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=payload)
    
    if response.status_code == 429:
        raise RateLimitError()
        
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
                    print("[SENTINEL] Cascading to Secondary (SambaNova)...")
                    return call_secondary_llm(prompt, require_json)
                except Exception as e:
                    print(f"[SENTINEL] Secondary Failed: {e}")
                    try:
                        print("[SENTINEL] Cascading to Tertiary (OpenRouter)...")
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

        CRITICAL FINANCIAL EXTRACTION RULE:
        When parsing the invoice to extract the 'total_amount', you must locate the absolute final liability due after all taxes and adjustments.
        - Identify 'Gross Worth', 'Total Amount Due', or 'Gross Amount' as the primary target for the 'total_amount' key.
        - Do not extract the 'Net Worth', 'Subtotal', or any pre-tax figures into the 'total_amount' field, even if they are positioned directly next to the word 'Total'.
        - If a column labeled 'Gross Worth' or 'Total (Inclusive of Tax)' is present, that specific value takes absolute priority over all other financial figures.

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
        You are a Data Auditor Agent. You are NOT extracting data — you are verifying
        whether an already-extracted JSON is fully and accurately supported by the
        original invoice text.

        Original Text:
        {raw_text}

        Extracted JSON:
        {extracted_data_str}

        SCOPE:
        Only evaluate these 4 fields: vendor_name, invoice_number, total_amount, date.
        Do NOT flag the JSON for missing or extra fields (e.g. client_name, items,VAT, taxes) — those are out of scope and irrelevant to this audit.

        ANTI-HALLUCINATION CHECK:
        -Flag as invalid if any of the 4 fields appears to be invented, guessed, or a
        generic placeholder (e.g. "ABC Corp", "INV-001", "1234.56") that does not literally appear in or derive from the invoice text.
        -A field being null is NOT a defect if it is genuinely absent from the source
        text — do not penalize legitimate nulls.

        FIELD-SPECIFIC RULES:
        - vendor_name / invoice_number: must match the source text (case-insensitive,
            ignoring surrounding whitespace).
        - date: must match the date in the source text, allowing for equivalent
            formats (e.g. "01/02/2024" vs "Feb 1, 2024" if unambiguous), but not a
            different date.
        - total_amount: normalize before comparing — strip commas, currency symbols
            (INR, Rs, $, etc.), and trailing/leading whitespace. Compare the resulting
            numeric value exactly. "1,844,673.60" and "1844673.60" are a match. Do NOT
            allow rounding tolerance — a decimal-placement error (e.g. 1234.56 vs
            123456) is a real error and must be flagged invalid.

        OUTPUT:
        Return ONLY a raw JSON object, with no markdown formatting, no code fences,
        and no explanatory text outside the JSON. It must have exactly two keys:
        "is_valid" (boolean) and "reason" (a short string explaining the decision).
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