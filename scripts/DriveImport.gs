// plugin/ingest/DriveImport.gs — Drive folder search + BOL field extraction + sheet import
//
// Extends the original file-name/link sync so each BOL document is opened,
// OCR'd (Advanced Drive API), and its fields parsed into individual columns.
//
// SETUP (one-time, in the Apps Script editor):
//   1. Enable the Advanced "Drive API" (v2) service:
//      Editor → Services (+) → Drive API → Add.
//   2. First run will prompt for Drive + Sheets authorization — accept.
//
// If a field regex doesn't match YOUR BOL layout, run `debugDumpText(folderId)`
// once — it prints the raw OCR text of the first file to the Logs so you can
// see the real labels and tune FIELDS below.

var CONFIG = {
  OCR_LANGUAGE: 'en',        // ISO language code for OCR
  SLEEP_MS: 300,             // throttle between OCR calls (Drive quota)
  INCLUDE_RAW_TEXT: false,   // add a 'Raw Text' column (huge — off by default)
  MAX_FILES_PER_RUN: 0,      // 0 = unlimited; set e.g. 40 to stay under the 6-min limit
};

// ---------------------------------------------------------------------------
// FIELD DEFINITIONS — the columns and how to find each value in the OCR text.
//
//   key     : internal id
//   column  : header label in the sheet
//   labels  : synonyms to look for; value is captured after the first hit
//   multiLine: if true, capture up to `maxLines` lines BELOW the label
//   maxLines : for multiLine blocks
//   numeric : if true, pull just the leading number (drops units)
//
// Add / remove entries to change the columns. Order = sheet column order.
// ---------------------------------------------------------------------------
var FIELDS = [
  { key: 'bol',          column: 'BOL #',           labels: ['Bill of Lading No', 'Bill of Lading Number', 'Bill of Lading #', 'BOL No', 'BOL Number', 'BOL #', 'B/L No', 'B/L #'], numeric: false },
  { key: 'pro',          column: 'PRO #',           labels: ['PRO Number', 'PRO No', 'PRO #', 'Pro #', 'PRO', 'Reference Number', 'Reference #', 'Tracking Pro', 'Tracking Number', 'Tracking #'], numeric: false },
  { key: 'po',           column: 'PO #',            labels: ['Purchase Order #', 'Purchase Order', 'PO Number', 'PO No', 'PO #', 'Customer PO', 'Customer Order #', 'Order #', 'Shipment Reference'], numeric: false },
  { key: 'ship_date',    column: 'Ship Date',       labels: ['Date Shipped', 'Ship Date', 'Shipping Date', 'Pickup Date', 'Shipment Date', 'Pro Date', 'Date'], numeric: false },
  { key: 'shipper',      column: 'Shipper',         labels: ['Shipper', 'Consignor', 'Bill From'], multiLine: true, maxLines: 1 },
  { key: 'shipper_addr', column: 'Shipper Address', labels: ['Shipper', 'Consignor', 'Bill From'], multiLine: true, maxLines: 4 },
  { key: 'consignee',    column: 'Consignee',       labels: ['Consignee', 'Ship To', 'Bill To', 'Ultimate Consignee'], multiLine: true, maxLines: 1 },
  { key: 'consignee_addr', column: 'Consignee Address', labels: ['Consignee', 'Ship To', 'Bill To', 'Ultimate Consignee'], multiLine: true, maxLines: 4 },
  { key: 'carrier',      column: 'Carrier',         labels: ['Carrier Name', 'Freight Carrier', 'Transportation Company', 'Carrier'], numeric: false },
  { key: 'scac',         column: 'SCAC',            labels: ['SCAC Code', 'SCAC'], numeric: false },
  { key: 'pieces',       column: 'Pieces',          labels: ['Handling Units', 'No of Pieces', '# of Pieces', 'Number of Pieces', 'Pieces', 'Packages', 'Pcs', 'Units', 'Qty', 'Quantity'], numeric: true },
  { key: 'weight',       column: 'Weight (lbs)',    labels: ['Total Weight', 'Net Weight', 'Gross Weight', 'Weight (lbs)', 'Weight lbs', 'Weight'], numeric: true },
  { key: 'freight_class', column: 'Freight Class',  labels: ['Freight Class', 'NMFC Class', 'Frt Class', 'Class'], numeric: false },
  { key: 'nmfc',         column: 'NMFC #',          labels: ['NMFC Item', 'NMFC #', 'NMFC Number', 'NMFC', 'Commodity Code'], numeric: false },
  { key: 'description',  column: 'Description',     labels: ['Description of Articles', 'Description of Goods', 'Description', 'Commodity', 'Contents'], numeric: false },
  { key: 'seal',         column: 'Seal #',          labels: ['Seal Number', 'Seal #', 'Seal'], numeric: false },
  { key: 'trailer',      column: 'Trailer #',       labels: ['Trailer Number', 'Trailer #', 'Trailer'], numeric: false },
  { key: 'origin_city',  column: 'Origin City',     labels: ['Origin City', 'Pickup City', 'Origin'], numeric: false },
  { key: 'dest_city',    column: 'Destination City', labels: ['Destination City', 'Dest City', 'Consignee City', 'Delivery City'], numeric: false },
];

