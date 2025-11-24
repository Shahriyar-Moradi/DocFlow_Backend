"""
Background task processing for document OCR
"""
import logging
import tempfile
import os
import re
import sys
from typing import Dict, Any, Optional
from pathlib import Path

from fastapi import BackgroundTasks

sys.path.append(str(Path(__file__).parent.parent))

from config import settings
from services.document_processor import DocumentProcessor
from services.firestore_service import FirestoreService
from gcs_service import GCSVoucherService
from services.mocks import MockFirestoreService, MockGCSVoucherService

logger = logging.getLogger(__name__)

class TaskQueue:
    """Background task processing service"""
    
    def __init__(self):
        """Initialize task queue services"""
        self._document_processor = None
        self._firestore_service = None
        self._gcs_service = None
    
    @property
    def document_processor(self):
        """Lazy initialization of document processor"""
        if self._document_processor is None:
            self._document_processor = DocumentProcessor()
        return self._document_processor
    
    @property
    def firestore_service(self):
        """Lazy initialization of firestore service"""
        if self._firestore_service is None:
            if settings.USE_MOCK_SERVICES:
                self._firestore_service = MockFirestoreService()
            else:
                try:
                    self._firestore_service = FirestoreService()
                except Exception:
                    self._firestore_service = MockFirestoreService()
        return self._firestore_service
    
    @property
    def gcs_service(self):
        """Lazy initialization of GCS service"""
        if self._gcs_service is None:
            if settings.USE_MOCK_SERVICES:
                self._gcs_service = MockGCSVoucherService()
            else:
                try:
                    self._gcs_service = GCSVoucherService()
                except Exception:
                    self._gcs_service = MockGCSVoucherService()
        return self._gcs_service
    
    async def process_document_task(
        self,
        document_id: str,
        gcs_temp_path: str,
        original_filename: str,
        job_id: Optional[str] = None
    ):
        """
        Background task to process a single document
        
        Args:
            document_id: Unique document ID
            gcs_temp_path: GCS path to temporary uploaded file
            original_filename: Original filename
            job_id: Optional job ID for batch processing
        """
        try:
            logger.info(f"Starting background processing for document: {document_id}")
            
            # Initialize result dictionary to avoid UnboundLocalError in finally block
            result = {}
            
            # Update status to processing
            self.firestore_service.update_document(document_id, {
                'processing_status': 'processing'
            })
            
            if job_id:
                self.firestore_service.update_job(job_id, {'status': 'processing'})
            
            # Download file from GCS temp to local temp
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(original_filename).suffix
            )
            temp_file_path = temp_file.name
            temp_file.close()
            
            try:
                # Download from GCS
                bucket = self.gcs_service.bucket
                blob = bucket.blob(gcs_temp_path)
                blob.download_to_filename(temp_file_path)
                logger.info(f"Downloaded file from GCS: {gcs_temp_path}")
                
                # Process document
                result = self.document_processor.process_document(
                    temp_file_path,
                    original_filename=original_filename
                )
                
                if result.get('success'):
                    # Upload processed file to organized location
                    organized_path = result.get('organized_path')
                    if organized_path:
                        # Determine which file to upload (PDF if converted, otherwise original)
                        file_to_upload = result.get('pdf_path', temp_file_path)
                        is_pdf = result.get('converted_to_pdf', False)
                        
                        # Generate final filename
                        if result.get('complete_filename'):
                            complete_doc_no = result['complete_filename'].strip()
                            safe_filename = re.sub(r'[<>:"/\\|?*]', '_', complete_doc_no)
                            
                            if is_pdf:
                                final_filename = f"{safe_filename}_0001.pdf"
                            else:
                                original_ext = Path(original_filename).suffix
                                final_filename = f"{safe_filename}_0001{original_ext}"
                        else:
                            filename_without_ext = Path(original_filename).stem
                            if is_pdf:
                                final_filename = f"{filename_without_ext}.pdf"
                            else:
                                original_ext = Path(original_filename).suffix
                                final_filename = f"{filename_without_ext}{original_ext}"
                        
                        organized_key = f"{organized_path}/{final_filename}"
                        
                        # Prepare metadata
                        metadata = {}
                        if result.get('document_no'):
                            metadata['document-no'] = str(result['document_no'])
                        if result.get('classification'):
                            metadata['classification'] = str(result['classification'])
                        if result.get('branch_id'):
                            metadata['branch-id'] = str(result['branch_id'])
                        if result.get('invoice_amount_usd'):
                            metadata['invoice-amount-usd'] = str(result['invoice_amount_usd'])
                        if result.get('invoice_amount_aed'):
                            metadata['invoice-amount-aed'] = str(result['invoice_amount_aed'])
                        if result.get('gold_weight'):
                            metadata['gold-weight'] = str(result['gold_weight'])
                        if result.get('purity'):
                            metadata['purity'] = str(result['purity'])
                        if result.get('document_date'):
                            metadata['document-date'] = str(result['document_date'])
                        if result.get('discount_rate'):
                            metadata['discount-rate'] = str(result['discount_rate'])
                        
                        # Upload to GCS
                        content_type = 'application/pdf' if is_pdf else 'image/jpeg'
                        blob = bucket.blob(organized_key)
                        with open(file_to_upload, 'rb') as file_data:
                            blob.upload_from_file(file_data, content_type=content_type)
                            blob.metadata = metadata
                            blob.patch()
                        
                        logger.info(f"Uploaded file to organized location: {organized_key}")
                        
                        # Update Firestore with success
                        self.firestore_service.update_document(document_id, {
                            'processing_status': 'completed',
                            'organized_path': organized_path,
                            'gcs_path': f"gs://{settings.GCS_BUCKET_NAME}/{organized_key}",
                            'metadata': {
                                'document_no': result.get('document_no'),
                                'document_date': result.get('document_date'),
                                'branch_id': result.get('branch_id'),
                                'classification': result.get('classification'),
                                'invoice_amount_usd': result.get('invoice_amount_usd'),
                                'invoice_amount_aed': result.get('invoice_amount_aed'),
                                'gold_weight': result.get('gold_weight'),
                                'purity': result.get('purity'),
                                'discount_rate': result.get('discount_rate'),
                                'is_valid_voucher': result.get('is_valid_voucher', False),
                                'needs_attachment': result.get('needs_attachment', False)
                            },
                            'processing_method': result.get('method'),
                            'confidence': result.get('confidence')
                        })
                    else:
                        # UNKNOWN classification - mark as failed
                        logger.warning(f"UNKNOWN classification for document {document_id}")
                        self.firestore_service.update_document(document_id, {
                            'processing_status': 'failed',
                            'error': 'Document classified as UNKNOWN - unable to determine document type'
                        })
                else:
                    # Processing failed
                    error_msg = result.get('error', 'Unknown error during processing')
                    logger.error(f"Processing failed for document {document_id}: {error_msg}")
                    self.firestore_service.update_document(document_id, {
                        'processing_status': 'failed',
                        'error': error_msg
                    })
                
                # Update job progress if batch job
                if job_id:
                    if result.get('success'):
                        self.firestore_service.update_job_progress(job_id, processed=1)
                    else:
                        self.firestore_service.update_job_progress(job_id, failed=1)
                
                # Delete temp file from GCS
                try:
                    blob = bucket.blob(gcs_temp_path)
                    blob.delete()
                    logger.info(f"Deleted temp file from GCS: {gcs_temp_path}")
                except Exception as e:
                    logger.warning(f"Failed to delete temp file from GCS: {e}")
                
            finally:
                # Clean up local temp file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    logger.info(f"Cleaned up local temp file: {temp_file_path}")
                
                # Clean up PDF if converted
                if result.get('pdf_path') and result.get('pdf_path') != temp_file_path:
                    pdf_path = result.get('pdf_path')
                    if os.path.exists(pdf_path):
                        os.unlink(pdf_path)
                        logger.info(f"Cleaned up converted PDF: {pdf_path}")
            
            logger.info(f"Completed background processing for document: {document_id}")
            
        except Exception as e:
            logger.error(f"Error in background task for document {document_id}: {str(e)}")
            self.firestore_service.update_document(document_id, {
                'processing_status': 'failed',
                'error': str(e)
            })
            
            if job_id:
                self.firestore_service.update_job_progress(job_id, failed=1)
    
    def add_process_task(
        self,
        background_tasks: BackgroundTasks,
        document_id: str,
        gcs_temp_path: str,
        original_filename: str,
        job_id: Optional[str] = None
    ):
        """Add a document processing task to background tasks"""
        background_tasks.add_task(
            self.process_document_task,
            document_id,
            gcs_temp_path,
            original_filename,
            job_id
        )

