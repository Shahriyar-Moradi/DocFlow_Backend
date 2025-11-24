"""
Mock services for testing without external dependencies
"""
import logging
import uuid
import json
from datetime import datetime
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

class MockFirestoreService:
    """Mock Firestore service"""
    
    def __init__(self):
        self.documents = {}
        self.jobs = {}
        logger.info("Initialized Mock Firestore Service")
        
    def create_document(self, document_id: str, data: Dict[str, Any]) -> str:
        data['created_at'] = datetime.now()
        data['updated_at'] = datetime.now()
        self.documents[document_id] = data
        return document_id
        
    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        doc = self.documents.get(document_id)
        if doc:
            # Return a copy to simulate fetching
            ret = doc.copy()
            ret['document_id'] = document_id
            return ret
        return None
        
    def update_document(self, document_id: str, data: Dict[str, Any]) -> bool:
        if document_id in self.documents:
            self.documents[document_id].update(data)
            self.documents[document_id]['updated_at'] = datetime.now()
            return True
        return False
        
    def list_documents(self, page: int = 1, page_size: int = 20, filters: Optional[Dict[str, Any]] = None) -> tuple[List[Dict[str, Any]], int]:
        docs = list(self.documents.values())
        # Add IDs
        for i, doc_id in enumerate(self.documents.keys()):
            docs[i]['document_id'] = doc_id
            
        # Sort by created_at desc
        docs.sort(key=lambda x: x.get('created_at', datetime.min), reverse=True)
        
        total = len(docs)
        start = (page - 1) * page_size
        end = start + page_size
        
        return docs[start:end], total
        
    def search_documents(self, search_params: Dict[str, Any]) -> tuple[List[Dict[str, Any]], int]:
        # Simple mock search implementation
        return self.list_documents(
            page=search_params.get('page', 1),
            page_size=search_params.get('page_size', 20)
        )
        
    def create_job(self, job_id: str, data: Dict[str, Any]) -> str:
        data['created_at'] = datetime.now()
        data['updated_at'] = datetime.now()
        self.jobs[job_id] = data
        return job_id
        
    def update_job(self, job_id: str, data: Dict[str, Any]) -> bool:
        if job_id in self.jobs:
            self.jobs[job_id].update(data)
            self.jobs[job_id]['updated_at'] = datetime.now()
            return True
        return False
        
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.jobs.get(job_id)
        
    def update_job_progress(self, job_id: str, processed: int = 0, failed: int = 0, status: Optional[str] = None) -> bool:
        if job_id in self.jobs:
            job = self.jobs[job_id]
            job['processed_documents'] = job.get('processed_documents', 0) + processed
            job['failed_documents'] = job.get('failed_documents', 0) + failed
            if status:
                job['status'] = status
            job['updated_at'] = datetime.now()
            return True
        return False


class MockGCSVoucherService:
    """Mock GCS Service"""
    
    def __init__(self):
        self.bucket_name = "mock-bucket"
        self.files = {}
        self.bucket = self # Mock bucket object
        logger.info("Initialized Mock GCS Service")
        
    def upload_file_from_bytes(self, file_bytes: bytes, gcs_path: str, **kwargs) -> Dict[str, Any]:
        self.files[gcs_path] = file_bytes
        return {
            'success': True,
            'gcs_path': f"gs://{self.bucket_name}/{gcs_path}",
            'file_size': len(file_bytes)
        }
        
    def get_file_download_url(self, gcs_path: str, **kwargs) -> str:
        return f"http://mock-storage/{gcs_path}"
        
    def blob(self, path):
        return MockBlob(path, self)

class MockBlob:
    def __init__(self, name, service):
        self.name = name
        self.service = service
        
    def download_to_filename(self, filename):
        # Create dummy file
        with open(filename, 'wb') as f:
            f.write(self.service.files.get(self.name, b'mock content'))
            
    def upload_from_file(self, file_obj, **kwargs):
        self.service.files[self.name] = file_obj.read()
        
    def delete(self):
        if self.name in self.service.files:
            del self.service.files[self.name]
            
    def exists(self):
        return self.name in self.service.files
        
    def generate_signed_url(self, **kwargs):
        return f"http://mock-storage/{self.name}"
        
    @property
    def metadata(self):
        return {}
        
    @metadata.setter
    def metadata(self, value):
        pass
        
    def patch(self):
        pass

