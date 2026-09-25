/**
 * =========================================================================
 * PADOSI AGENT — GOOGLE APPS SCRIPT FOR INVOICE & GOOGLE DRIVE SYNC
 * =========================================================================
 * 
 * 16 Exact Headers:
 * [Invoice #, Date, Agent, Email, Mobile, Plan Name, Place of Supply, Base Amount, CGST, SGST, IGST, Total Amount, Payment ID, Promo Code, Discount Folder, PDF Link]
 *
 * HOW TO SETUP:
 * 1. Open your Google Sheet.
 * 2. Click "Extensions" > "Apps Script".
 * 3. Replace all existing code with this file.
 * 4. Paste your Google Drive Folder ID into FOLDER_ID below.
 *    (From Drive URL: https://drive.google.com/drive/folders/<FOLDER_ID>)
 * 5. Click "Deploy" > "New deployment".
 * 6. Select type: "Web app".
 * 7. Set Description: "Invoice Google Drive & Sheet Sync".
 * 8. Set Execute as: "Me" (your Google account).
 * 9. Set Who has access: "Anyone" (CRITICAL: Must be Anyone so backend can POST).
 * 10. Click "Deploy", copy the Web App URL, and paste it into:
 *     Admin Panel > Invoices > Google Sheet Sync URL > Save URL.
 */

// REPLACE WITH YOUR GOOGLE DRIVE FOLDER ID (Optional - defaults to "PadosiAgent Invoices"):
var FOLDER_ID = "YOUR_GOOGLE_DRIVE_FOLDER_ID";

/**
 * Handles GET requests (when the link is clicked or opened in a browser).
 * Automatically redirects the user to the active Google Sheet spreadsheet!
 */
function doGet(e) {
  try {
    var ss = SpreadsheetApp.getActiveSpreadsheet();
    var sheetUrl = ss.getUrl();
    return HtmlService.createHtmlOutput(
      '<!DOCTYPE html><html><head>' +
      '<meta http-equiv="refresh" content="0;url=' + sheetUrl + '">' +
      '<script>window.location.replace("' + sheetUrl + '");</script>' +
      '</head>' +
      '<body style="font-family:system-ui,sans-serif;text-align:center;padding:50px;background:#f8fafc;color:#1e293b;">' +
      '<div style="background:#ffffff;padding:30px;border-radius:12px;display:inline-block;box-shadow:0 4px 12px rgba(0,0,0,0.08);">' +
      '<h2 style="color:#18529d;margin-top:0;">Opening Google Sheet...</h2>' +
      '<p style="color:#64748b;">If you are not redirected automatically, click below:</p>' +
      '<a href="' + sheetUrl + '" style="display:inline-block;padding:10px 20px;background:#18529d;color:#ffffff;text-decoration:none;border-radius:6px;font-weight:bold;">Open Google Sheet &rarr;</a>' +
      '</div></body></html>'
    ).setTitle("PadosiAgent Invoice Sheet").setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
  } catch (err) {
    return ContentService.createTextOutput("PadosiAgent Invoice Web App is Active. (Ready to receive invoice sync via POST)").setMimeType(ContentService.MimeType.TEXT);
  }
}

