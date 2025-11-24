# How to Check GCS Bucket and Firestore Contents

## Quick Check Script

Run this command to check both GCS and Firestore:

```bash
cd mobile_app/backend
conda activate llm10
python check_status.py
```

## Manual Check via Google Cloud Console

### Check GCS Bucket (Files)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **Cloud Storage** > **Buckets**
3. Click on your bucket: `voucher-bucket-1`
4. You'll see folders:
   - `temp/` - Temporary uploads (before processing)
   - `organized_vouchers/` - Processed and organized documents
   - `test_uploads/` - Test files (if any)

### Check Firestore (Metadata)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Navigate to **Firestore** > **Data**
3. Look for collections:
   - `documents` - Document metadata
   - `processing_jobs` - Batch job status

**Note:** Firestore API must be enabled first. If you see an error, enable it at:
https://console.developers.google.com/apis/api/firestore.googleapis.com/overview?project=rocasoft

## Check via API

### List Documents
```bash
curl http://localhost:8080/api/v1/documents
```

### Get Specific Document
```bash
curl http://localhost:8080/api/v1/documents/{document_id}
```

### Search Documents
```bash
curl "http://localhost:8080/api/v1/documents/search?classification=MPU&page=1&page_size=10"
```

## Using gcloud CLI

### List GCS Files
```bash
gsutil ls gs://voucher-bucket-1/
gsutil ls -r gs://voucher-bucket-1/temp/
gsutil ls -r gs://voucher-bucket-1/organized_vouchers/
```

### Count Files
```bash
gsutil ls gs://voucher-bucket-1/** | wc -l
```

### Download a File
```bash
gsutil cp gs://voucher-bucket-1/path/to/file.png ./downloaded.png
```

## Current Status

✅ **GCS Bucket:** Working perfectly
- Files can be uploaded successfully
- Files are stored in `temp/` folder initially
- After processing, files move to `organized_vouchers/` folder

⚠️ **Firestore:** API needs to be enabled
- Enable at: https://console.developers.google.com/apis/api/firestore.googleapis.com/overview?project=rocasoft
- Once enabled, document metadata will be stored
- Uploads work even without Firestore (files still go to GCS)

