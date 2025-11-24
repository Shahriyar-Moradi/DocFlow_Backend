# Firestore Index Configuration

This document explains how to set up the required Firestore indexes for the DocFlow Backend.

## Why Indexes Are Needed

Firestore requires composite indexes for queries that:
1. Filter on one field and order by another field
2. Use multiple inequality filters
3. Use array-contains with other filters

Our application uses such queries, particularly:
- Filtering by `flow_id` and ordering by `created_at`
- Filtering by `user_id` and ordering by `created_at`

## Current Status

The code has been updated to handle missing indexes gracefully by:
- First attempting to use the indexed query (fastest)
- Falling back to client-side sorting if the index doesn't exist
- Logging warnings to remind you to create the index

**Note:** While the fallback works, creating the proper indexes will significantly improve performance, especially with large datasets.

## Option 1: Create Index via Console (Quickest)

When you see the index error in the logs, it includes a direct link to create the index. Click the link and follow the Firebase Console prompts.

Example error with link:
```
Failed to get documents by flow_id: 400 The query requires an index. 
You can create it here: https://console.firebase.google.com/v1/r/project/rocasoft/firestore/indexes?create_composite=...
```

## Option 2: Deploy via Firebase CLI (Recommended for Production)

### Prerequisites
```bash
# Install Firebase CLI if not already installed
npm install -g firebase-tools

# Login to Firebase
firebase login
```

### Deploy Indexes

1. Initialize Firebase in your project (if not already done):
```bash
cd /path/to/DocFlow_Backend
firebase init firestore
```

2. When prompted:
   - Select your Firebase project (rocasoft)
   - Use the existing `firestore.indexes.json` file
   - Don't overwrite existing rules

3. Deploy the indexes:
```bash
firebase deploy --only firestore:indexes
```

4. Wait for indexes to build (can take several minutes):
   - You'll receive an email when indexes are ready
   - Or check status in Firebase Console → Firestore → Indexes

## Option 3: Manual Creation in Firebase Console

1. Go to [Firebase Console](https://console.firebase.google.com)
2. Select your project (rocasoft)
3. Navigate to Firestore Database → Indexes
4. Click "Add Index"
5. Configure each index:

### Index 1: flow_id + created_at
- Collection: `documents`
- Fields:
  - `flow_id` (Ascending)
  - `created_at` (Descending)
- Query scope: Collection

### Index 2: flow_id + status + created_at
- Collection: `documents`
- Fields:
  - `flow_id` (Ascending)
  - `status` (Ascending)
  - `created_at` (Descending)
- Query scope: Collection

### Index 3: user_id + created_at
- Collection: `documents`
- Fields:
  - `user_id` (Ascending)
  - `created_at` (Descending)
- Query scope: Collection

## Verify Indexes

After creating indexes:

1. Check status in Firebase Console → Firestore → Indexes
2. Wait until all indexes show "Enabled" status
3. Test your queries - they should work without fallback warnings
4. Check logs - no more "index not available" warnings

## Performance Impact

**Without Indexes:**
- Queries fall back to client-side sorting
- All matching documents are fetched from Firestore
- Sorting happens in application memory
- Slower for large datasets (>100 documents)

**With Indexes:**
- Firestore handles sorting server-side
- Only requested page of documents is transferred
- Significantly faster, especially with pagination
- Lower bandwidth usage

## Troubleshooting

### Index Creation Fails
- Ensure you have Firebase Admin permissions
- Check project quota limits
- Try creating indexes one at a time

### Index Stays in "Building" State
- Large collections can take 10-30 minutes
- Check for any quota warnings in console
- Indexes build in background - app still works with fallback

### Still Getting Index Errors
- Clear browser cache
- Verify index status shows "Enabled"
- Check that field names match exactly (case-sensitive)
- Restart your backend service

## Index File Location

The index configuration is stored in:
```
mobile_app/DocFlow_Backend/firestore.indexes.json
```

This file should be committed to version control and deployed with your application.

