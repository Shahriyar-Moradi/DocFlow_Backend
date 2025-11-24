"""
Complete test of Firestore operations
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import firestore
from datetime import datetime

load_dotenv()

PROJECT_ID = os.getenv("GCS_PROJECT_ID", "rocasoft")
COLLECTION = "documents"

def test_firestore_operations():
    """Test all Firestore operations"""
    print("="*60)
    print("Testing Firestore Operations")
    print("="*60)
    
    try:
        # Initialize Firestore
        print(f"\n🔌 Connecting to Firestore...")
        print(f"   Project: {PROJECT_ID}")
        print(f"   Collection: {COLLECTION}")
        db = firestore.Client(project=PROJECT_ID)
        collection = db.collection(COLLECTION)
        print("✅ Connected successfully!")
        
        # Test 1: Create a document
        print(f"\n📝 Test 1: Creating a test document...")
        test_doc_id = f"test_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        test_data = {
            'filename': 'test_document.png',
            'original_filename': 'test_document.png',
            'file_type': '.png',
            'file_size': 1024,
            'gcs_path': 'gs://voucher-bucket-1/test/test_document.png',
            'processing_status': 'completed',
            'created_at': firestore.SERVER_TIMESTAMP,
            'updated_at': firestore.SERVER_TIMESTAMP,
            'metadata': {
                'document_no': 'TEST01-12345',
                'classification': 'MPU',
                'branch_id': '01',
                'document_date': '2025-11-23'
            }
        }
        doc_ref = collection.document(test_doc_id)
        doc_ref.set(test_data)
        print(f"✅ Created document: {test_doc_id}")
        
        # Test 2: Read the document
        print(f"\n📖 Test 2: Reading the document...")
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            print(f"✅ Document found!")
            print(f"   Filename: {data.get('filename')}")
            print(f"   Status: {data.get('processing_status')}")
            print(f"   Document No: {data.get('metadata', {}).get('document_no')}")
        else:
            print("❌ Document not found")
            return
        
        # Test 3: Update the document
        print(f"\n✏️  Test 3: Updating the document...")
        doc_ref.update({
            'processing_status': 'updated',
            'updated_at': firestore.SERVER_TIMESTAMP
        })
        doc = doc_ref.get()
        if doc.exists:
            data = doc.to_dict()
            print(f"✅ Document updated!")
            print(f"   New Status: {data.get('processing_status')}")
        
        # Test 4: List all documents
        print(f"\n📋 Test 4: Listing all documents...")
        docs = list(collection.limit(10).stream())
        print(f"✅ Found {len(docs)} document(s):")
        for doc in docs:
            data = doc.to_dict()
            print(f"   - {doc.id}: {data.get('filename')} ({data.get('processing_status')})")
        
        # Test 5: Query documents
        print(f"\n🔍 Test 5: Querying documents by status...")
        query = collection.where('processing_status', '==', 'completed')
        docs = list(query.limit(5).stream())
        print(f"✅ Found {len(docs)} document(s) with status 'completed'")
        
        # Test 6: Delete test document
        print(f"\n🗑️  Test 6: Deleting test document...")
        doc_ref.delete()
        doc = doc_ref.get()
        if not doc.exists:
            print(f"✅ Document deleted successfully!")
        else:
            print("❌ Document still exists")
        
        # Test 7: Check jobs collection
        print(f"\n📊 Test 7: Checking jobs collection...")
        jobs_collection = db.collection("processing_jobs")
        jobs = list(jobs_collection.limit(5).stream())
        print(f"✅ Found {len(jobs)} job(s):")
        for job in jobs:
            data = job.to_dict()
            print(f"   - {job.id}: {data.get('status')} ({data.get('total_documents', 0)} documents)")
        
        print(f"\n" + "="*60)
        print("✅ All Firestore tests passed!")
        print("="*60)
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    test_firestore_operations()

