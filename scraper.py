import os
import json
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import pandas as pd

def parse_rbi_portal():
    print("🚀 Running automated web scraping protocol targeting RBI database links...")
    target_url = "https://rbi.org.in/scripts/atmview.aspx"
    
    # Desktop spoof header definitions to bypass security controls
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        req = requests.get(target_url, headers=headers, timeout=25)
        req.raise_for_status()
    except Exception as error:
        print(f"❌ Aborting. Target server unreachable: {error}")
        return

    soup = BeautifulSoup(req.text, 'html.parser')
    xlsx_link = None
    
    # Query document anchor links out of structural elements
    for anchor in soup.find_all('a'):
        href = anchor.get('href', '')
        if 'xlsx' in href.lower() and 'atm' in href.lower():
            xlsx_link = urljoin(target_url, href)
            break
            
    if not xlsx_link:
        print("❌ Analytical Error: The RBI target sheet reference cannot be extracted from HTML components.")
        return

    print(f"🔗 Match found! Streaming download from target URL: {xlsx_link}")
    
    try:
        file_stream = requests.get(xlsx_link, headers=headers, timeout=35).content
        temp_destination = "scratch_rbi.xlsx"
        with open(temp_destination, "wb") as file:
            file.write(file_stream)
    except Exception as error:
        print(f"❌ Transmission error: {error}")
        return

    # Ingest matrix arrays via Pandas
    try:
        df = pd.read_excel(temp_destination, header=None)
        extracted_records = []
        tracked_sector = "Scheduled Commercial Banks"

        for idx, row in df.iterrows():
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
                    'sector': tracked_sector.strip(),
                    'sr_no': int(c1),
                    'bank_name': c2.upper().strip(),
                    'cc_outstanding': format_num(row[9]),
                    'pos_vol': format_num(row[11]),
                    'pos_val': format_num(row[12]),
                    'online_vol': format_num(row[13]),
                    'online_val': format_num(row[14]),
                    'others_vol': format_num(row[15]),
                    'others_val': format_num(row[16]),
                    'atm_vol': format_num(row[17]),
                    'atm_val': format_num(row[18])
                })

        with open('data.json', 'w') as out:
            json.dump(extracted_records, out, indent=2)
            
        print(f"📊 Extraction engine complete! Processed parameters for {len(extracted_records)} banks inside data.json.")
        
    except Exception as error:
        print(f"❌ Internal processing error: {error}")
    finally:
        if os.path.exists(temp_destination):
            os.remove(temp_destination)

if __name__ == "__main__":
    parse_rbi_portal()