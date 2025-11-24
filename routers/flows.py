"""
Flow API endpoints
"""
import logging
import uuid
import sys
from datetime import datetime
from typing import Optional
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

sys.path.append(str(Path(__file__).parent.parent))

from config import settings
from models.schemas import (
    FlowResponse,
    FlowListResponse,
    FlowCreateRequest,
    DocumentListResponse,
    DocumentResponse
)
from services.firestore_service import FirestoreService
from services.mocks import MockFirestoreService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/flows", tags=["flows"])

# Initialize services
firestore_service = None

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


@router.post("", response_model=FlowResponse)
async def create_flow(flow_request: FlowCreateRequest):
    """
    Create a new flow
    """
    try:
        flow_id = str(uuid.uuid4())
        
        # Create flow record
        safe_firestore_operation(
            get_firestore_service().create_flow,
            flow_id,
            {
                'flow_name': flow_request.flow_name,
                'document_count': 0
            }
        )
        
        # Get the created flow to return
        flow = get_firestore_service().get_flow(flow_id)
        if not flow:
            raise HTTPException(status_code=500, detail="Failed to create flow")
        
        return FlowResponse(
            flow_id=flow.get('flow_id'),
            flow_name=flow.get('flow_name', ''),
            created_at=flow.get('created_at', datetime.now()),
            document_count=flow.get('document_count', 0)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating flow: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("", response_model=FlowListResponse)
async def list_flows(
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):
    """
    List flows with pagination
    """
    try:
        flows, total = get_firestore_service().list_flows(
            page=page,
            page_size=page_size
        )
        
        # Convert to response format
        flow_responses = []
        for flow in flows:
            flow_responses.append(FlowResponse(
                flow_id=flow.get('flow_id'),
                flow_name=flow.get('flow_name', ''),
                created_at=flow.get('created_at', datetime.now()),
                document_count=flow.get('document_count', 0)
            ))
        
        return FlowListResponse(
            flows=flow_responses,
            total=total,
            page=page,
            page_size=page_size,
            has_next=(page * page_size) < total,
            has_previous=page > 1
        )
        
    except Exception as e:
        logger.error(f"Error listing flows: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{flow_id}", response_model=FlowResponse)
async def get_flow(flow_id: str):
    """
    Get flow details by ID
    """
    try:
        flow = get_firestore_service().get_flow(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        
        return FlowResponse(
            flow_id=flow.get('flow_id'),
            flow_name=flow.get('flow_name', ''),
            created_at=flow.get('created_at', datetime.now()),
            document_count=flow.get('document_count', 0)
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting flow: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{flow_id}/documents", response_model=DocumentListResponse)
async def get_flow_documents(
    flow_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100)
):
    """
    Get documents for a specific flow
    """
    try:
        # Verify flow exists
        flow = get_firestore_service().get_flow(flow_id)
        if not flow:
            raise HTTPException(status_code=404, detail="Flow not found")
        
        # Get documents for this flow
        documents, total = get_firestore_service().get_documents_by_flow_id(
            flow_id=flow_id,
            page=page,
            page_size=page_size
        )
        
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
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting flow documents: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

