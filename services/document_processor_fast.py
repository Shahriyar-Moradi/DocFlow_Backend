"""
Optimized document processor with combined classification and extraction
This is an alternative implementation that combines both steps into one API call
for faster processing.
"""
import os
import base64
import json
import re
import logging
from typing import Dict, Any, Optional
from pathlib import Path

from anthropic import Anthropic

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from config import settings

logger = logging.getLogger(__name__)

class FastDocumentProcessor:
    """
    Optimized processor that combines classification and extraction in one API call
    Reduces processing time by ~50% (from 2 API calls to 1)
    """
    
    def __init__(self):
        """Initialize the Fast Document Processor"""
        if not settings.anthropic_api_key_configured:
            raise ValueError("ANTHROPIC_API_KEY is required for document processing")
        
        try:
            self.anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = settings.ANTHROPIC_MODEL
            logger.info(f"Fast Document Processor initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            raise
    
    def _encode_image_to_base64(self, image_path: str) -> str:
        """Encode image or PDF to base64"""
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
            encoded = base64.b64encode(image_data).decode('utf-8')
            return encoded
    
    def classify_and_extract(self, image_path: str) -> Dict[str, Any]:
        """
        Combined classification and extraction in one API call
        This is faster than separate calls but may be less accurate for edge cases
        """
        try:
            logger.info(f"Fast processing document: {image_path}")
            
            base64_image = self._encode_image_to_base64(image_path)
            
            # Determine media type
            file_extension = os.path.splitext(image_path)[1].lower().lstrip('.')
            if file_extension in ['jpg', 'jpeg']:
                media_type = "image/jpeg"
            elif file_extension == 'png':
                media_type = "image/png"
            elif file_extension == 'pdf':
                media_type = "application/pdf"
            else:
                media_type = "image/png"
            
            doc_content_type = "document" if media_type == "application/pdf" else "image"
            
            # Combined prompt for classification and extraction
            combined_prompt = '''Analyze this document and perform both classification and data extraction in one step.

STEP 1 - CLASSIFICATION:
Classify the document into one of these categories:
- Invoice
- Receipt
- Contract/Agreement
- Purchase Order
- Legal Document
- Voucher
- Real Estate
- Other

STEP 2 - EXTRACTION:
Extract all key information:
- Document number/ID
- Date(s) (issue date, due date, etc.)
- Amount/Total with currency
- Parties involved (buyer, seller, client, vendor, etc.)
- Items/services listed
- Terms and conditions
- Signature/authorization info

Return in JSON format:
{
    "document_type": "Invoice",
    "classification_confidence": 0.95,
    "classification_reasoning": "Brief explanation",
    "document_number": "INV-2025-001",
    "issue_date": "2025-01-15",
    "total_amount": "1500.00",
    "currency": "USD",
    "buyer": {"name": "...", "address": "..."},
    "seller": {"name": "...", "address": "..."},
    "items": [...],
    "terms": "...",
    "signatures": {"present": true, "signatories": [...]}
}

Be thorough and accurate. Extract all available information.'''
            
            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": combined_prompt
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
            
            # Single API call for both classification and extraction
            response = self.anthropic_client.messages.create(
                model=self.model,
                max_tokens=1536,  # Optimized for combined response
                messages=messages
            )
            
            result_text = response.content[0].text
            logger.info("Combined classification and extraction completed")
            
            # Parse JSON response
            json_match = re.search(r'\{[^}]*\}', result_text, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return {
                    'success': True,
                    'document_type': data.get('document_type', 'Other'),
                    'classification_confidence': float(data.get('classification_confidence', 0.5)),
                    'classification_reasoning': data.get('classification_reasoning', ''),
                    'extracted_data': data,
                    'document_no': data.get('document_number') or data.get('document_id') or '',
                    'document_date': data.get('issue_date') or data.get('document_date') or '',
                    'ocr_text': result_text
                }
            else:
                raise ValueError("No JSON found in response")
                
        except Exception as e:
            logger.error(f"Fast processing failed: {e}")
            return {
                'success': False,
                'error': str(e),
                'document_type': 'Other',
                'classification_confidence': 0.0
            }