function doPost(e) {
  var lock = LockService.getScriptLock();
  // Wait up to 30 seconds for concurrent invocations
  try {
    lock.waitLock(30000);
  } catch (lockErr) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: "Server busy, could not acquire script lock"
    })).setMimeType(ContentService.MimeType.JSON);
  }

  try {
    if (!e || !e.postData || !e.postData.contents) {
      return ContentService.createTextOutput(JSON.stringify({
        status: "error",
        message: "No POST body received"
      })).setMimeType(ContentService.MimeType.JSON);
    }

    var data = JSON.parse(e.postData.contents);
    var ss = SpreadsheetApp.getActiveSpreadsheet();

    // Reliably target "Invoices" tab or the first sheet tab (never random tab)
    var sheet = ss.getSheetByName("Invoices") || ss.getSheetByName("Sheet1") || ss.getSheets()[0];

    // 1. Auto-create 16 headers if sheet is empty
    if (sheet.getLastRow() === 0) {
      var headers = [
        "Invoice #",
        "Date",
        "Agent",
        "Email",
        "Mobile",
        "Plan Name",
        "Place of Supply",
        "Base Amount",
        "CGST",
        "SGST",
        "IGST",
        "Total Amount",
        "Payment ID",
        "Promo Code",
        "Discount Folder",
        "PDF Link"
      ];
      sheet.appendRow(headers);
      var headerRange = sheet.getRange(1, 1, 1, headers.length);
      headerRange.setFontWeight("bold");
      headerRange.setBackground("#18529d");
      headerRange.setFontColor("#ffffff");
      headerRange.setHorizontalAlignment("center");
      sheet.setFrozenRows(1);

      // Set text format for Date (col 2) and Mobile (col 5)
      var maxRows = Math.max(sheet.getMaxRows() - 1, 10);
      sheet.getRange(2, 2, maxRows, 1).setNumberFormat("@");
      sheet.getRange(2, 5, maxRows, 1).setNumberFormat("@");
      // Set currency/decimal format for Amount columns 8..12
      sheet.getRange(2, 8, maxRows, 5).setNumberFormat("#,##0.00");
    }

    // 2. Upload PDF to Google Drive if base64 provided
    var pdfDriveUrl = "";
    if (data.pdf_base64 && data.pdf_base64.length > 50) {
      try {
        var rootFolder;
        if (FOLDER_ID && FOLDER_ID !== "YOUR_GOOGLE_DRIVE_FOLDER_ID" && FOLDER_ID.trim().length > 5) {
          rootFolder = DriveApp.getFolderById(FOLDER_ID.trim());
        } else {
          // If no custom folder ID, use/create dedicated "PadosiAgent Invoices" folder
          var defaultFolders = DriveApp.getFoldersByName("PadosiAgent Invoices");
          rootFolder = defaultFolders.hasNext() ? defaultFolders.next() : DriveApp.createFolder("PadosiAgent Invoices");
        }

        // Subfolder based on discount folder (e.g. "No Discount", "10%", "₹1 (Special)")
        var subFolderName = (data.discount_folder || data['Discount Folder'] || "Invoices").toString().trim();
        var subFolders = rootFolder.getFoldersByName(subFolderName);
        var targetFolder = subFolders.hasNext() ? subFolders.next() : rootFolder.createFolder(subFolderName);

        var bytes = Utilities.base64Decode(data.pdf_base64);
        var invNum = (data.invoice_number || data['Invoice #'] || "Invoice").toString().replace(/[\/\\:*?"<>|]/g, "_");
        var fileName = invNum + ".pdf";
        var blob = Utilities.newBlob(bytes, "application/pdf", fileName);

        // Remove old file versions safely to prevent binary PDF corruption with setContent
        var existingFiles = targetFolder.getFilesByName(fileName);
        while (existingFiles.hasNext()) {
          var oldFile = existingFiles.next();
          try {
            oldFile.setTrashed(true);
          } catch (trashErr) {
            // Ignore if trash not permitted
          }
        }

        var file = targetFolder.createFile(blob);
        // Set sharing permissions so link can be viewed by anyone with link
        file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW);
        pdfDriveUrl = file.getUrl();
      } catch (driveErr) {
        pdfDriveUrl = data.pdf_url || ("Drive Error: " + driveErr.toString());
      }
    } else {
      pdfDriveUrl = data.pdf_url || "";
    }

    // 3. Extract and parse data matching exact 16-column header
    var invoiceNumber = data.invoice_number || data['Invoice #'] || "";
    var date = data.date || data['Date'] || "";
    var agentName = data.agent_name || data['Agent'] || "";
    var agentEmail = data.agent_email || data['Email'] || "";
    var agentMobile = data.agent_mobile || data['Mobile'] || "";
    var planName = data.plan_name || data['Plan Name'] || "";
    var placeOfSupply = data.place_of_supply || data['Place of Supply'] || "Gujarat";
    var baseAmount = data.base_amount != null ? Number(data.base_amount) : (data['Base Amount'] != null ? Number(data['Base Amount']) : 0);
    var cgst = data.cgst != null ? Number(data.cgst) : (data['CGST'] != null ? Number(data['CGST']) : 0);
    var sgst = data.sgst != null ? Number(data.sgst) : (data['SGST'] != null ? Number(data['SGST']) : 0);
    var igst = data.igst != null ? Number(data.igst) : (data['IGST'] != null ? Number(data['IGST']) : 0);
    var totalAmount = data.total_amount != null ? Number(data.total_amount) : (data['Total Amount'] != null ? Number(data['Total Amount']) : 0);
    var paymentId = data.payment_id || data['Payment ID'] || "";
    var promoCode = data.promo_code || data['Promo Code'] || "";
    var discountFolder = data.discount_folder || data['Discount Folder'] || "";

    // Sanitize mobile to prevent formula errors or scientific notation
    var mobileStr = agentMobile ? agentMobile.toString().trim() : "";
    if (mobileStr && !mobileStr.startsWith("'")) {
      mobileStr = "'" + mobileStr;
    }

    // 4. Exact 16-column row:
    // Invoice # | Date | Agent | Email | Mobile | Plan Name | Place of Supply | Base Amount | CGST | SGST | IGST | Total Amount | Payment ID | Promo Code | Discount Folder | PDF Link
    var rowData = [
      invoiceNumber,
      date,
      agentName,
      agentEmail,
      mobileStr,
      planName,
      placeOfSupply,
      baseAmount,
      cgst,
      sgst,
      igst,
      totalAmount,
      paymentId,
      promoCode,
      discountFolder,
      pdfDriveUrl
    ];

    // 5. Prevent duplicate rows: Check if invoice already exists in Column 1
    var existingRow = -1;
    var lastRow = sheet.getLastRow();
    if (lastRow > 1 && invoiceNumber) {
      var colValues = sheet.getRange(2, 1, lastRow - 1, 1).getValues();
      var targetNum = invoiceNumber.toString().trim().toLowerCase();
      for (var i = 0; i < colValues.length; i++) {
        if (colValues[i][0] && colValues[i][0].toString().trim().toLowerCase() === targetNum) {
          existingRow = i + 2; // header is row 1
          break;
        }
      }
    }

    if (existingRow > 0) {
      sheet.getRange(existingRow, 1, 1, rowData.length).setValues([rowData]);
    } else {
      sheet.appendRow(rowData);
    }

    return ContentService.createTextOutput(JSON.stringify({
      status: "success",
      action: existingRow > 0 ? "updated" : "appended",
      invoice_number: invoiceNumber,
      drive_url: pdfDriveUrl
    })).setMimeType(ContentService.MimeType.JSON);

  } catch (err) {
    return ContentService.createTextOutput(JSON.stringify({
      status: "error",
      message: err.toString()
    })).setMimeType(ContentService.MimeType.JSON);
  } finally {
    lock.releaseLock();
  }
}
