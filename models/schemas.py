"""
Pydantic models for request/response validation
"""
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field


class DocumentUploadResponse(BaseModel):
    """Response after document upload"""
    document_id: str
    job_id: Optional[str] = None
    status: str
    message: str
    uploaded_at: datetime
    # Immediate processing results
    document_type: Optional[str] = None
    classification_confidence: Optional[float] = None
    extracted_data: Optional[Dict[str, Any]] = None
    document_number: Optional[str] = None
    document_date: Optional[str] = None
    total_amount: Optional[str] = None
    currency: Optional[str] = None


class BatchUploadResponse(BaseModel):
    """Response after batch document upload"""
    job_id: str
    total_documents: int
    status: str
    message: str
    uploaded_at: datetime


class DocumentMetadata(BaseModel):
    """Document metadata extracted from OCR"""
    document_no: Optional[str] = None
    document_date: Optional[str] = None
    branch_id: Optional[str] = None
    classification: Optional[str] = None
    invoice_amount_usd: Optional[str] = None
    invoice_amount_aed: Optional[str] = None
    gold_weight: Optional[str] = None
    purity: Optional[str] = None
    discount_rate: Optional[str] = None
    is_valid_voucher: bool = False
    needs_attachment: bool = False


class DocumentResponse(BaseModel):
    """Complete document response"""
    document_id: str
    filename: str
    original_filename: str
    file_type: str
    file_size: int
    gcs_path: str
    organized_path: Optional[str] = None
    metadata: DocumentMetadata
    processing_status: str
    processing_method: Optional[str] = None
    confidence: Optional[float] = None
    created_at: datetime
    updated_at: datetime
    error: Optional[str] = None
    flow_id: Optional[str] = None


class DocumentListResponse(BaseModel):
    """Paginated document list response"""
    documents: List[DocumentResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool


class JobStatusResponse(BaseModel):
    """Processing job status response"""
    job_id: str
    status: str  # pending, processing, completed, failed
    total_documents: int
    processed_documents: int
    failed_documents: int
    created_at: datetime
    updated_at: datetime
    completed_at: Optional[datetime] = None
    error: Optional[str] = None
    results: Optional[List[Dict[str, Any]]] = None


class DocumentSearchRequest(BaseModel):
    """Document search request"""
    document_no: Optional[str] = None
    classification: Optional[str] = None
    branch_id: Optional[str] = None
    date_from: Optional[datetime] = None
    date_to: Optional[datetime] = None
    min_amount_usd: Optional[float] = None
    max_amount_usd: Optional[float] = None
    min_amount_aed: Optional[float] = None
    max_amount_aed: Optional[float] = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)


class ErrorResponse(BaseModel):
    """Error response model"""
    error: str
    detail: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.now)


class HealthResponse(BaseModel):
    """Health check response"""
    status: str
    version: str
    timestamp: datetime = Field(default_factory=datetime.now)
    services: Dict[str, bool]


class FlowCreateRequest(BaseModel):
    """Request to create a new flow"""
    flow_name: str = Field(..., min_length=1, max_length=200)


class FlowResponse(BaseModel):
    """Flow response model"""
    flow_id: str
    flow_name: str
    created_at: datetime
    document_count: int = 0


class FlowListResponse(BaseModel):
    """Paginated flow list response"""
    flows: List[FlowResponse]
    total: int
    page: int
    page_size: int
    has_next: bool
    has_previous: bool

