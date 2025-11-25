"""
Document API endpoints
"""
import logging
import uuid
import sys
import os
import json
import re
import tempfile
from datetime import datetime
from typing import List, Optional
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException, BackgroundTasks, Query, Depends
from fastapi.responses import StreamingResponse

sys.path.append(str(Path(__file__).parent.parent))

from config import settings
from models.schemas import (
    DocumentUploadResponse,
    BatchUploadResponse,
    DocumentResponse,
    DocumentListResponse,
    DocumentSearchRequest,
    JobStatusResponse,
    ErrorResponse,
    CategoryStatsResponse,
    CategoryStatsListResponse
)
from services.firestore_service import FirestoreService
from services.task_queue import TaskQueue
from services.document_processor import DocumentProcessor
from services.category_mapper import map_backend_to_ui_category, get_all_ui_categories, is_valid_ui_category
from gcs_service import GCSVoucherService
from services.mocks import MockFirestoreService, MockGCSVoucherService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Initialize services (lazy initialization in TaskQueue)
firestore_service = None
task_queue = TaskQueue()
gcs_service = None

def get_firestore_service():
    """Get or create firestore service"""
    global firestore_service
    if firestore_service is None:
        if settings.USE_MOCK_SERVICES:
            logger.info("Using Mock Firestore Service")
            firestore_service = MockFirestoreService()
        else:
            try:
                firestore_service = FirestoreService()
            except Exception as e:
                logger.warning(f"Failed to initialize Firestore, falling back to mock: {e}")
                firestore_service = MockFirestoreService()
    return firestore_service

def safe_firestore_operation(operation, *args, **kwargs):
    """Safely execute Firestore operation, return None if it fails"""
    try:
        return operation(*args, **kwargs)
    except Exception as e:
        logger.warning(f"Firestore operation failed (non-critical): {e}")
        return None

def get_gcs_service():
    """Get or create GCS service"""
    global gcs_service
    if gcs_service is None:
        if settings.USE_MOCK_SERVICES:
            logger.info("Using Mock GCS Service")
            gcs_service = MockGCSVoucherService()
        else:
            try:
                gcs_service = GCSVoucherService()
            except Exception as e:
                logger.warning(f"Failed to initialize GCS, falling back to mock: {e}")
                gcs_service = MockGCSVoucherService()
    return gcs_service


