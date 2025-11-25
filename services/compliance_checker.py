"""
Compliance checking service for documents
Uses AI to analyze documents and identify missing required fields, signatures, and attachments
"""
import os
import base64
import json
import re
import tempfile
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List
from pathlib import Path

from anthropic import Anthropic

import sys
sys.path.append(str(Path(__file__).parent.parent))

from config import settings
from services.document_processor import DocumentProcessor
from .anthropic_utils import detect_model_not_found_error
from .json_utils import extract_json_from_text

logger = logging.getLogger(__name__)


class ComplianceChecker:
    """Service for checking document compliance using AI"""
    
    def __init__(self):
        """Initialize the Compliance Checker"""
        logger.info("Initializing Compliance Checker...")
        
        # Initialize Anthropic client
        if not settings.anthropic_api_key_configured:
            raise ValueError("ANTHROPIC_API_KEY is required for compliance checking")
        
        try:
            self.anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = settings.ANTHROPIC_MODEL
            logger.info(f"Compliance checker initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            raise
        
        # Reuse document processor for encoding images
        self.document_processor = DocumentProcessor()
    
    def _get_required_fields_for_type(self, document_type: str) -> Dict[str, List[str]]:
        """
        Get required fields, signatures, and attachments for a document type
        
        Returns:
            Dict with 'fields', 'signatures', and 'attachments' lists
        """
        document_type_lower = document_type.lower()
        
        # Tenancy Contract rules
        if 'tenancy' in document_type_lower or 'rental' in document_type_lower or 'lease' in document_type_lower:
            return {
                'fields': [
                    'Tenant Name',
                    'Landlord Name',
                    'Property Address',
                    'Security Deposit Amount',
                    'Contract Start Date',
                    'Contract End Date',
                    'Annual Rent Amount',
                    'Payment Schedule',
                    'Contract Terms'
                ],
                'signatures': [
                    'Landlord Signature',
                    'Tenant Signature'
                ],
                'attachments': [
                    'Passport copy',
                    'ID copy'
                ]
            }
        
        # Default: no specific requirements
        return {
            'fields': [],
            'signatures': [],
            'attachments': []
        }
    
    def _encode_image_to_base64(self, image_path: str) -> tuple[str, str]:
        """Encode image or PDF to base64 - reuse from document processor"""
        return self.document_processor._encode_image_to_base64(image_path)
    
    def _analyze_document_compliance(
        self,
        image_path: str,
        extracted_data: Dict[str, Any],
        document_type: str
    ) -> Dict[str, Any]:
        """
        Use AI to analyze document for compliance issues
        
        Args:
            image_path: Path to document file
            extracted_data: Previously extracted data from OCR
            document_type: Classified document type
            
        Returns:
            Dict with compliance analysis results
        """
        max_retries = settings.OCR_MAX_RETRIES
        retry_delay = settings.OCR_RETRY_DELAY
        
        for attempt in range(1, max_retries + 1):
            try:
                logger.info(f"Analyzing document compliance (attempt {attempt}) for type: {document_type}")
                
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Document file does not exist: {image_path}")
                
                # Encode document
                base64_image, media_type = self._encode_image_to_base64(image_path)
                doc_content_type = "document" if media_type == "application/pdf" else "image"
                
                # Get required fields for this document type
                required_items = self._get_required_fields_for_type(document_type)
                required_fields = required_items.get('fields', [])
                required_signatures = required_items.get('signatures', [])
                required_attachments = required_items.get('attachments', [])
                
                # Build compliance check prompt
                compliance_prompt = f'''You are a compliance checker for {document_type} documents. Analyze this document and check for missing required fields, signatures, and attachments.

**Required Fields to Check:**
{json.dumps(required_fields, indent=2) if required_fields else "None specified for this document type"}

**Required Signatures to Check:**
{json.dumps(required_signatures, indent=2) if required_signatures else "None specified for this document type"}

**Required Attachments to Check:**
{json.dumps(required_attachments, indent=2) if required_attachments else "None specified for this document type"}

**Previously Extracted Data:**
{json.dumps(extracted_data, indent=2) if extracted_data else "No extracted data available"}

**Your Tasks:**

1. **Field Compliance Check**: For each required field, check if it is present in the document:
   - Check the extracted data first
   - Also visually inspect the document image to verify the field is actually present
   - Mark as "missing" if not found in either location
   - Mark as "found" if present

2. **Signature Detection**: For each required signature:
   - Visually inspect the document to detect signature marks/signatures
   - Check extracted text for signature field labels (e.g., "Signed by", "Signature:", "Landlord Signature", "Tenant Signature")
   - Mark as "detected" if signature is visually present in the document
   - Mark as "not_detected" if signature is missing
   - Be thorough - look for actual signature marks, not just signature fields

3. **Attachment Check**: For each required attachment:
   - Check the document text to see if it mentions the attachment (e.g., "Passport copy attached", "ID copy required")
   - Check if the document indicates the attachment should be present
   - Mark as "present" if mentioned as attached or visible in document
   - Mark as "attachment_missing" if required but not mentioned or visible

**Output Format:**

Return your analysis in JSON format:
{{
    "overall_status": "compliant" | "non_compliant",
    "issues": [
        {{
            "field": "Field Name",
            "status": "missing" | "found" | "not_detected" | "detected" | "present" | "attachment_missing",
            "message": "Field Name → Missing" or similar descriptive message
        }}
    ],
    "missing_fields": ["Field1", "Field2"],
    "missing_signatures": ["Signature1"],
    "missing_attachments": ["Attachment1"]
}}

**Important Rules:**
- Be accurate and thorough in your analysis
- Only report issues that are actually missing
- For signatures, you must visually detect them in the document image
- For fields, check both extracted data AND visual presence in document
- Use clear, descriptive messages for each issue
- If all required items are present, set overall_status to "compliant"
- If any required items are missing, set overall_status to "non_compliant"

Now analyze this document:'''
                
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": compliance_prompt
                            },
                            {
                                "type": doc_content_type,
                                "source": {
                                    "type": "base64",
                                    "media_type": media_type,
                                    "data": base64_image
                                }
                            }
                        ]
                    }
                ]
                
                # Make Anthropic API call
                response = self.anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=2048,
                    messages=messages
                )
                
                # Parse response
                compliance_result = response.content[0].text
                logger.info(f"Compliance analysis result received")
                
                # Extract JSON from response
                compliance_data = extract_json_from_text(compliance_result)
                if compliance_data:
                    return compliance_data
                
                # Fallback: try to parse manually
                logger.warning("Failed to parse JSON from compliance response, using fallback parsing")
                return self._parse_compliance_response_fallback(compliance_result, required_fields, required_signatures, required_attachments)
                
            except Exception as e:
                error_message = str(e)
                logger.error(f"Compliance analysis attempt {attempt} failed: {error_message}")

                model_hint = detect_model_not_found_error(error_message, self.model)
                if model_hint:
                    raise Exception(f"OCR_MODEL_NOT_FOUND: {model_hint}") from e
                
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    import time
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"COMPLIANCE_CHECK_FAILED: {error_message}")
    
    def _parse_compliance_response_fallback(
        self,
        response_text: str,
        required_fields: List[str],
        required_signatures: List[str],
        required_attachments: List[str]
    ) -> Dict[str, Any]:
        """Fallback parser if JSON parsing fails"""
        issues = []
        missing_fields = []
        missing_signatures = []
        missing_attachments = []
        
        response_lower = response_text.lower()
        
        # Check fields
        for field in required_fields:
            if field.lower() not in response_lower or 'missing' in response_lower:
                issues.append({
                    "field": field,
                    "status": "missing",
                    "message": f"{field} → Missing"
                })
                missing_fields.append(field)
        
        # Check signatures
        for sig in required_signatures:
            if sig.lower() not in response_lower or 'not detected' in response_lower:
                issues.append({
                    "field": sig,
                    "status": "not_detected",
                    "message": f"{sig} → Not Detected"
                })
                missing_signatures.append(sig)
        
        # Check attachments
        for attachment in required_attachments:
            if attachment.lower() not in response_lower or 'missing' in response_lower:
                issues.append({
                    "field": attachment,
                    "status": "attachment_missing",
                    "message": f"{attachment} → Attachment missing"
                })
                missing_attachments.append(attachment)
        
        overall_status = "compliant" if len(issues) == 0 else "non_compliant"
        
        return {
            "overall_status": overall_status,
            "issues": issues,
            "missing_fields": missing_fields,
            "missing_signatures": missing_signatures,
            "missing_attachments": missing_attachments
        }
    
    def check_compliance(
        self,
        document_id: str,
        image_path: str,
        extracted_data: Dict[str, Any],
        document_type: str
    ) -> Dict[str, Any]:
        """
        Main method to check document compliance
        
        Args:
            document_id: Document ID
            image_path: Path to document file
            extracted_data: Previously extracted data from OCR
            document_type: Classified document type
            
        Returns:
            Dict with compliance check results
        """
        try:
            logger.info(f"Starting compliance check for document: {document_id}, type: {document_type}")
            
            # Analyze document compliance using AI
            compliance_result = self._analyze_document_compliance(
                image_path=image_path,
                extracted_data=extracted_data,
                document_type=document_type
            )
            
            # Add metadata
            compliance_result['document_id'] = document_id
            compliance_result['document_type'] = document_type
            compliance_result['check_timestamp'] = datetime.now().isoformat()
            
            logger.info(f"Compliance check completed for document: {document_id}, status: {compliance_result.get('overall_status')}")
            logger.info(f"Found {len(compliance_result.get('issues', []))} compliance issues")
            
            return compliance_result
            
        except Exception as e:
            logger.error(f"Error checking compliance for document {document_id}: {str(e)}")
            raise

