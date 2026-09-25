# PadosiAgent Google Sheets & Google Drive Invoice Sync

This integration automatically synchronizes invoice records to Google Sheets and uploads invoice PDFs directly to Google Drive upon Razorpay payment completion or manual sync.

---

## 16 Columns Layout

| Column # | Header Name | Data Source |
|---|---|---|
| 1 | **Invoice #** | `invoice_number` (e.g. `PA/26-27/00042`) |
| 2 | **Date** | `date` (formatted `DD/MM/YYYY HH:mm`) |
| 3 | **Agent** | `agent_name` (e.g. `Ashish Patel`) |
| 4 | **Email** | `agent_email` |
| 5 | **Mobile** | `agent_mobile` |
| 6 | **Plan Name** | `plan_name` (e.g. `Professional Plan`) |
| 7 | **Place of Supply** | State name (e.g. `Gujarat`, `Maharashtra`) |
| 8 | **Base Amount** | Base amount before tax |
| 9 | **CGST** | 9% for Gujarat, 0.00 for other states |
| 10 | **SGST** | 9% for Gujarat, 0.00 for other states |
| 11 | **IGST** | 0.00 for Gujarat, 18% for other states |
| 12 | **Total Amount** | Total amount paid (including GST) |
| 13 | **Payment ID** | Razorpay payment ID (e.g. `pay_...`) |
| 14 | **Promo Code** | Promo code applied or empty |
| 15 | **Discount Folder** | Folder classification (e.g. `No Discount`, `10%`, `₹1 (Special)`) |
| 16 | **PDF Link** | Google Drive shareable link to the uploaded PDF |

---

## Deployment Steps

### Step 1: Create Google Drive Folder
1. Go to [Google Drive](https://drive.google.com).
2. Create a new folder (e.g. `PadosiAgent Invoices`).
3. Open the folder and copy the folder ID from the address bar:
   `https://drive.google.com/drive/folders/`**`1a2b3c4d5e...`**

### Step 2: Open Google Sheet & Apps Script
1. Open or create your Google Sheet for Invoices.
2. In the menu, click **Extensions** > **Apps Script**.
3. Clear any code in `Code.gs` and paste the contents of `google_apps_script/Code.gs`.
4. At line 26 of `Code.gs`, replace `YOUR_GOOGLE_DRIVE_FOLDER_ID` with your folder ID:
   ```javascript
   var FOLDER_ID = "1a2b3c4d5e...";
   ```
5. Click **Save** (💾 icon).

### Step 3: Deploy as Web App
1. Click **Deploy** > **New deployment**.
2. Click the gear icon (⚙️) next to "Select type" and select **Web app**.
3. Fill in:
   - **Description**: `Invoice Sync Web App`
   - **Execute as**: `Me` (your Google account)
   - **Who has access**: **`Anyone`** (⚠️ Important: Do NOT select "Only myself", it must be "Anyone").
4. Click **Deploy**.
5. If prompted, authorize Google permissions (Click "Advanced" > "Go to ... (unsafe)" > "Allow").
6. Copy the **Web App URL** (e.g. `https://script.google.com/macros/s/.../exec`).

### Step 4: Configure in Admin Panel
1. Open PadosiAgent Admin Panel at `/admin/invoices/`.
2. Under **Google Sheet Sync** on the left sidebar:
   - Paste the Web App URL into the input field.
   - Click **Save URL**.
3. Now all new paid invoices will automatically:
   - Generate PDF
   - Upload PDF to Google Drive
   - Insert row with Google Drive PDF link into Google Sheet
   - Calculate CGST, SGST, IGST and Place of Supply automatically.
