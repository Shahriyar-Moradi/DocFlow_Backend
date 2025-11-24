"""
Firestore service for storing document metadata and job status
"""
import logging
from datetime import datetime
from typing import Optional, List, Dict, Any
from google.cloud import firestore
from google.cloud.firestore import Query

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from config import settings

logger = logging.getLogger(__name__)

class FirestoreService:
    """Service for interacting with Firestore database"""
    
    def __init__(self):
        """Initialize Firestore client"""
        try:
            self.db = firestore.Client(project=settings.FIRESTORE_PROJECT_ID)
            self.documents_collection = self.db.collection(settings.FIRESTORE_COLLECTION_DOCUMENTS)
            self.jobs_collection = self.db.collection(settings.FIRESTORE_COLLECTION_JOBS)
            self.flows_collection = self.db.collection(settings.FIRESTORE_COLLECTION_FLOWS)
            logger.info(f"Firestore client initialized for project: {settings.FIRESTORE_PROJECT_ID}")
        except Exception as e:
            logger.error(f"Failed to initialize Firestore client: {e}")
            raise
    
    # Document Operations
    
    def create_document(self, document_id: str, data: Dict[str, Any]) -> str:
        """Create a new document record"""
        try:
            doc_ref = self.documents_collection.document(document_id)
            data['created_at'] = firestore.SERVER_TIMESTAMP
            data['updated_at'] = firestore.SERVER_TIMESTAMP
            doc_ref.set(data)
            logger.info(f"Created document record: {document_id}")
            return document_id
        except Exception as e:
            logger.error(f"Failed to create document record: {e}")
            raise
    
    def get_document(self, document_id: str) -> Optional[Dict[str, Any]]:
        """Get a document by ID"""
        try:
            doc_ref = self.documents_collection.document(document_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                data['document_id'] = doc.id
                return data
            return None
        except Exception as e:
            logger.error(f"Failed to get document: {e}")
            return None
    
    def update_document(self, document_id: str, data: Dict[str, Any]) -> bool:
        """Update a document record"""
        try:
            doc_ref = self.documents_collection.document(document_id)
            data['updated_at'] = firestore.SERVER_TIMESTAMP
            doc_ref.update(data)
            logger.info(f"Updated document record: {document_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update document record: {e}")
            return False
    
    def list_documents(
        self,
        page: int = 1,
        page_size: int = 20,
        filters: Optional[Dict[str, Any]] = None
    ) -> tuple[List[Dict[str, Any]], int]:
        """List documents with pagination and optional filters"""
        try:
            query = self.documents_collection
            
            # Apply filters
            if filters:
                if filters.get('classification'):
                    query = query.where('metadata.classification', '==', filters['classification'])
                if filters.get('ui_category'):
                    query = query.where('metadata.ui_category', '==', filters['ui_category'])
                if filters.get('branch_id'):
                    query = query.where('metadata.branch_id', '==', filters['branch_id'])
                if filters.get('date_from'):
                    query = query.where('metadata.document_date', '>=', filters['date_from'])
                if filters.get('date_to'):
                    query = query.where('metadata.document_date', '<=', filters['date_to'])
                if filters.get('flow_id'):
                    query = query.where('flow_id', '==', filters['flow_id'])
            
            # Order by created_at descending
            query = query.order_by('created_at', direction=Query.DESCENDING)
            
            # Get total count (before pagination)
            total = len(list(query.stream()))
            
            # Apply pagination
            offset = (page - 1) * page_size
            docs = query.offset(offset).limit(page_size).stream()
            
            documents = []
            for doc in docs:
                data = doc.to_dict()
                data['document_id'] = doc.id
                documents.append(data)
            
            return documents, total
        except Exception as e:
            logger.error(f"Failed to list documents: {e}")
            return [], 0
    
    def search_documents(self, search_params: Dict[str, Any]) -> tuple[List[Dict[str, Any]], int]:
        """Search documents by various criteria"""
        try:
            query = self.documents_collection
            
            # Apply search filters
            if search_params.get('document_no'):
                query = query.where('metadata.document_no', '==', search_params['document_no'])
            if search_params.get('classification'):
                query = query.where('metadata.classification', '==', search_params['classification'])
            if search_params.get('branch_id'):
                query = query.where('metadata.branch_id', '==', search_params['branch_id'])
            if search_params.get('date_from'):
                query = query.where('metadata.document_date', '>=', search_params['date_from'])
            if search_params.get('date_to'):
                query = query.where('metadata.document_date', '<=', search_params['date_to'])
            if search_params.get('min_amount_usd'):
                query = query.where('metadata.invoice_amount_usd', '>=', str(search_params['min_amount_usd']))
            if search_params.get('max_amount_usd'):
                query = query.where('metadata.invoice_amount_usd', '<=', str(search_params['max_amount_usd']))
            
            # Order by created_at descending
            query = query.order_by('created_at', direction=Query.DESCENDING)
            
            # Get total count
            total = len(list(query.stream()))
            
            # Apply pagination
            page = search_params.get('page', 1)
            page_size = search_params.get('page_size', 20)
            offset = (page - 1) * page_size
            docs = query.offset(offset).limit(page_size).stream()
            
            documents = []
            for doc in docs:
                data = doc.to_dict()
                data['document_id'] = doc.id
                documents.append(data)
            
            return documents, total
        except Exception as e:
            logger.error(f"Failed to search documents: {e}")
            return [], 0
    
    def delete_document(self, document_id: str) -> bool:
        """Delete a document record"""
        try:
            doc_ref = self.documents_collection.document(document_id)
            doc_ref.delete()
            logger.info(f"Deleted document record: {document_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to delete document record: {e}")
            return False
    
    # Job Operations
    
    def create_job(self, job_id: str, data: Dict[str, Any]) -> str:
        """Create a new processing job"""
        try:
            doc_ref = self.jobs_collection.document(job_id)
            data['status'] = 'pending'
            data['created_at'] = firestore.SERVER_TIMESTAMP
            data['updated_at'] = firestore.SERVER_TIMESTAMP
            data['processed_documents'] = 0
            data['failed_documents'] = 0
            doc_ref.set(data)
            logger.info(f"Created job record: {job_id}")
            return job_id
        except Exception as e:
            logger.error(f"Failed to create job record: {e}")
            raise
    
    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get a job by ID"""
        try:
            doc_ref = self.jobs_collection.document(job_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                data['job_id'] = doc.id
                return data
            return None
        except Exception as e:
            logger.error(f"Failed to get job: {e}")
            return None
    
    def update_job(self, job_id: str, data: Dict[str, Any]) -> bool:
        """Update a job record"""
        try:
            doc_ref = self.jobs_collection.document(job_id)
            data['updated_at'] = firestore.SERVER_TIMESTAMP
            doc_ref.update(data)
            logger.info(f"Updated job record: {job_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update job record: {e}")
            return False
    
    def update_job_progress(self, job_id: str, processed: int = 0, failed: int = 0, status: Optional[str] = None) -> bool:
        """Update job progress"""
        try:
            doc_ref = self.jobs_collection.document(job_id)
            update_data = {'updated_at': firestore.SERVER_TIMESTAMP}
            
            if processed > 0:
                doc = doc_ref.get()
                if doc.exists:
                    current_data = doc.to_dict()
                    current_processed = current_data.get('processed_documents', 0)
                    update_data['processed_documents'] = current_processed + processed
            
            if failed > 0:
                doc = doc_ref.get()
                if doc.exists:
                    current_data = doc.to_dict()
                    current_failed = current_data.get('failed_documents', 0)
                    update_data['failed_documents'] = current_failed + failed
            
            if status:
                update_data['status'] = status
                if status == 'completed' or status == 'failed':
                    update_data['completed_at'] = firestore.SERVER_TIMESTAMP
            
            doc_ref.update(update_data)
            return True
        except Exception as e:
            logger.error(f"Failed to update job progress: {e}")
            return False
    
    # Flow Operations
    
    def create_flow(self, flow_id: str, data: Dict[str, Any]) -> str:
        """Create a new flow"""
        try:
            doc_ref = self.flows_collection.document(flow_id)
            data['created_at'] = firestore.SERVER_TIMESTAMP
            data['updated_at'] = firestore.SERVER_TIMESTAMP
            data['document_count'] = 0
            doc_ref.set(data)
            logger.info(f"Created flow record: {flow_id}")
            return flow_id
        except Exception as e:
            logger.error(f"Failed to create flow record: {e}")
            raise
    
    def get_flow(self, flow_id: str) -> Optional[Dict[str, Any]]:
        """Get a flow by ID"""
        try:
            doc_ref = self.flows_collection.document(flow_id)
            doc = doc_ref.get()
            if doc.exists:
                data = doc.to_dict()
                data['flow_id'] = doc.id
                return data
            return None
        except Exception as e:
            logger.error(f"Failed to get flow: {e}")
            return None
    
    def list_flows(
        self,
        page: int = 1,
        page_size: int = 20
    ) -> tuple[List[Dict[str, Any]], int]:
        """List flows with pagination"""
        try:
            query = self.flows_collection
            
            # Order by created_at descending
            query = query.order_by('created_at', direction=Query.DESCENDING)
            
            # Get total count (before pagination)
            total = len(list(query.stream()))
            
            # Apply pagination
            offset = (page - 1) * page_size
            docs = query.offset(offset).limit(page_size).stream()
            
            flows = []
            for doc in docs:
                data = doc.to_dict()
                data['flow_id'] = doc.id
                flows.append(data)
            
            return flows, total
        except Exception as e:
            logger.error(f"Failed to list flows: {e}")
            return [], 0
    
    def update_flow(self, flow_id: str, data: Dict[str, Any]) -> bool:
        """Update a flow record"""
        try:
            doc_ref = self.flows_collection.document(flow_id)
            data['updated_at'] = firestore.SERVER_TIMESTAMP
            doc_ref.update(data)
            logger.info(f"Updated flow record: {flow_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to update flow record: {e}")
            return False
    
    def increment_flow_document_count(self, flow_id: str, increment: int = 1) -> bool:
        """Increment the document count for a flow"""
        try:
            doc_ref = self.flows_collection.document(flow_id)
            doc = doc_ref.get()
            if doc.exists:
                current_data = doc.to_dict()
                current_count = current_data.get('document_count', 0)
                doc_ref.update({
                    'document_count': current_count + increment,
                    'updated_at': firestore.SERVER_TIMESTAMP
                })
                logger.info(f"Incremented document count for flow {flow_id} by {increment}")
                return True
            else:
                logger.warning(f"Flow {flow_id} not found for document count increment")
                return False
        except Exception as e:
            logger.error(f"Failed to increment flow document count: {e}")
            return False
    
    def get_documents_by_flow_id(
        self,
        flow_id: str,
        page: int = 1,
        page_size: int = 20
    ) -> tuple[List[Dict[str, Any]], int]:
        """Get documents by flow_id with pagination"""
        try:
            # Try with index-based query first (requires composite index)
            try:
                query = self.documents_collection.where('flow_id', '==', flow_id)
                query = query.order_by('created_at', direction=Query.DESCENDING)
                
                # Get total count (before pagination)
                all_docs = list(query.stream())
                total = len(all_docs)
                
                # Apply pagination in memory since we already fetched for count
                offset = (page - 1) * page_size
                paginated_docs = all_docs[offset:offset + page_size]
                
                documents = []
                for doc in paginated_docs:
                    data = doc.to_dict()
                    data['document_id'] = doc.id
                    documents.append(data)
                
                return documents, total
                
            except Exception as index_error:
                # If index doesn't exist, fall back to client-side sorting
                if "index" in str(index_error).lower():
                    logger.warning(f"Composite index not available, using client-side sorting. Create index at Firebase Console for better performance.")
                    logger.info("Falling back to client-side sorting...")
                    
                    # Fetch all documents with flow_id (no ordering)
                    query = self.documents_collection.where('flow_id', '==', flow_id)
                    docs = list(query.stream())
                    
                    # Convert to list with data
                    all_documents = []
                    for doc in docs:
                        data = doc.to_dict()
                        data['document_id'] = doc.id
                        all_documents.append(data)
                    
                    # Sort by created_at in memory
                    all_documents.sort(
                        key=lambda x: x.get('created_at', datetime.min),
                        reverse=True
                    )
                    
                    total = len(all_documents)
                    
                    # Apply pagination
                    offset = (page - 1) * page_size
                    documents = all_documents[offset:offset + page_size]
                    
                    return documents, total
                else:
                    raise
                    
        except Exception as e:
            logger.error(f"Failed to get documents by flow_id: {e}")
            return [], 0
    
    def get_category_statistics(self) -> Dict[str, int]:
        """Get document count by UI category"""
        try:
            # Get all documents
            docs = self.documents_collection.stream()
            
            category_counts: Dict[str, int] = {}
            total = 0
            
            for doc in docs:
                total += 1
                data = doc.to_dict()
                metadata = data.get('metadata', {})
                ui_category = metadata.get('ui_category', 'Unknown')
                category_counts[ui_category] = category_counts.get(ui_category, 0) + 1
            
            # Ensure all categories are present (even with 0 count)
            category_counts['total'] = total
            return category_counts
        except Exception as e:
            logger.error(f"Failed to get category statistics: {e}")
            return {'total': 0}

