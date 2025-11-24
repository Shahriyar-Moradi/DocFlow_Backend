"""
Test GCS upload directly (bypassing Firestore)
"""
import os
from pathlib import Path
from google.cloud import storage
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

PROJECT_ID = os.getenv("GCS_PROJECT_ID", "rocasoft")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "voucher-bucket-1")

def test_gcs_upload():
    """Test direct GCS upload"""
    print("="*60)
    print("Testing Direct GCS Upload")
    print("="*60)
    
    # Create test image
    print("\n📝 Creating test image...")
    img = Image.new('RGB', (200, 200), color='blue')
    test_file = Path("test_gcs_upload.png")
    img.save(test_file)
    print(f"✅ Created: {test_file} ({test_file.stat().st_size} bytes)")
    
    try:
        # Initialize GCS client
        print(f"\n🔌 Connecting to GCS...")
        print(f"   Project: {PROJECT_ID}")
        print(f"   Bucket: {BUCKET_NAME}")
        client = storage.Client(project=PROJECT_ID)
        bucket = client.bucket(BUCKET_NAME)
        
        if not bucket.exists():
            print(f"❌ Bucket {BUCKET_NAME} does not exist!")
            return
        
        print("✅ Bucket exists and is accessible")
        
        # Upload test file
        test_path = f"test_uploads/{test_file.name}"
        print(f"\n📤 Uploading to: {test_path}")
        blob = bucket.blob(test_path)
        blob.upload_from_filename(str(test_file))
        print(f"✅ Upload successful!")
        print(f"   GCS Path: gs://{BUCKET_NAME}/{test_path}")
        print(f"   Size: {blob.size} bytes")
        
        # Verify upload
        print(f"\n🔍 Verifying upload...")
        if blob.exists():
            print("✅ File exists in bucket!")
            
            # List all files
            print(f"\n📋 Listing all files in bucket:")
            blobs = list(client.list_blobs(BUCKET_NAME))
            if blobs:
                print(f"   Found {len(blobs)} file(s):")
                for b in blobs:
                    print(f"   - {b.name} ({b.size} bytes)")
            else:
                print("   Bucket is empty")
        else:
            print("❌ File not found after upload")
        
        # Download test
        print(f"\n📥 Testing download...")
        download_path = Path("test_download.png")
        blob.download_to_filename(str(download_path))
        if download_path.exists():
            print(f"✅ Download successful: {download_path}")
            download_path.unlink()
        
    except Exception as e:
        print(f"❌ Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        # Cleanup
        if test_file.exists():
            test_file.unlink()
            print(f"\n🧹 Cleaned up test file")

if __name__ == "__main__":
    test_gcs_upload()

