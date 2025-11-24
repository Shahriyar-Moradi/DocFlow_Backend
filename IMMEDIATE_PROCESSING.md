# Immediate Processing Response

## Overview

The upload endpoint now performs quick classification and extraction **synchronously** before returning the response, so you get the classification type and extracted data immediately.

## Updated Response Structure

### Before
```json
{
  "document_id": "...",
  "status": "pending",
  "message": "Document uploaded successfully and queued for processing",
  "uploaded_at": "..."
}
```

### After
```json
{
  "document_id": "0ca7b9b3-017e-4c9e-8dab-4aec1053a1d9",
  "status": "processing",
  "message": "Document uploaded and processed successfully",
  "uploaded_at": "2025-11-24T11:02:38.254699",
  "document_type": "Invoice",
  "classification_confidence": 0.95,
  "extracted_data": {
    "document_number": "INV-2025-001",
    "issue_date": "2025-01-15",
    "total_amount": "1500.00",
    "currency": "USD",
    "buyer": {...},
    "seller": {...},
    "items": [...],
    "terms": "...",
    "signatures": {...}
  },
  "document_number": "INV-2025-001",
  "document_date": "2025-01-15",
  "total_amount": "1500.00",
  "currency": "USD"
}
```

## Response Fields

### New Fields Added
- **`document_type`**: Classification result (Invoice, Receipt, Contract, etc.)
- **`classification_confidence`**: Confidence score (0.0-1.0)
- **`extracted_data`**: Complete JSON with all extracted fields
- **`document_number`**: Extracted document number/ID
- **`document_date`**: Extracted date
- **`total_amount`**: Extracted total amount
- **`currency`**: Currency code (USD, AED, etc.)

## Processing Flow

1. **Upload File** → File uploaded to GCS temp folder
2. **Quick Classification** → Document type identified (2-5 seconds)
3. **Quick Extraction** → Key data extracted (3-8 seconds)
4. **Return Response** → Immediate response with classification and extracted data
5. **Background Processing** → Full processing continues (organized path, PDF conversion, etc.)

## Performance

- **Upload Response Time**: 5-15 seconds (includes classification + extraction)
- **Background Processing**: Continues after response (organized path, final storage)

## Error Handling

- If quick processing fails, upload still succeeds
- Response includes `document_type: "Other"` and `classification_confidence: 0.0`
- Full processing continues in background
- Errors are logged but don't block the upload

## Example Response

### Invoice
```json
{
  "document_id": "abc123",
  "status": "processing",
  "document_type": "Invoice",
  "classification_confidence": 0.95,
  "document_number": "INV-2025-001",
  "document_date": "2025-01-15",
  "total_amount": "1500.00",
  "currency": "USD",
  "extracted_data": {
    "document_number": "INV-2025-001",
    "issue_date": "2025-01-15",
    "due_date": "2025-02-15",
    "total_amount": "1500.00",
    "currency": "USD",
    "buyer": {
      "name": "Company Name",
      "address": "123 Main St"
    },
    "seller": {
      "name": "Vendor Name"
    },
    "items": [
      {
        "description": "Product Name",
        "quantity": "2",
        "unit_price": "650.00",
        "total": "1300.00"
      }
    ],
    "terms": "Net 30 days"
  }
}
```

### Voucher
```json
{
  "document_id": "abc123",
  "status": "processing",
  "document_type": "Voucher",
  "classification_confidence": 0.98,
  "document_number": "MPU01-85285",
  "document_date": "02/06/2025",
  "total_amount": "2154100.49",
  "currency": "USD",
  "extracted_data": {
    "document_no": "MPU01-85285",
    "category_type": "MPU",
    "branch_id": "01",
    "document_date": "02/06/2025",
    "invoice_amount_usd": "2154100.49",
    "invoice_amount_aed": "7914165.20",
    "gold_weight": "20000.000",
    "purity": "1.000"
  }
}
```

## Notes

- Processing happens synchronously before response (5-15 seconds)
- Full processing (organized path, PDF conversion) continues in background
- If processing fails, upload still succeeds with basic info
- All extracted data is available immediately in response


