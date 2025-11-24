# Firestore Configuration Documentation

## Table of Contents
1. [Overview](#overview)
2. [Project Setup](#project-setup)
3. [Collections Structure](#collections-structure)
4. [Data Models](#data-models)
5. [Indexes](#indexes)
6. [Security Rules](#security-rules)
7. [Environment Configuration](#environment-configuration)
8. [Usage in Codebase](#usage-in-codebase)
9. [Deployment](#deployment)
10. [Troubleshooting](#troubleshooting)

---

## Overview

Firestore is used as the primary database for storing document metadata, processing job status, and workflow definitions in the DocFlow Backend system.

### Key Features
- **Real-time Database**: NoSQL document database
- **Scalable**: Automatically scales with your application
- **Integrated**: Part of Google Cloud Platform (GCP)
- **Collections**: Organized data structure with three main collections

### Project Information
- **Project ID**: `rocasoft`
- **Project Name**: Document Automation System
- **Database Mode**: Native mode (recommended for new projects)

---

## Project Setup

### Prerequisites
1. Google Cloud Project with billing enabled
2. Firestore API enabled
3. Authentication credentials configured

### Enable Firestore API

```bash
# Enable Firestore API
gcloud services enable firestore.googleapis.com --project=rocasoft

# Or via console
# Visit: https://console.cloud.google.com/apis/library/firestore.googleapis.com?project=rocasoft
```

### Firebase Console Links
- **Project Console**: https://console.firebase.google.com/project/rocasoft
- **Firestore Database**: https://console.firebase.google.com/project/rocasoft/firestore
- **Index Management**: https://console.firebase.google.com/v1/r/project/rocasoft/firestore/indexes

---

## Collections Structure

The Firestore database consists of three main collections:

### 1. `documents` Collection
Stores metadata for all uploaded and processed documents.

**Purpose**: Document records with metadata, processing status, and extracted data.

### 2. `processing_jobs` Collection
Tracks background processing jobs for batch document uploads.

**Purpose**: Job status, progress tracking, and batch operation results.

### 3. `flows` Collection
Manages document workflow definitions and organization.

**Purpose**: Flow/workflow definitions that group related documents.

---

## Data Models

### Document Model (`documents` collection)

```typescript
{
  // Document Identification
  document_id: string,              // Auto-generated document ID
  filename: string,                 // Stored filename
  original_filename: string,        // Original upload filename
  file_type: string,                // File extension (.pdf, .png, etc.)
  file_size: number,                // File size in bytes
  
  // Storage Information
  gcs_path: string,                 // Google Cloud Storage path
  download_url: string,             // Public download URL (optional)
  
  // Processing Status
  processing_status: string,        // 'pending' | 'processing' | 'completed' | 'failed'
  status: string,                   // Alternative status field
  
  // Classification & Metadata
  document_type: string,            // Document type classification
  metadata: {
    classification: string,          // Backend classification (e.g., 'MPU', 'Invoice')
    ui_category: string,            // UI category (e.g., 'Invoices', 'Contracts')
    document_no: string,            // Document number
    document_date: string,          // Document date (YYYY-MM-DD)
    branch_id: string,              // Branch identifier
    invoice_amount_usd: string,     // Invoice amount in USD
    invoice_amount_aed: string,     // Invoice amount in AED
    // ... other extracted fields
  },
  
  // Flow Association
  flow_id: string,                  // Associated flow ID (optional)
  
  // Timestamps
  created_at: Timestamp,            // Server timestamp
  updated_at: Timestamp,            // Server timestamp
  
  // Extracted Data
  extracted_data: object,          // Full extracted data object
  classification_confidence: number // Classification confidence (0-1)
}
```

### Job Model (`processing_jobs` collection)

```typescript
{
  // Job Identification
  job_id: string,                   // Auto-generated job ID
  
  // Job Status
  status: string,                    // 'pending' | 'processing' | 'completed' | 'failed'
  
  // Progress Tracking
  total_documents: number,           // Total documents in batch
  processed_documents: number,       // Successfully processed count
  failed_documents: number,          // Failed documents count
  
  // Job Details
  uploaded_at: Timestamp,           // Upload timestamp
  completed_at: Timestamp,          // Completion timestamp (if completed)
  
  // Timestamps
  created_at: Timestamp,            // Server timestamp
  updated_at: Timestamp,            // Server timestamp
  
  // Additional Metadata
  flow_id: string,                  // Associated flow ID (optional)
  error_message: string,           // Error message if failed
}
```

### Flow Model (`flows` collection)

```typescript
{
  // Flow Identification
  flow_id: string,                  // Auto-generated flow ID
  flow_name: string,                // User-defined flow name
  
  // Flow Statistics
  document_count: number,           // Number of documents in flow
  
  // Timestamps
  created_at: Timestamp,            // Server timestamp
  updated_at: Timestamp,           // Server timestamp
  
  // Additional Metadata
  description: string,             // Flow description (optional)
  user_id: string,                 // User identifier (optional)
}
```

---

## Indexes

Firestore requires composite indexes for queries that filter on multiple fields or order by fields that aren't in the filter.

### Required Indexes

All indexes are defined in `firestore.indexes.json`:

#### 1. Documents by Flow and Created Date
```json
{
  "collectionGroup": "documents",
  "queryScope": "COLLECTION",
  "fields": [
    {"fieldPath": "flow_id", "order": "ASCENDING"},
    {"fieldPath": "created_at", "order": "DESCENDING"}
  ]
}
```

**Used for**: Listing documents within a specific flow, ordered by creation date.

#### 2. Documents by Flow, Status, and Created Date
```json
{
  "collectionGroup": "documents",
  "queryScope": "COLLECTION",
  "fields": [
    {"fieldPath": "flow_id", "order": "ASCENDING"},
    {"fieldPath": "status", "order": "ASCENDING"},
    {"fieldPath": "created_at", "order": "DESCENDING"}
  ]
}
```

**Used for**: Filtering documents by flow and status, ordered by creation date.

#### 3. Documents by User and Created Date
```json
{
  "collectionGroup": "documents",
  "queryScope": "COLLECTION",
  "fields": [
    {"fieldPath": "user_id", "order": "ASCENDING"},
    {"fieldPath": "created_at", "order": "DESCENDING"}
  ]
}
```

**Used for**: User-specific document listings.

### Deploying Indexes

#### Option 1: Via Firebase Console (Recommended)
1. Click the direct link: https://console.firebase.google.com/v1/r/project/rocasoft/firestore/indexes?create_composite=...
2. Click "Create Index"
3. Wait 2-5 minutes for building

#### Option 2: Via Firebase CLI
```bash
cd mobile_app/DocFlow_Backend
firebase deploy --only firestore:indexes
```

#### Option 3: Via npx (No Installation)
```bash
cd mobile_app/DocFlow_Backend
npx firebase-tools deploy --only firestore:indexes
```

### Index Status
- Check index status: https://console.firebase.google.com/project/rocasoft/firestore/indexes
- Indexes typically build in 2-5 minutes
- App works without indexes (using fallback), but queries are slower

---

## Security Rules

Security rules control access to Firestore data. Current rules are in `firestore.rules`.

### Current Rules (Development Mode)

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Documents collection
    match /documents/{documentId} {
      allow read, write: if true;
    }
    
    // Flows collection
    match /flows/{flowId} {
      allow read, write: if true;
    }
    
    // Allow read/write to all other collections (for development)
    match /{document=**} {
      allow read, write: if true;
    }
  }
}
```

**⚠️ WARNING**: Current rules allow unrestricted access. This is for development only!

### Production Security Rules (Recommended)

```javascript
rules_version = '2';
service cloud.firestore {
  match /databases/{database}/documents {
    // Helper function to check authentication
    function isAuthenticated() {
      return request.auth != null;
    }
    
    // Helper function to check if user owns the document
    function isOwner(userId) {
      return isAuthenticated() && request.auth.uid == userId;
    }
    
    // Documents collection
    match /documents/{documentId} {
      // Allow read if authenticated
      allow read: if isAuthenticated();
      
      // Allow write if authenticated and owner
      allow create: if isAuthenticated() && 
                       request.resource.data.user_id == request.auth.uid;
      allow update, delete: if isAuthenticated() && 
                              resource.data.user_id == request.auth.uid;
    }
    
    // Flows collection
    match /flows/{flowId} {
      allow read: if isAuthenticated();
      allow write: if isAuthenticated() && 
                      request.resource.data.user_id == request.auth.uid;
    }
    
    // Processing jobs collection
    match /processing_jobs/{jobId} {
      allow read: if isAuthenticated();
      allow write: if isAuthenticated();
    }
  }
}
```

### Deploying Security Rules

```bash
cd mobile_app/DocFlow_Backend
firebase deploy --only firestore:rules
```

---

## Environment Configuration

### Configuration File
Settings are defined in `config.py`:

```python
# Firestore Configuration
FIRESTORE_PROJECT_ID: str = os.getenv("FIRESTORE_PROJECT_ID", "rocasoft")
FIRESTORE_COLLECTION_DOCUMENTS: str = "documents"
FIRESTORE_COLLECTION_JOBS: str = "processing_jobs"
FIRESTORE_COLLECTION_FLOWS: str = "flows"
```

### Environment Variables

Create a `.env` file in `mobile_app/DocFlow_Backend/`:

```bash
# Firestore Configuration
FIRESTORE_PROJECT_ID=rocasoft

# Optional: Override collection names (if needed)
# FIRESTORE_COLLECTION_DOCUMENTS=documents
# FIRESTORE_COLLECTION_JOBS=processing_jobs
# FIRESTORE_COLLECTION_FLOWS=flows
```

### Authentication

Firestore uses Application Default Credentials (ADC) in the following order:

1. **Service Account Key File** (if specified):
   ```bash
   GCS_SERVICE_ACCOUNT_KEY=/path/to/service-account-key.json
   ```

2. **Environment Variable**:
   ```bash
   export GOOGLE_APPLICATION_CREDENTIALS="/path/to/service-account-key.json"
   ```

3. **Application Default Credentials** (gcloud CLI):
   ```bash
   gcloud auth application-default login
   ```

4. **Compute Engine/Cloud Run Service Account** (when deployed)

---

## Usage in Codebase

### Initialization

The `FirestoreService` class handles all Firestore operations:

```python
from services.firestore_service import FirestoreService

# Initialize service (singleton pattern)
firestore_service = FirestoreService()
```

### Document Operations

#### Create Document
```python
document_data = {
    'filename': 'invoice_001.pdf',
    'original_filename': 'invoice.pdf',
    'file_type': '.pdf',
    'file_size': 102400,
    'gcs_path': 'gs://bucket/path/to/file.pdf',
    'processing_status': 'pending',
    'metadata': {
        'classification': 'Invoice',
        'ui_category': 'Invoices',
        'document_no': 'INV-001'
    }
}

document_id = firestore_service.create_document('doc_123', document_data)
```

#### Get Document
```python
document = firestore_service.get_document('doc_123')
if document:
    print(document['filename'])
```

#### Update Document
```python
update_data = {
    'processing_status': 'completed',
    'metadata.document_date': '2025-11-24'
}
firestore_service.update_document('doc_123', update_data)
```

#### List Documents with Filters
```python
filters = {
    'ui_category': 'Invoices',
    'branch_id': '01'
}
documents, total = firestore_service.list_documents(
    page=1,
    page_size=20,
    filters=filters
)
```

#### Search Documents
```python
search_params = {
    'classification': 'Invoice',
    'date_from': '2025-01-01',
    'date_to': '2025-12-31',
    'min_amount_usd': '100',
    'page': 1,
    'page_size': 20
}
documents, total = firestore_service.search_documents(search_params)
```

### Job Operations

#### Create Job
```python
job_data = {
    'total_documents': 10,
    'flow_id': 'flow_123'
}
job_id = firestore_service.create_job('job_456', job_data)
```

#### Update Job Progress
```python
firestore_service.update_job_progress(
    job_id='job_456',
    processed=5,
    failed=1,
    status='processing'
)
```

### Flow Operations

#### Create Flow
```python
flow_data = {
    'flow_name': 'Invoice Processing',
    'document_count': 0
}
flow_id = firestore_service.create_flow('flow_789', flow_data)
```

#### Get Flow Documents
```python
filters = {'flow_id': 'flow_789'}
documents, total = firestore_service.list_documents(
    page=1,
    page_size=100,
    filters=filters
)
```

---

## Deployment

### Local Development

1. **Set up authentication**:
   ```bash
   gcloud auth application-default login
   ```

2. **Set environment variables**:
   ```bash
   export FIRESTORE_PROJECT_ID=rocasoft
   ```

3. **Run the application**:
   ```bash
   cd mobile_app/DocFlow_Backend
   python main.py
   ```

### Cloud Run Deployment

Firestore configuration is automatically used when deployed to Cloud Run. Ensure:

1. **Service Account Permissions**:
   ```bash
   gcloud projects add-iam-policy-binding rocasoft \
     --member="serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
     --role="roles/datastore.user"
   ```

2. **Environment Variables** (set in Cloud Run):
   ```bash
   FIRESTORE_PROJECT_ID=rocasoft
   ```

3. **Deploy**:
   ```bash
   gcloud run deploy docflow-backend \
     --source . \
     --region us-central1 \
     --set-env-vars "FIRESTORE_PROJECT_ID=rocasoft"
   ```

### Firebase Deployment

Deploy Firestore rules and indexes:

```bash
cd mobile_app/DocFlow_Backend

# Deploy security rules
firebase deploy --only firestore:rules

# Deploy indexes
firebase deploy --only firestore:indexes

# Deploy both
firebase deploy --only firestore
```

---

## Troubleshooting

### Common Issues

#### 1. "Firestore API has not been used" Error

**Error**: `403 Cloud Firestore API has not been used in project rocasoft before or it is disabled`

**Solution**:
1. Enable Firestore API:
   ```bash
   gcloud services enable firestore.googleapis.com --project=rocasoft
   ```
2. Or visit: https://console.developers.google.com/apis/api/firestore.googleapis.com/overview?project=rocasoft

#### 2. Missing Index Error

**Error**: `The query requires an index`

**Solution**:
1. Click the link provided in the error message
2. Or deploy indexes manually:
   ```bash
   firebase deploy --only firestore:indexes
   ```

#### 3. Authentication Error

**Error**: `403 Permission denied`

**Solution**:
1. Check service account permissions
2. Verify authentication:
   ```bash
   gcloud auth application-default login
   ```
3. Check service account key file path

#### 4. Collection Not Found

**Error**: Collection doesn't exist

**Solution**:
- Collections are created automatically on first write
- No manual creation needed

### Testing Firestore Connection

Use the test script:

```bash
cd mobile_app/DocFlow_Backend
python test_firestore_complete.py
```

### Checking Firestore Status

```bash
cd mobile_app/DocFlow_Backend
python check_status.py
```

### Viewing Data in Console

1. Visit: https://console.firebase.google.com/project/rocasoft/firestore
2. Navigate to the collection
3. View documents and their fields

---

## Best Practices

### 1. Use Server Timestamps
Always use `firestore.SERVER_TIMESTAMP` for `created_at` and `updated_at`:
```python
data['created_at'] = firestore.SERVER_TIMESTAMP
```

### 2. Batch Operations
For multiple writes, use batch operations:
```python
batch = firestore_service.db.batch()
# Add operations to batch
batch.commit()
```

### 3. Error Handling
Always wrap Firestore operations in try-except blocks:
```python
try:
    result = firestore_service.create_document(doc_id, data)
except Exception as e:
    logger.error(f"Firestore error: {e}")
```

### 4. Pagination
Always use pagination for large result sets:
```python
documents, total = firestore_service.list_documents(
    page=1,
    page_size=20  # Reasonable page size
)
```

### 5. Index Optimization
- Create indexes only for queries you actually use
- Monitor index usage in Firebase Console
- Remove unused indexes to save costs

---

## Additional Resources

- **Firestore Documentation**: https://firebase.google.com/docs/firestore
- **Firestore Python SDK**: https://googleapis.dev/python/firestore/latest/
- **Firebase Console**: https://console.firebase.google.com/project/rocasoft
- **Index Management**: https://console.firebase.google.com/project/rocasoft/firestore/indexes
- **Security Rules Guide**: https://firebase.google.com/docs/firestore/security/get-started

---

## Support

For issues or questions:
1. Check the troubleshooting section above
2. Review Firebase Console for errors
3. Check application logs: `server.log`
4. Verify environment variables and authentication

---

**Last Updated**: November 2025  
**Project**: DocFlow Backend  
**Firestore Project ID**: `rocasoft`

