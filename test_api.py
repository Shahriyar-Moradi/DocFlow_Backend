"""
Test script for FastAPI Document Automation Backend
"""
import requests
import json
import time
from pathlib import Path

BASE_URL = "http://localhost:8080"

def test_health_check():
    """Test health check endpoint"""
    print("\n" + "="*50)
    print("Testing Health Check Endpoint")
    print("="*50)
    try:
        response = requests.get(f"{BASE_URL}/health")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_root_endpoint():
    """Test root endpoint"""
    print("\n" + "="*50)
    print("Testing Root Endpoint")
    print("="*50)
    try:
        response = requests.get(f"{BASE_URL}/")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_list_documents():
    """Test list documents endpoint"""
    print("\n" + "="*50)
    print("Testing List Documents Endpoint")
    print("="*50)
    try:
        response = requests.get(f"{BASE_URL}/api/v1/documents?page=1&page_size=10")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_search_documents():
    """Test search documents endpoint"""
    print("\n" + "="*50)
    print("Testing Search Documents Endpoint")
    print("="*50)
    try:
        params = {
            "page": 1,
            "page_size": 10
        }
        response = requests.get(f"{BASE_URL}/api/v1/documents/search", params=params)
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_upload_document(file_path=None):
    """Test upload document endpoint"""
    print("\n" + "="*50)
    print("Testing Upload Document Endpoint")
    print("="*50)
    try:
        # Create a dummy file if no file provided
        if file_path is None or not Path(file_path).exists():
            print("No test file provided, creating dummy file...")
            dummy_file = Path("test_document.png")
            dummy_file.write_bytes(b"dummy image data")
            file_path = str(dummy_file)
        
        with open(file_path, 'rb') as f:
            files = {'file': (Path(file_path).name, f, 'image/png')}
            response = requests.post(f"{BASE_URL}/api/v1/documents/upload", files=files)
        
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        
        # Clean up dummy file
        if Path(file_path).name == "test_document.png":
            Path(file_path).unlink()
        
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_get_document(document_id):
    """Test get document endpoint"""
    print("\n" + "="*50)
    print(f"Testing Get Document Endpoint (ID: {document_id})")
    print("="*50)
    try:
        response = requests.get(f"{BASE_URL}/api/v1/documents/{document_id}")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_job_status(job_id):
    """Test job status endpoint"""
    print("\n" + "="*50)
    print(f"Testing Job Status Endpoint (ID: {job_id})")
    print("="*50)
    try:
        response = requests.get(f"{BASE_URL}/api/v1/jobs/{job_id}/status")
        print(f"Status Code: {response.status_code}")
        print(f"Response: {json.dumps(response.json(), indent=2)}")
        return response.status_code == 200
    except Exception as e:
        print(f"Error: {e}")
        return False

def main():
    """Run all tests"""
    print("\n" + "="*50)
    print("FastAPI Document Automation Backend - API Tests")
    print("="*50)
    
    # Wait a bit for server to be ready
    print("\nWaiting for server to be ready...")
    time.sleep(2)
    
    results = {}
    
    # Test 1: Health check
    results['health_check'] = test_health_check()
    
    # Test 2: Root endpoint
    results['root'] = test_root_endpoint()
    
    # Test 3: List documents
    results['list_documents'] = test_list_documents()
    
    # Test 4: Search documents
    results['search_documents'] = test_search_documents()
    
    # Test 5: Upload document
    results['upload_document'] = test_upload_document()
    
    # Test 6: Get document (if we have an ID from upload)
    # This would need a real document ID from a previous upload
    
    # Summary
    print("\n" + "="*50)
    print("Test Results Summary")
    print("="*50)
    for test_name, passed in results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{test_name}: {status}")
    
    total = len(results)
    passed = sum(results.values())
    print(f"\nTotal: {passed}/{total} tests passed")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    exit(0 if success else 1)

