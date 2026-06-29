import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from io import BytesIO
import re
from datetime import datetime

def extract_month_from_text(text):
    """
    Parses natural language strings to extract a clean Month Year identifier.
    E.g. "ATM Statistics for May 2026" -> "May 2026"
    """
    months = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december"]
    text_lower = text.lower()
    found_month = None
    found_year = None
    
    for m in months:
        if m in text_lower:
            found_month = m.capitalize()
            break
            
    year_match = re.search(r'\b(20\d{2})\b', text)
    if year_match:
        found_year = year_match.group(1)
        
    if found_month and found_year:
        return f"{found_month} {found_year}"
    return None

def parse_rbi_portal():
    print("🚀 Initiating RBI Multi-Month Historical Pipeline Scraper...")
    target_url = "https://rbi.org.in/scripts/atmview.aspx"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    session = requests.Session()
    
    try:
        req = session.get(target_url, headers=headers, timeout=25)
        req.raise_for_status()
    except Exception as error:
        print(f"❌ Error reaching RBI page: {error}")
        return

    soup = BeautifulSoup(req.text, 'html.parser')
    all_links = []

    def extract_links_from_soup(current_soup):
        for anchor in current_soup.find_all('a'):
            href = anchor.get('href', '')
            text = anchor.get_text()
            href_lower = href.lower()
            text_lower = text.lower()
            
            # Accepts both modern .xlsx and legacy .xls formats
            is_excel = '.xls' in href_lower or '.xlsx' in href_lower
            is_atm = 'atm' in href_lower or 'atm' in text_lower or 'card' in text_lower
            
            if is_excel and is_atm:
                resolved_url = urljoin(target_url, href)
                month_name = extract_month_from_text(text) or extract_month_from_text(href)
                all_links.append({
                    'url': resolved_url,
                    'fallback_name': month_name
                })

    # Grab the current year links (e.g. 2026)
    extract_links_from_soup(soup)

    try:
        # Find ASP.NET state verification inputs
        viewstate = soup.find(id='__VIEWSTATE')['value'] if soup.find(id='__VIEWSTATE') else ''
        viewstate_gen = soup.find(id='__VIEWSTATEGENERATOR')['value'] if soup.find(id='__VIEWSTATEGENERATOR') else ''
        event_val = soup.find(id='__EVENTVALIDATION')['value'] if soup.find(id='__EVENTVALIDATION') else ''
        
        # Discover ASP.NET select tag name dynamically
        select_tag = soup.find('select', id=lambda x: x and 'yr' in x.lower())
        select_name = select_tag['name'] if select_tag else 'ddlYr'
        
        current_year = datetime.now().year
        previous_year = current_year - 1
        
        print(f"🔄 Interrogating ASP.NET state parameters to trigger dropdown switch to: {previous_year}")
        
        # Postback payload payload
        payload = {
            '__VIEWSTATE': viewstate,
            '__VIEWSTATEGENERATOR': viewstate_gen,
            '__EVENTVALIDATION': event_val,
            '__EVENTTARGET': select_name,
            select_name: str(previous_year)
        }
        
        post_headers = headers.copy()
        post_headers['Referer'] = target_url
        
        post_response = session.post(target_url, data=payload, headers=post_headers, timeout=25)
        if post_response.status_code == 200:
            post_soup = BeautifulSoup(post_response.text, 'html.parser')
            # Extract links from the newly posted previous year page
            extract_links_from_soup(post_soup)
            print(f"✅ Successfully extracted additional historical elements from {previous_year} layout.")
    except Exception as post_error:
        print(f"⚠️ Form Postback bypassed or failed: {post_error}. Processing what is visible.")

    unique_links = []
    seen_urls = set()
    for l in all_links:
        if l['url'] not in seen_urls:
            seen_urls.add(l['url'])
            unique_links.append(l)

    # Slice strictly to the latest 8 months
    target_links = unique_links[:8]
    print(f"📚 Identified {len(target_links)} total months of data for parsing.")

    database = {
        "months": [],
        "history": {}
    }

    for idx, item in enumerate(target_links):
        url = item['url']
        month_name = item['fallback_name'] or f"Archive Period {idx + 1}"
        
        print(f"📥 Downloading & Parsing [{month_name}] from link: {url}")
        
        try:
            file_stream = requests.get(url, headers=headers, timeout=35).content
            
            # Read excel sheet (will load openpyxl for .xlsx and xlrd for .xls files automatically)
            df = pd.read_excel(BytesIO(file_stream), header=None)
            
            sheet_month = None
            for r_idx in range(min(12, len(df))):
                for c_idx in range(min(6, len(df.columns))):
                    cell_val = str(df.iloc[r_idx, c_idx])
                    if "month of" in cell_val.lower():
                        parts = re.split(r'month of', cell_val, flags=re.IGNORECASE)
                        if len(parts) > 1:
                            raw_month = parts[1].replace('"', '').replace("'", "").strip()
                            # FIXED REGEX: Preserve digit sequences (the year) but strip trailing symbols/asterisks
                            cleaned_month = re.sub(r'[\*_\s#]+$', '', raw_month).strip()
                            if cleaned_month:
                                sheet_month = cleaned_month
                                break
                if sheet_month:
                    break
            
            if sheet_month:
                month_name = sheet_month

            extracted_records = []
            tracked_sector = "Scheduled Commercial Banks"

            for _, row in df.iterrows():
                if len(row) < 13: # Safe margin checks
                    continue
                
                c1 = str(row[1]).strip() if pd.notna(row[1]) else ""
                c2 = str(row[2]).strip() if pd.notna(row[2]) else ""
                
                if c1 == "" or c1.lower() == "nan":
                    continue
                    
                if c2 == "" or c2.lower() == "nan":
                    if "bank" in c1.lower() or "sector" in c1.lower() or "scheduled" in c1.lower():
                        tracked_sector = c1
                    continue

                if c1.isdigit():
                    def format_num(cell):
                        if pd.isna(cell) or str(cell).strip() == "" or str(cell).strip().lower() == "nan":
                            return 0.0
                        try:
                            return float(str(cell).replace(',', '').strip())
                        except ValueError:
                            return 0.0

                    def get_val(col_idx):
                        if col_idx < len(row):
                            return format_num(row[col_idx])
                        return 0.0

                    extracted_records.append({
                        'category': tracked_sector.strip(),
                        'sr_no': int(c1),
                        'bank_name': c2.upper().strip(),
                        'cards_outstanding': get_val(9),
                        'pos_volume': get_val(11),
                        'pos_value': get_val(12),
                        'online_volume': get_val(13),
                        'online_value': get_val(14),
                        'others_volume': get_val(15),
                        'others_value': get_val(16),
                        'atm_volume': get_val(17),
                        'atm_value': get_val(18)
                    })

            if extracted_records:
                database["months"].append(month_name)
                database["history"][month_name] = extracted_records
                print(f"   ✅ Successfully loaded {len(extracted_records)} banks for {month_name}")
            else:
                print(f"   ⚠️ Warning: Parsed zero banks for {month_name}")

        except Exception as error:
            print(f"   ❌ Failed to process Excel: {error}")

    if database["months"]:
        with open('data.json', 'w') as out:
            json.dump(database, out, indent=2)
        print(f"\n🎉 Ingestion Pipeline Success! Generated structured data.json containing {len(database['months'])} periods.")
    else:
        print("❌ Scraper failure: No periods could be extracted.")

if __name__ == "__main__":
    parse_rbi_portal()