import requests
from bs4 import BeautifulSoup
import pandas as pd
import os
import subprocess
import sys

url = 'https://agencyportal.irdai.gov.in/PublicAccess/BlackListedAgent.aspx'

print('Step 1 — Fetching page to get session tokens...')
session = requests.Session()
session.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
})

response = session.get(url)
print(f'Page status: {response.status_code}')

soup = BeautifulSoup(response.text, 'html.parser')

viewstate = soup.find('input', {'name': '__VIEWSTATE'})['value']
viewstategenerator = soup.find('input', {'name': '__VIEWSTATEGENERATOR'})['value']
eventvalidation = soup.find('input', {'name': '__EVENTVALIDATION'})['value']

print('Step 2 — Tokens extracted successfully')

payload = {
    '__EVENTTARGET': '',
    '__EVENTARGUMENT': '',
    '__VIEWSTATE': viewstate,
    '__VIEWSTATEGENERATOR': viewstategenerator,
    '__EVENTVALIDATION': eventvalidation,
    '__SCROLLPOSITIONX': '0',
    '__SCROLLPOSITIONY': '0',
    'ctl00$ContentPlaceHolder1$txtStartDate': '13 Jul 2026',
    'ctl00$ContentPlaceHolder1$btnExport': 'Export',
}

print('Step 3 — Sending export request...')
export_response = session.post(url, data=payload)
print(f'Export status: {export_response.status_code}')
print(f'Content type: {export_response.headers.get("Content-Type")}')
print(f'Content length: {len(export_response.content)} bytes')

print('Step 4 — Parsing HTML response into real Excel...')
from io import StringIO
html_content = export_response.text
tables = pd.read_html(StringIO(html_content), header=0)
df = tables[1]
print(f'Rows parsed: {len(df)}')

os.makedirs('data', exist_ok=True)
save_path = 'data/blacklisted_agents.xlsx'
df.to_excel(save_path, index=False)
print(f'Step 5 — Real xlsx saved to {save_path}')

print('Step 6 — Running import command...')
result = subprocess.run(
    [sys.executable, 'manage.py', 'import_blacklisted_agents',
     '--file=data/blacklisted_agents.xlsx', '--source=auto'],
    capture_output=True,
    text=True
)
print(result.stdout)
if result.stderr:
    print('Errors:', result.stderr)

print('All done!')
