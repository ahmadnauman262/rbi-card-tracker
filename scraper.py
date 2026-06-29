import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd
from io import BytesIO
import re

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
            
    # Search for any 4-digit year boundaries
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
    
    try:
        req = requests.get(target_url, headers=headers, timeout=25)
        req.raise_for_status()
    except Exception as error:
        print(f"❌ Error reaching RBI page: {error}")
        return

    soup = BeautifulSoup(req.text, 'html.parser')
    all_links = []
    
    # Locate all XLSX spreadsheets matching card analytics parameters
    for anchor in soup.find_all('a'):
        href = anchor.get('href', '')
        text = anchor.get_text()
        if 'xlsx' in href.lower() and 'atm' in href.lower():
            resolved_url = urljoin(target_url, href)
            # Attempt to extract month name directly from anchor description
            month_name = extract_month_from_text(text) or extract_month_from_text(href)
            all_links.append({
                'url': resolved_url,
                'fallback_name': month_name
            })

    # Deduplicate matching URL paths
    unique_links = []
    seen_urls = set()
    for l in all_links:
        if l['url'] not in seen_urls:
            seen_urls.add(l['url'])
            unique_links.append(l)

    # Grab up to the 8 most recent files
    target_links = unique_links[:8]
    print(f"📚 Identified {len(target_links)} monthly reporting links for baseline ingestion.")

    database = {
        "months": [],
        "history": {}
    }

    for idx, item in enumerate(target_links):
        url = item['url']
        month_name = item['fallback_name'] or f"Archive Period {idx + 1}"
        
        print(f"📥 Processing [{month_name}] from link: {url}")
        
        try:
            file_stream = requests.get(url, headers=headers, timeout=35).content
            df = pd.read_excel(BytesIO(file_stream), header=None)
            
            # Search title block cells inside Excel to locate highly accurate Month-Year markers
            sheet_month = None
            for r_idx in range(min(12, len(df))):
                for c_idx in range(min(6, len(df.columns))):
                    cell_val = str(df.iloc[r_idx, c_idx])
                    if "month of" in cell_val.lower():
                        parts = re.split(r'month of', cell_val, flags=re.IGNORECASE)
                        if len(parts) > 1:
                            raw_month = parts[1].replace('"', '').replace("'", "").strip()
                            # Strip footnotes
                            cleaned_month = re.sub(r'[\d\*_#]+$', '', raw_month).strip()
                            if cleaned_month:
                                sheet_month = cleaned_month
                                break
                if sheet_month:
                    break
            
            if sheet_month:
                month_name = sheet_month

            # Parse and transform matrix row structures
            extracted_records = []
            tracked_sector = "Scheduled Commercial Banks"

            for _, row in df.iterrows():
                if len(row) < 19:
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
                        return float(str(cell).replace(',', '').strip())

                    extracted_records.append({
                        'category': tracked_sector.strip(),
                        'sr_no': int(c1),
                        'bank_name': c2.upper().strip(),
                        'cards_outstanding': format_num(row[9]),
                        'pos_volume': format_num(row[11]),
                        'pos_value': format_num(row[12]),
                        'online_volume': format_num(row[13]),
                        'online_value': format_num(row[14]),
                        'others_volume': format_num(row[15]),
                        'others_value': format_num(row[16]),
                        'atm_volume': format_num(row[17]),
                        'atm_value': format_num(row[18])
                    })

            if extracted_records:
                database["months"].append(month_name)
                database["history"][month_name] = extracted_records
                print(f"   ✅ successfully loaded {len(extracted_records)} banks for {month_name}")
            else:
                print(f"   ⚠️ Parsing completed with zero active records for {month_name}")

        except Exception as error:
            print(f"   ❌ Failed parsing asset details: {error}")

    # Output merged data
    if database["months"]:
        with open('data.json', 'w') as out:
            json.dump(database, out, indent=2)
        print(f"\n🎉 Deployment completed. Generated database containing historical data for {len(database['months'])} periods.")
    else:
        print("❌ Scrape cancelled. No historical worksheets could be resolved.")

if __name__ == "__main__":
    parse_rbi_portal()