def validate_file_extension(filename: str) -> bool:
    """Validate file extension"""
    ext = Path(filename).suffix.lower()
    return ext in settings.ALLOWED_EXTENSIONS


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    flow_id: Optional[str] = Form(None)
):
    """
    Upload a single document for processing
    """
    try:
        # Validate file extension
        if not validate_file_extension(file.filename):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid file type. Allowed: {', '.join(settings.ALLOWED_EXTENSIONS)}"
            )
        
        # Read file content
        file_content = await file.read()
        
        # Check file size
        if len(file_content) > settings.MAX_UPLOAD_SIZE:
            raise HTTPException(
                status_code=400,
                detail=f"File too large. Maximum size: {settings.MAX_UPLOAD_SIZE / 1024 / 1024}MB"
            )
        
        # Generate document ID
        document_id = str(uuid.uuid4())
        
        # Upload to GCS temp folder
        gcs_temp_path = f"{settings.TEMP_UPLOAD_FOLDER}/{document_id}/{file.filename}"
        
        # Determine content type
        content_type = file.content_type or 'application/octet-stream'
        if Path(file.filename).suffix.lower() == '.pdf':
            content_type = 'application/pdf'
        elif Path(file.filename).suffix.lower() in ['.jpg', '.jpeg']:
            content_type = 'image/jpeg'
        elif Path(file.filename).suffix.lower() == '.png':
            content_type = 'image/png'
        
        upload_result = get_gcs_service().upload_file_from_bytes(
            file_content,
            gcs_temp_path,
            content_type=content_type
        )
        
        if not upload_result.get('success'):
            raise HTTPException(
                status_code=500,
                detail=f"Failed to upload file to storage: {upload_result.get('error')}"
            )
        
        # Quick processing: Classify and extract data immediately
        document_type = None
        classification_confidence = None
        extracted_data = {}
        document_number = None
        document_date = None
        total_amount = None
        currency = None
        
        try:
            logger.info("Performing quick classification and extraction...")
            
            # Save file temporarily for processing
            temp_file = tempfile.NamedTemporaryFile(
                delete=False,
                suffix=Path(file.filename).suffix
            )
            temp_file_path = temp_file.name
            temp_file.write(file_content)
            temp_file.close()
            
            try:
                # Initialize processor
                processor = DocumentProcessor()
                
                # Quick classification and extraction
                classification_result = processor._classify_document_type(temp_file_path)
                document_type = classification_result.get('document_type', 'Other')
                classification_confidence = classification_result.get('confidence', 0.0)
                
                logger.info(f"Quick classification: {document_type} (confidence: {classification_confidence:.2f})")
                
                # Quick extraction (use general extraction for all types for speed)
                if document_type.lower() == 'voucher':
                    # Use voucher-specific extraction
                    extraction_text = processor._extract_transaction_data(temp_file_path)
                else:
                    # Use general extraction
                    extraction_text = processor._extract_general_document_data(temp_file_path, document_type)
                
                # Parse extraction results
                try:
                    json_match = re.search(r'\{[^}]*\}', extraction_text, re.DOTALL)
                    if json_match:
                        extracted_data = json.loads(json_match.group())
                        
                        # Extract key fields for response
                        if document_type.lower() == 'voucher':
                            document_number = extracted_data.get('document_no', '')
                            document_date = extracted_data.get('document_date', '')
                            total_amount = extracted_data.get('invoice_amount_usd') or extracted_data.get('invoice_amount_aed', '')
                            currency = 'USD' if extracted_data.get('invoice_amount_usd') else ('AED' if extracted_data.get('invoice_amount_aed') else None)
                        else:
                            document_number = extracted_data.get('document_number') or extracted_data.get('document_id', '')
                            # Prioritize document_date, then issue_date, then other date fields
                            document_date = (
                                extracted_data.get('document_date') or 
                                extracted_data.get('issue_date') or 
                                extracted_data.get('date') or 
                                extracted_data.get('created_date') or
                                extracted_data.get('date_of_issue') or
                                ''
                            )
                            total_amount = extracted_data.get('total_amount', '')
                            currency = extracted_data.get('currency', '')
                        
                        logger.info(f"Quick extraction completed: Doc No={document_number}, Date={document_date}")
                except Exception as parse_error:
                    logger.warning(f"Failed to parse extraction JSON: {parse_error}")
                    extracted_data = {'raw_text': extraction_text[:500]}  # Store first 500 chars
                    
            finally:
                # Clean up temp file
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)
                    
        except Exception as processing_error:
            logger.warning(f"Quick processing failed (non-critical): {processing_error}")
            # Continue with upload even if quick processing fails
            document_type = 'Other'
            classification_confidence = 0.0
        
        # Map backend classification to UI category
        ui_category = map_backend_to_ui_category(document_type)
        
        # Create document record in Firestore (non-critical if it fails)
        document_data = {
            'filename': file.filename,
            'original_filename': file.filename,
            'file_type': Path(file.filename).suffix.lower(),
            'file_size': len(file_content),
            'gcs_path': upload_result.get('gcs_path'),
            'gcs_temp_path': gcs_temp_path,
            'processing_status': 'processing',  # Changed to processing since we did quick processing
            'document_type': document_type,
            'classification_confidence': classification_confidence,
            'extracted_data': extracted_data,
            'metadata': {
                'classification': document_type,
                'ui_category': ui_category,
                'document_no': document_number,
                'document_date': document_date
            },
            'created_at': datetime.now(),
            'updated_at': datetime.now()
        }
        
        # Add flow_id if provided
        if flow_id:
            document_data['flow_id'] = flow_id
        
        safe_firestore_operation(
            get_firestore_service().create_document,
            document_id,
            document_data
        )
        
        # Increment flow document count if flow_id is provided
        if flow_id:
            safe_firestore_operation(
                get_firestore_service().increment_flow_document_count,
                flow_id,
                1
            )
        
        # Add background processing task for full processing (organized path, PDF conversion, etc.)
        task_queue.add_process_task(
            background_tasks,
            document_id,
            gcs_temp_path,
            file.filename
        )
        
        return DocumentUploadResponse(
            document_id=document_id,
            status="processing",
            message="Document uploaded and processed successfully",
            uploaded_at=datetime.now(),
            document_type=document_type,
            classification_confidence=classification_confidence,
            extracted_data=extracted_data if extracted_data else None,
            document_number=document_number,
            document_date=document_date,
            total_amount=total_amount,
            currency=currency
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error uploading document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/batch", response_model=BatchUploadResponse)
async def upload_documents_batch(
    background_tasks: BackgroundTasks,
    files: List[UploadFile] = File(...),
    flow_id: Optional[str] = Form(None)
):
    """
    Upload multiple documents for batch processing
    """
    try:
        if len(files) == 0:
            raise HTTPException(status_code=400, detail="No files provided")
        
        # Generate job ID
        job_id = str(uuid.uuid4())
        
        # Create job record (non-critical if it fails)
        safe_firestore_operation(
            get_firestore_service().create_job,
            job_id,
            {
                'total_documents': len(files),
                'documents': []
            }
        )
        
        document_ids = []
        
        for file in files:
            # Validate file extension
            if not validate_file_extension(file.filename):
                logger.warning(f"Skipping invalid file: {file.filename}")
                continue
            
            # Read file content
            file_content = await file.read()
            
            # Check file size
            if len(file_content) > settings.MAX_UPLOAD_SIZE:
                logger.warning(f"Skipping large file: {file.filename}")
                continue
            
            # Generate document ID
            document_id = str(uuid.uuid4())
            document_ids.append(document_id)
            
            # Upload to GCS temp folder
            gcs_temp_path = f"{settings.TEMP_UPLOAD_FOLDER}/{job_id}/{document_id}/{file.filename}"
            
            # Determine content type
            content_type = file.content_type or 'application/octet-stream'
            if Path(file.filename).suffix.lower() == '.pdf':
                content_type = 'application/pdf'
            elif Path(file.filename).suffix.lower() in ['.jpg', '.jpeg']:
                content_type = 'image/jpeg'
            elif Path(file.filename).suffix.lower() == '.png':
                content_type = 'image/png'
            
            upload_result = get_gcs_service().upload_file_from_bytes(
                file_content,
                gcs_temp_path,
                content_type=content_type
            )
            
            if not upload_result.get('success'):
                logger.error(f"Failed to upload {file.filename}")
                continue
            
            # Create document record (non-critical if it fails)
            document_data = {
                'filename': file.filename,
                'original_filename': file.filename,
                'file_type': Path(file.filename).suffix.lower(),
                'file_size': len(file_content),
                'gcs_path': upload_result.get('gcs_path'),
                'gcs_temp_path': gcs_temp_path,
                'processing_status': 'pending',
                'job_id': job_id,
                'created_at': datetime.now(),
                'updated_at': datetime.now()
            }
            
            # Add flow_id if provided
            if flow_id:
                document_data['flow_id'] = flow_id
            
            safe_firestore_operation(
                get_firestore_service().create_document,
                document_id,
                document_data
            )
            
            # Add background processing task
            task_queue.add_process_task(
                background_tasks,
                document_id,
                gcs_temp_path,
                file.filename,
                job_id
            )
        
        # Update job with document IDs (non-critical if it fails)
        safe_firestore_operation(
            get_firestore_service().update_job,
            job_id,
            {'documents': document_ids}
        )
        
        # Increment flow document count if flow_id is provided
        if flow_id and len(document_ids) > 0:
            safe_firestore_operation(
                get_firestore_service().increment_flow_document_count,
                flow_id,
                len(document_ids)
            )
        
        return BatchUploadResponse(
            job_id=job_id,
            total_documents=len(document_ids),
            status="pending",
            message=f"Batch upload successful. {len(document_ids)} documents queued for processing",
            uploaded_at=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in batch upload: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=DocumentListResponse)
async def list_documents(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    classification: Optional[str] = None,
    ui_category: Optional[str] = None,
    branch_id: Optional[str] = None
):
    """
    List processed documents with pagination
    
    Args:
        page: Page number (starts at 1)
        page_size: Number of documents per page
        classification: Filter by backend classification
        ui_category: Filter by UI category (Contracts, Invoices, Insurance, RTA, Forms, ID / Passport, Others, Unknown)
        branch_id: Filter by branch ID
    """
    try:
        # Validate ui_category if provided
        if ui_category and not is_valid_ui_category(ui_category):
            # If invalid, try to map it (for backward compatibility)
            logger.warning(f"Invalid ui_category provided: {ui_category}, attempting to map")
            # Don't reject, just log - let the filter work if it matches
        
        filters = {}
        if classification:
            filters['classification'] = classification
        if ui_category:
            filters['ui_category'] = ui_category
        if branch_id:
            filters['branch_id'] = branch_id
        
        documents, total = get_firestore_service().list_documents(
            page=page,
            page_size=page_size,
            filters=filters
        )
        
        # Convert to response format
        document_responses = []
        for doc in documents:
            metadata = doc.get('metadata', {})
            
            # Ensure ui_category is always set (compute from classification if missing)
            ui_category = metadata.get('ui_category')
            if not ui_category:
                classification = metadata.get('classification') or doc.get('document_type') or doc.get('classification')
                ui_category = map_backend_to_ui_category(classification)
            
            document_responses.append(DocumentResponse(
                document_id=doc.get('document_id'),
                filename=doc.get('filename', ''),
                original_filename=doc.get('original_filename', ''),
                file_type=doc.get('file_type', ''),
                file_size=doc.get('file_size', 0),
                gcs_path=doc.get('gcs_path', ''),
                organized_path=doc.get('organized_path'),
                metadata={
                    'document_no': metadata.get('document_no'),
                    'document_date': metadata.get('document_date'),
                    'branch_id': metadata.get('branch_id'),
                    'classification': metadata.get('classification'),
                    'ui_category': ui_category,  # Always include computed ui_category
                    'invoice_amount_usd': metadata.get('invoice_amount_usd'),
                    'invoice_amount_aed': metadata.get('invoice_amount_aed'),
                    'gold_weight': metadata.get('gold_weight'),
                    'purity': metadata.get('purity'),
                    'discount_rate': metadata.get('discount_rate'),
                    'is_valid_voucher': metadata.get('is_valid_voucher', False),
                    'needs_attachment': metadata.get('needs_attachment', False)
                },
                processing_status=doc.get('processing_status', 'pending'),
                processing_method=doc.get('processing_method'),
                confidence=doc.get('confidence'),
                created_at=doc.get('created_at', datetime.now()),
                updated_at=doc.get('updated_at', datetime.now()),
                error=doc.get('error'),
                flow_id=doc.get('flow_id')
            ))
        
        return DocumentListResponse(
            documents=document_responses,
            total=total,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total,
            has_previous=page > 1
        )
        
    except Exception as e:
        logger.error(f"Error listing documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/search", response_model=DocumentListResponse)
async def search_documents(
    search_request: DocumentSearchRequest = Depends()
):
    """
    Search documents by various criteria
    """
    try:
        search_params = {
            'document_no': search_request.document_no,
            'classification': search_request.classification,
            'branch_id': search_request.branch_id,
            'date_from': search_request.date_from,
            'date_to': search_request.date_to,
            'min_amount_usd': search_request.min_amount_usd,
            'max_amount_usd': search_request.max_amount_usd,
            'min_amount_aed': search_request.min_amount_aed,
            'max_amount_aed': search_request.max_amount_aed,
            'page': search_request.page,
            'page_size': search_request.page_size
        }
        
        # Remove None values
        search_params = {k: v for k, v in search_params.items() if v is not None}
        
        documents, total = get_firestore_service().search_documents(search_params)
        
        # Convert to response format
        document_responses = []
        for doc in documents:
            metadata = doc.get('metadata', {})
            document_responses.append(DocumentResponse(
                document_id=doc.get('document_id'),
                filename=doc.get('filename', ''),
                original_filename=doc.get('original_filename', ''),
                file_type=doc.get('file_type', ''),
                file_size=doc.get('file_size', 0),
                gcs_path=doc.get('gcs_path', ''),
                organized_path=doc.get('organized_path'),
                metadata={
                    'document_no': metadata.get('document_no'),
                    'document_date': metadata.get('document_date'),
                    'branch_id': metadata.get('branch_id'),
                    'classification': metadata.get('classification'),
                    'ui_category': metadata.get('ui_category'),
                    'invoice_amount_usd': metadata.get('invoice_amount_usd'),
                    'invoice_amount_aed': metadata.get('invoice_amount_aed'),
                    'gold_weight': metadata.get('gold_weight'),
                    'purity': metadata.get('purity'),
                    'discount_rate': metadata.get('discount_rate'),
                    'is_valid_voucher': metadata.get('is_valid_voucher', False),
                    'needs_attachment': metadata.get('needs_attachment', False)
                },
                processing_status=doc.get('processing_status', 'pending'),
                processing_method=doc.get('processing_method'),
                confidence=doc.get('confidence'),
                created_at=doc.get('created_at', datetime.now()),
                updated_at=doc.get('updated_at', datetime.now()),
                error=doc.get('error'),
                flow_id=doc.get('flow_id')
            ))
        
        return DocumentListResponse(
            documents=document_responses,
            total=total,
            page=search_request.page,
            page_size=search_request.page_size,
            has_next=(search_request.page * search_request.page_size) < total,
            has_previous=search_request.page > 1
        )
        
    except Exception as e:
        logger.error(f"Error searching documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}", response_model=DocumentResponse)
async def get_document(document_id: str):
    """
    Get document details by ID
    """
    try:
        doc = get_firestore_service().get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        metadata = doc.get('metadata', {})
        return DocumentResponse(
            document_id=doc.get('document_id'),
            filename=doc.get('filename', ''),
            original_filename=doc.get('original_filename', ''),
            file_type=doc.get('file_type', ''),
            file_size=doc.get('file_size', 0),
            gcs_path=doc.get('gcs_path', ''),
            organized_path=doc.get('organized_path'),
            metadata={
                'document_no': metadata.get('document_no'),
                'document_date': metadata.get('document_date'),
                'branch_id': metadata.get('branch_id'),
                'classification': metadata.get('classification'),
                'invoice_amount_usd': metadata.get('invoice_amount_usd'),
                'invoice_amount_aed': metadata.get('invoice_amount_aed'),
                'gold_weight': metadata.get('gold_weight'),
                'purity': metadata.get('purity'),
                'discount_rate': metadata.get('discount_rate'),
                'is_valid_voucher': metadata.get('is_valid_voucher', False),
                'needs_attachment': metadata.get('needs_attachment', False)
            },
            processing_status=doc.get('processing_status', 'pending'),
            processing_method=doc.get('processing_method'),
            confidence=doc.get('confidence'),
            created_at=doc.get('created_at', datetime.now()),
            updated_at=doc.get('updated_at', datetime.now()),
            error=doc.get('error')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{document_id}/download")
async def download_document(document_id: str):
    """
    Download a processed document
    """
    try:
        doc = get_firestore_service().get_document(document_id)
        if not doc:
            raise HTTPException(status_code=404, detail="Document not found")
        
        gcs_path = doc.get('gcs_path')
        if not gcs_path:
            raise HTTPException(status_code=404, detail="Document file not found")
        
        # Extract blob name from gs:// path
        if gcs_path.startswith('gs://'):
            blob_name = gcs_path.split('/', 3)[3]
        else:
            blob_name = gcs_path
        
        # Get blob
        blob = get_gcs_service().bucket.blob(blob_name)
        
        if not blob.exists():
            raise HTTPException(status_code=404, detail="File not found in storage")
        
        # Generate signed URL for download
        download_url = get_gcs_service().get_file_download_url(blob_name)
        
        # Return redirect to signed URL
        from fastapi.responses import RedirectResponse
        return RedirectResponse(url=download_url)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error downloading document: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/jobs/{job_id}/status", response_model=JobStatusResponse)
async def get_job_status(job_id: str):
    """
    Get batch processing job status
    """
    try:
        job = get_firestore_service().get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        
        return JobStatusResponse(
            job_id=job.get('job_id'),
            status=job.get('status', 'pending'),
            total_documents=job.get('total_documents', 0),
            processed_documents=job.get('processed_documents', 0),
            failed_documents=job.get('failed_documents', 0),
            created_at=job.get('created_at', datetime.now()),
            updated_at=job.get('updated_at', datetime.now()),
            completed_at=job.get('completed_at'),
            error=job.get('error'),
            results=job.get('results')
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting job status: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/categories/stats", response_model=CategoryStatsListResponse)
async def get_category_statistics():
    """
    Get document count statistics by UI category
    """
    try:
        stats = get_firestore_service().get_category_statistics()
        total = stats.pop('total', 0)
        
        # Get all UI categories and create response
        all_categories = get_all_ui_categories()
        category_responses = []
        
        for category in all_categories:
            if category == 'All':
                continue  # Skip 'All' as it's not a real category
            count = stats.get(category, 0)
            category_responses.append(CategoryStatsResponse(
                category=category,
                count=count
            ))
        
        return CategoryStatsListResponse(
            categories=category_responses,
            total_documents=total
        )
        
    except Exception as e:
        logger.error(f"Error getting category statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

