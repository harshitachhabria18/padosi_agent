import os
import uuid
import base64
import logging
from bs4 import BeautifulSoup
from datetime import datetime, timedelta
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

# Registry to keep track of active sessions (cookies, viewstate, timestamp)
SESSION_REGISTRY = {}
SESSION_TTL_MINUTES = 5

def cleanup_stale_sessions():
    """Removes sessions older than SESSION_TTL_MINUTES."""
    now = datetime.now()
    stale_keys = [
        key for key, session in SESSION_REGISTRY.items()
        if now - session.get("timestamp", now) > timedelta(minutes=SESSION_TTL_MINUTES)
    ]
    for key in stale_keys:
        logger.info(f"Cleaning up stale IRDAI lookup session: {key}")
        SESSION_REGISTRY.pop(key, None)

class IRDAIScraperService:
    BASE_URL = "https://agencyportal.irdai.gov.in/PublicAccess/LookUpPAN.aspx"

    @staticmethod
    def initiate_lookup(pan_number):
        # curl_cffi is loaded only for this admin-only lookup (~15 MB per process).
        from curl_cffi import requests
        cleanup_stale_sessions()
        session_id = str(uuid.uuid4())
        
        try:
            # 1. Initialize session and get the initial page
            session = requests.Session(impersonate="chrome")
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
            })
            
            response = session.get(IRDAIScraperService.BASE_URL, timeout=15)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 2. Extract ASP.NET state variables
            viewstate = soup.find("input", {"id": "__VIEWSTATE"})
            viewstategenerator = soup.find("input", {"id": "__VIEWSTATEGENERATOR"})
            eventvalidation = soup.find("input", {"id": "__EVENTVALIDATION"})
            
            if not viewstate:
                return {"status": "ERROR", "message": "Failed to load IRDAI portal. Missing VIEWSTATE."}
                
            state_data = {
                "__VIEWSTATE": viewstate.get("value", "") if viewstate else "",
                "__VIEWSTATEGENERATOR": viewstategenerator.get("value", "") if viewstategenerator else "",
                "__EVENTVALIDATION": eventvalidation.get("value", "") if eventvalidation else "",
            }
            
            # 3. Extract CAPTCHA image src
            captcha_img = soup.find("img", {"id": "ctl00_ContentPlaceHolder1_imgcaptcha"})
            if not captcha_img or not captcha_img.get("src"):
                return {"status": "ERROR", "message": "Failed to load CAPTCHA image from IRDAI portal."}
                
            captcha_url = captcha_img.get("src")
            if not captcha_url.startswith("http"):
                captcha_url = urljoin(IRDAIScraperService.BASE_URL, captcha_url)
                
            # 4. Fetch CAPTCHA image
            captcha_response = session.get(captcha_url, timeout=10)
            captcha_response.raise_for_status()
            captcha_base64 = base64.b64encode(captcha_response.content).decode('utf-8')
            
            # 5. Store session state
            SESSION_REGISTRY[session_id] = {
                "cookies": session.cookies.get_dict(),
                "state_data": state_data,
                "timestamp": datetime.now(),
                "pan": pan_number
            }
            
            return {
                "status": "CAPTCHA_REQUIRED",
                "session_id": session_id,
                "captcha_image": f"data:image/png;base64,{captcha_base64}"
            }
            
        except requests.RequestsError as e:
            logger.error(f"HTTP Error in initiate_lookup for PAN {pan_number}: {e}")
            return {"status": "ERROR", "message": "Failed to communicate with IRDAI portal."}
        except Exception as e:
            logger.error(f"Error in initiate_lookup for PAN {pan_number}: {e}", exc_info=True)
            return {"status": "ERROR", "message": "An unexpected error occurred during initiation."}

    @staticmethod
    def resume_lookup(session_id, captcha_solution):
        from curl_cffi import requests
        cleanup_stale_sessions()
        session_data = SESSION_REGISTRY.pop(session_id, None)
        
        if not session_data:
            return {"status": "ERROR", "message": "Session expired or invalid. Please try again."}
            
        try:
            # 1. Restore session
            session = requests.Session(impersonate="chrome")
            session.headers.update({
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.5",
                "Referer": IRDAIScraperService.BASE_URL,
                "Content-Type": "application/x-www-form-urlencoded"
            })
            requests.utils.add_dict_to_cookiejar(session.cookies, session_data["cookies"])
            
            pan_number = session_data["pan"]
            state_data = session_data["state_data"]
            
            # 2. Prepare POST payload
            payload = {
                "__EVENTTARGET": "",
                "__EVENTARGUMENT": "",
                "__VIEWSTATE": state_data.get("__VIEWSTATE", ""),
                "__VIEWSTATEGENERATOR": state_data.get("__VIEWSTATEGENERATOR", ""),
                "__EVENTVALIDATION": state_data.get("__EVENTVALIDATION", ""),
                "ctl00$ContentPlaceHolder1$RadioButtonPanAdhar": "RadioButtonPanAdhar_0", # Assuming PAN is _0
                "ctl00$ContentPlaceHolder1$PAN_Details": pan_number,
                "ctl00$ContentPlaceHolder1$txtcaptcha": captcha_solution,
                "ctl00$ContentPlaceHolder1$btn_lookup": "Submit"
            }
            
            # 3. Submit form
            response = session.post(IRDAIScraperService.BASE_URL, data=payload, timeout=20)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # 4. Check for errors
            error_elems = soup.select("[id*='error'], [id*='Message'], [id*='lbl_err']")
            for elem in error_elems:
                text = elem.get_text(strip=True)
                style = elem.get("style", "").lower()
                if text and "display:none" not in style and "display: none" not in style:
                    return {"status": "ERROR", "message": text}
                    
            # 5. Extract data from tables
            data = {}
            found_data = False
            tables = soup.find_all("table")
            
            for table in tables:
                rows = table.find_all("tr")
                for row in rows:
                    cols = row.find_all(["td", "th"])
                    if len(cols) >= 2:
                        key = cols[0].get_text(strip=True).rstrip(':').strip()
                        val = cols[1].get_text(strip=True)
                        if key and val and "//<![CDATA[" not in key and "//<![CDATA[" not in val and len(key) <= 100:
                            data[key] = val
                            found_data = True
                            
            for table in tables:
                headers_elems = table.find_all("th")
                if headers_elems:
                    headers = [th.get_text(strip=True) for th in headers_elems]
                    rows = table.find_all("tr")
                    for r in rows:
                        tds = r.find_all("td")
                        if len(tds) == len(headers):
                            for h, td in zip(headers, tds):
                                key = h
                                val = td.get_text(strip=True)
                                if key and val and "//<![CDATA[" not in key and "//<![CDATA[" not in val and len(key) <= 100:
                                    data[key] = val
                                    found_data = True
                                    
            if not found_data or len(data) < 2:
                body_text = soup.body.get_text(separator=' ', strip=True).lower() if soup.body else ""
                if "no record" in body_text or "not found" in body_text:
                    return {"status": "ERROR", "message": "No record found for the provided PAN Number."}
                else:
                    return {"status": "ERROR", "message": "Failed to extract data. The IRDAI portal structure may have changed, or CAPTCHA was invalid."}
                    
            mapped_data = IRDAIScraperService.map_fields(data)
            return {
                "status": "SUCCESS",
                "data": mapped_data,
                "raw_data": data
            }
            
        except requests.RequestsError as e:
            logger.error(f"HTTP Error in resume_lookup for session {session_id}: {e}")
            return {"status": "ERROR", "message": "Failed to communicate with IRDAI portal."}
        except Exception as e:
            logger.error(f"Error in resume_lookup for session {session_id}: {e}", exc_info=True)
            return {"status": "ERROR", "message": "Failed to process verification results."}

    @staticmethod
    def map_fields(raw_data):
        """Maps IRDAI portal table labels to local fields."""
        mapped = {}
        
        # Helper dictionary for mapping variations
        mapping_keys = {
            "license_number": ["license number", "licence no", "license no.", "license no", "licence number", "agency code", "agent code", "code"],
            "license_valid_till": ["valid till", "expiry date", "validity", "valid up to", "license valid till", "date of appointment", "status change date"],
            "agent_name": ["agent name", "name", "candidate name", "fullname"],
            "agency_name": ["agency name", "company name", "insurer name", "company", "insurer"],
            "agency_code": ["agency code", "code", "agent code"],
            "license_status": ["status of agency", "status change date", "status"],
            "designation": ["designation"],
            "category": ["category"],
            "address": ["address", "current address", "communication address"],
            "state": ["state"],
            "city": ["city", "district"],
            "pincode": ["pincode", "pin code", "pin"],
            "email": ["email", "e-mail", "email id"],
            "mobile": ["mobile", "phone", "contact", "mobile number"]
        }
        
        # Case insensitive mapping
        for local_field, irda_fields in mapping_keys.items():
            for key, val in raw_data.items():
                if any(f in key.lower() for f in irda_fields):
                    # Clean/normalize value
                    cleaned_val = val.strip()
                    # Try to parse valid dates if it's a date field
                    if local_field == "license_valid_till":
                        # Standardize format for date inputs (YYYY-MM-DD)
                        for fmt in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d %b %Y", "%d %B %Y"):
                            try:
                                dt = datetime.strptime(cleaned_val, fmt)
                                cleaned_val = dt.strftime("%Y-%m-%d")
                                break
                            except ValueError:
                                continue
                    mapped[local_field] = cleaned_val
                    break
                    
        return mapped
