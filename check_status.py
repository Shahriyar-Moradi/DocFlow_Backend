"""
Utility script to check GCS bucket and Firestore contents
"""
import os
import sys
from pathlib import Path
from dotenv import load_dotenv
from google.cloud import storage
from google.cloud import firestore
from google.oauth2 import service_account

# Load environment variables
env_path = Path(__file__).parent / ".env"
load_dotenv(env_path)

# Configuration
PROJECT_ID = os.getenv("GCS_PROJECT_ID", "rocasoft")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "voucher-bucket-1")
FIRESTORE_COLLECTION = os.getenv("FIRESTORE_COLLECTION_DOCUMENTS", "documents")
KEY_PATH = os.getenv("GCS_SERVICE_ACCOUNT_KEY", str(Path(__file__).parent / "voucher-storage-key.json"))

def get_credentials():
    """Get credentials from file or ADC"""
    if os.path.exists(KEY_PATH):
        print(f"Using service account key: {KEY_PATH}")
        return service_account.Credentials.from_service_account_file(KEY_PATH)
    else:
        print("Using Application Default Credentials (ADC)")
        return None

def check_gcs(credentials):
    """Check GCS bucket contents"""
    print("\n" + "="*50)
    print(f"Checking GCS Bucket: {BUCKET_NAME}")
    print("="*50)
    
    try:
        client = storage.Client(project=PROJECT_ID, credentials=credentials)
        bucket = client.bucket(BUCKET_NAME)
        
        if not bucket.exists():
            print(f"❌ Bucket {BUCKET_NAME} does not exist!")
            return

        blobs = list(client.list_blobs(BUCKET_NAME, max_results=20))
        
        if not blobs:
            print("Bucket is empty.")
        else:
            print(f"Found {len(blobs)} files (showing first 20):")
            for blob in blobs:
                print(f" - {blob.name} ({blob.size} bytes) [{blob.time_created}]")
                
    except Exception as e:
        print(f"❌ Error checking GCS: {e}")

def check_firestore(credentials):
    """Check Firestore documents"""
    print("\n" + "="*50)
    print(f"Checking Firestore Collection: {FIRESTORE_COLLECTION}")
    print("="*50)
    
    try:
        db = firestore.Client(project=PROJECT_ID, credentials=credentials)
        collection = db.collection(FIRESTORE_COLLECTION)
        
        docs = list(collection.limit(20).stream())
        
        if not docs:
            print("Collection is empty.")
        else:
            print(f"Found {len(docs)} documents (showing first 20):")
            for doc in docs:
                data = doc.to_dict()
                print(f" - ID: {doc.id}")
                print(f"   File: {data.get('filename', 'N/A')}")
                print(f"   Status: {data.get('processing_status', 'N/A')}")
                print(f"   Created: {data.get('created_at', 'N/A')}")
                print("-" * 30)
                
    except Exception as e:
        print(f"❌ Error checking Firestore: {e}")

if __name__ == "__main__":
    print(f"Project ID: {PROJECT_ID}")
    
    creds = get_credentials()
    
    check_gcs(creds)
    check_firestore(creds)