// Keep the original two helpers intact so existing menu/trigger wiring still works.
function getActiveSheetHeaders() {
  try {
    var sheet = SpreadsheetApp.getActiveSpreadsheet().getActiveSheet();
    var lastCol = sheet.getLastColumn();
    if (lastCol === 0) return [];
    return sheet.getRange(1, 1, 1, lastCol).getValues()[0].map(function (h) {
      return h.toString().trim();
    });
  } catch (e) {
    return [];
  }
}

function searchDriveFolders(query, isUrl) {
  var results = [];
  try {
    if (isUrl) {
      var match = query.match(/folders\/([a-zA-Z0-9-_]+)/);
      var id = match ? match[1] : query;
      var f = DriveApp.getFolderById(id);
      results.push({ name: f.getName(), id: f.getId(), url: f.getUrl() });
    } else {
      var sq = "title contains '" + query.replace(/'/g, "\\'") + "' and trashed = false";
      var folders = DriveApp.searchFolders(sq);
      while (folders.hasNext()) {
        var fd = folders.next();
        results.push({ name: fd.getName(), id: fd.getId(), url: fd.getUrl() });
        if (results.length >= 20) break;
      }
    }
  } catch (e) {
    Logger.log(e);
  }
  return results;
}

// ---------------------------------------------------------------------------
// Text extraction: read Google Docs / text directly, OCR everything else (PDF,
// images) into a temp Google Doc via the Advanced Drive API, then delete it.
// ---------------------------------------------------------------------------
function getFileText(file) {
  var mime = file.getMimeType();
  try {
    if (mime === MimeType.GOOGLE_DOCS) {
      return DocumentApp.openById(file.getId()).getBody().getText();
    }
    if (mime === MimeType.PLAIN_TEXT || mime === MimeType.CSV) {
      return file.getBlob().getDataAsString();
    }
    // PDF / image / anything else → OCR
    var blob = file.getBlob();
    var resource = { title: file.getName() + '_ocr_tmp', mimeType: MimeType.GOOGLE_DOCS };
    var docFile = Drive.Files.insert(resource, blob, { ocr: true, ocrLanguage: CONFIG.OCR_LANGUAGE });
    var text = DocumentApp.openById(docFile.id).getBody().getText();
    Drive.Files.remove(docFile.id); // clean up the temp doc
    return text;
  } catch (e) {
    Logger.log('Text extraction failed for ' + file.getName() + ': ' + e);
    return '';
  }
}

// ---------------------------------------------------------------------------
// Parsing
// ---------------------------------------------------------------------------
function escapeRegExp(s) { return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'); }

function cleanValue(v) {
  return v.replace(/\s+/g, ' ').replace(/^[:\s.#\-]+/, '').replace(/[:\s.#\-]+$/, '').trim();
}

// Capture the first value following any of `labels`. Two passes:
//   1. same line  : "LABEL: value"
//   2. next line  : label on its own line, value below (form layouts)
function matchLabeled(text, field) {
  var labels = field.labels || [];
  for (var i = 0; i < labels.length; i++) {
    var lab = escapeRegExp(labels[i]);
    // same-line capture; (^|\n or a space) before label, non-alphanumeric after
    var re = new RegExp('(^|[\\n ])' + lab + '(?=[^A-Za-z0-9]|$)[\\s:.#\\-]*([^\\n]{1,120})', 'i');
    var m = text.match(re);
    if (m && m[1]) {
      var v = cleanValue(m[2]);
      if (v) return field.numeric ? extractNumber(v) : v;
    }
    // next-line capture (value on the following line)
    var re2 = new RegExp('(^|\\n)\\s*' + lab + '[\\s:.#\\-]*\\n\\s*([^\\n]{1,120})', 'i');
    var m2 = text.match(re2);
    if (m2 && m2[2]) {
      var v2 = cleanValue(m2[2]);
      if (v2) return field.numeric ? extractNumber(v2) : v2;
    }
  }
  return '';
}

// Capture up to `maxLines` non-empty lines immediately BELOW a label line.
function matchBlock(lines, field) {
  var labels = field.labels || [];
  var maxLines = field.maxLines || 3;
  for (var i = 0; i < lines.length; i++) {
    var ln = lines[i].toUpperCase().trim();
    for (var j = 0; j < labels.length; j++) {
      if (ln === labels[j].toUpperCase()) {
        var block = [];
        for (var k = i + 1; k < lines.length && block.length < maxLines; k++) {
          var nl = lines[k].trim();
          if (nl) block.push(nl);
        }
        return block.join(' | ');
      }
    }
  }
  return '';
}

function extractNumber(v) {
  var m = v.match(/-?\d[\d,]*(?:\.\d+)?/);
  return m ? m[0].replace(/,/g, '') : v;
}

// Normalize OCR text: collapse blank lines + internal whitespace per line.
function normalize(text) {
  return text
    .split('\n')
    .map(function (l) { return l.replace(/\s+/g, ' ').trim(); })
    .join('\n');
}

function parseBolFields(text) {
  var norm = normalize(text);
  var lines = norm.split('\n');
  var out = {};
  for (var i = 0; i < FIELDS.length; i++) {
    var f = FIELDS[i];
    out[f.key] = f.multiLine ? matchBlock(lines, f) : matchLabeled(norm, f);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Main import — same signature as before, now writes full BOL columns.
// ---------------------------------------------------------------------------
function importFoldersToIndividualSheets(folderIds) {
  if (!folderIds || folderIds.length === 0) {
    return { success: false, message: 'No folders selected.' };
  }

  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var headers = ['File Name', 'Link'];
  for (var h = 0; h < FIELDS.length; h++) headers.push(FIELDS[h].column);
  if (CONFIG.INCLUDE_RAW_TEXT) headers.push('Raw Text');

  var totalFilesSynced = 0;
  var totalOcrFailed = 0;
  var processedTabs = [];

  for (var i = 0; i < folderIds.length; i++) {
    var memoryMatrix = null;
    try {
      var folder = DriveApp.getFolderById(folderIds[i]);
      var folderName = folder.getName();
      var cleanTabName = folderName.replace(/[\\\/\?\*\[\]]/g, '').substring(0, 26);
      if (!cleanTabName.trim()) cleanTabName = 'Folder ' + (i + 1);

      var targetSheet = ss.getSheetByName(cleanTabName) || ss.insertSheet(cleanTabName);
      targetSheet.clear();
      targetSheet.getRange(1, 1, 1, headers.length).setValues([headers]);

      var files = folder.getFiles();
      memoryMatrix = [];
      var row = 2;
      var fileCount = 0;

      while (files.hasNext()) {
        var file = files.next();
        fileCount++;
        if (CONFIG.MAX_FILES_PER_RUN > 0 && fileCount > CONFIG.MAX_FILES_PER_RUN) break;

        var text = getFileText(file);
        if (!text) totalOcrFailed++;

        var fields = parseBolFields(text);
        var rowVals = [file.getName(), file.getUrl()];
        for (var c = 0; c < FIELDS.length; c++) rowVals.push(fields[FIELDS[c].key]);
        if (CONFIG.INCLUDE_RAW_TEXT) rowVals.push(text);

        memoryMatrix.push(rowVals);
        totalFilesSynced++;

        // write incrementally so a 6-min timeout doesn't lose everything
        if (memoryMatrix.length >= 10) {
          targetSheet.getRange(row, 1, memoryMatrix.length, headers.length).setValues(memoryMatrix);
          row += memoryMatrix.length;
          memoryMatrix = [];
          SpreadsheetApp.flush();
        }
        Utilities.sleep(CONFIG.SLEEP_MS);
      }

      if (memoryMatrix.length > 0) {
        targetSheet.getRange(row, 1, memoryMatrix.length, headers.length).setValues(memoryMatrix);
      }
      targetSheet.setFrozenRows(1);
      targetSheet.getRange(1, 1, 1, headers.length)
        .setFontWeight('bold')
        .setBackground('#e6f4ea');
      processedTabs.push(folderName);
    } catch (err) {
      return { success: false, message: 'Folder error: ' + err.toString() };
    } finally {
      memoryMatrix = null;
    }
  }

  return {
    success: true,
    message: processedTabs.length + ' folders · ' + totalFilesSynced +
      ' files parsed' + (totalOcrFailed ? ' · ' + totalOcrFailed + ' OCR failures (see Logs)' : ''),
  };
}

// ---------------------------------------------------------------------------
// Debug helper — dump the OCR text of the first file in a folder so you can
// tune the FIELDS regexes against your real BOL layout.
// ---------------------------------------------------------------------------
function debugDumpText(folderId) {
  var folder = DriveApp.getFolderById(folderId);
  var files = folder.getFiles();
  if (!files.hasNext()) { Logger.log('No files in folder.'); return; }
  var file = files.next();
  Logger.log('=== ' + file.getName() + ' ===');
  Logger.log(getFileText(file));
}
