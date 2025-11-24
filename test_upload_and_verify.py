"""
Test script to upload a file and verify it appears in GCS and Firestore
"""
import requests
import json
import time
from pathlib import Path
from google.cloud import storage
from google.cloud import firestore
import os
from dotenv import load_dotenv

BASE_URL = "http://localhost:8080"

# Load config
load_dotenv()
PROJECT_ID = os.getenv("GCS_PROJECT_ID", "rocasoft")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "voucher-bucket-1")

def create_test_image():
    """Create a simple test PNG image"""
    from PIL import Image
    img = Image.new('RGB', (100, 100), color='red')
    test_file = Path("test_upload.png")
    img.save(test_file)
    return test_file

def upload_file(file_path):
    """Upload file via API"""
    print(f"\n📤 Uploading file: {file_path}")
    with open(file_path, 'rb') as f:
        files = {'file': (file_path.name, f, 'image/png')}
        response = requests.post(f"{BASE_URL}/api/v1/documents/upload", files=files)
    
    print(f"Status Code: {response.status_code}")
    if response.status_code == 200:
        result = response.json()
        print(f"✅ Upload successful!")
        print(f"   Document ID: {result['document_id']}")
        print(f"   Status: {result['status']}")
        return result['document_id']
    else:
        print(f"❌ Upload failed: {response.text}")
        return None

def check_gcs_for_file(document_id, filename):
    """Check if file exists in GCS"""
    print(f"\n🔍 Checking GCS for file...")
    try:
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        
        # Check temp folder
        temp_path = f"temp/{document_id}/{filename}"
        blob = bucket.blob(temp_path)
        if blob.exists():
            print(f"✅ Found in temp folder: {temp_path}")
            print(f"   Size: {blob.size} bytes")
            return True
        
        # Check organized folder (if processed)
        blobs = list(client.list_blobs(BUCKET_NAME, prefix=f"organized_vouchers/"))
        if blobs:
            print(f"✅ Found {len(blobs)} file(s) in organized_vouchers/")
            for b in blobs[:5]:  # Show first 5
                print(f"   - {b.name} ({b.size} bytes)")
        else:
            print("⚠️ No files found in organized_vouchers/ yet (may still be processing)")
        
        return False
    except Exception as e:
        print(f"❌ Error checking GCS: {e}")
        return False

def check_firestore_for_document(document_id):
    """Check if document exists in Firestore"""
    print(f"\n🔍 Checking Firestore for document: {document_id}")
    try:
        db = firestore.Client(project=PROJECT_ID)
        doc_ref = db.collection("documents").document(document_id)
        doc = doc_ref.get()
        
        if doc.exists:
            data = doc.to_dict()
            print(f"✅ Found document in Firestore!")
            print(f"   Filename: {data.get('filename', 'N/A')}")
            print(f"   Status: {data.get('processing_status', 'N/A')}")
            print(f"   GCS Path: {data.get('gcs_path', 'N/A')}")
            return True
        else:
            print("⚠️ Document not found in Firestore yet")
            return False
    except Exception as e:
        print(f"❌ Error checking Firestore: {e}")
        return False

def list_all_gcs_files():
    """List all files in GCS bucket"""
    print(f"\n📋 Listing all files in GCS bucket: {BUCKET_NAME}")
    try:
        client = storage.Client(project=PROJECT_ID)
        blobs = list(client.list_blobs(BUCKET_NAME))
        
        if not blobs:
            print("   Bucket is empty")
            return
        
        print(f"   Found {len(blobs)} file(s):")
        for blob in blobs:
            print(f"   - {blob.name} ({blob.size} bytes) [{blob.time_created}]")
    except Exception as e:
        print(f"❌ Error listing files: {e}")

def main():
    print("="*60)
    print("Upload and Verify Test")
    print("="*60)
    
    # Wait for server
    print("\n⏳ Waiting for server to be ready...")
    time.sleep(2)
    
    # Check server health
    try:
        response = requests.get(f"{BASE_URL}/health")
        if response.status_code != 200:
            print("❌ Server not ready")
            return
    except:
        print("❌ Server not accessible")
        return
    
    # Create test file
    test_file = create_test_image()
    
    try:
        # Upload file
        document_id = upload_file(test_file)
        if not document_id:
            return
        
        # Wait a bit for processing
        print("\n⏳ Waiting 5 seconds for background processing...")
        time.sleep(5)
        
        # Check GCS
        list_all_gcs_files()
        check_gcs_for_file(document_id, test_file.name)
        
        # Check Firestore
        check_firestore_for_document(document_id)
        
        # Get document status via API
        print(f"\n📊 Getting document status via API...")
        response = requests.get(f"{BASE_URL}/api/v1/documents/{document_id}")
        if response.status_code == 200:
            doc = response.json()
            print(f"✅ Document Status: {doc.get('processing_status')}")
            print(f"   Organized Path: {doc.get('organized_path', 'N/A')}")
        
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
            print(f"\n🧹 Cleaned up test file")

if __name__ == "__main__":
    main()

