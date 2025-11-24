"""
Document processing service adapted from Lambda OCR service
Uses Anthropic API directly and GCS for storage
"""
import os
import base64
import json
import re
import struct
import zlib
import time
import tempfile
import logging
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False

from anthropic import Anthropic

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from config import settings

logger = logging.getLogger(__name__)

class DocumentProcessor:
    """Document processing service using Anthropic API for OCR"""
    
    def __init__(self):
        """Initialize the Document Processor"""
        logger.info("Initializing Document Processor...")
        logger.info(f"PyMuPDF available: {PYMUPDF_AVAILABLE}")
        logger.info(f"PIL available: {PIL_AVAILABLE}")
        
        # Initialize Anthropic client
        if not settings.anthropic_api_key_configured:
            raise ValueError("ANTHROPIC_API_KEY is required for document processing")
        
        try:
            self.anthropic_client = Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            self.model = settings.ANTHROPIC_MODEL
            logger.info(f"Anthropic client initialized with model: {self.model}")
        except Exception as e:
            logger.error(f"Failed to initialize Anthropic client: {e}")
            raise
        
        # Define voucher type prefixes
        self.voucher_types = {
            "MPU": "MPU",
            "MPV": "MPV",
            "MRT": "MRT",
            "MSL": "MSL",
            "REC": "REC",
            "PAY": "PAY",
            "MJV": "MJV"
        }
        
        # Month mapping
        self.month_names = {
            1: "jan", 2: "feb", 3: "mar", 4: "apr",
            5: "may", 6: "jun", 7: "jul", 8: "aug",
            9: "sep", 10: "oct", 11: "nov", 12: "dec"
        }
    
    def _detect_image_format(self, image_path: str) -> str:
        """Detect actual image format from file content (magic bytes)"""
        with open(image_path, "rb") as f:
            header = f.read(16)
        
        # Check magic bytes
        if header.startswith(b'\xff\xd8\xff'):
            return 'jpeg'
        elif header.startswith(b'\x89PNG\r\n\x1a\n'):
            return 'png'
        elif header.startswith(b'%PDF'):
            return 'pdf'
        elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):
            return 'gif'
        elif header.startswith(b'RIFF') and header[8:12] == b'WEBP':
            return 'webp'
        else:
            logger.warning(f"Unknown image format for: {image_path}")
            return 'unknown'
    
    def _normalize_image_format(self, image_path: str) -> tuple[str, str]:
        """
        Ensure image format matches its extension by converting if needed.
        Returns: (normalized_path, actual_format)
        """
        if not PIL_AVAILABLE:
            # Without PIL, we can't convert - just detect and warn
            actual_format = self._detect_image_format(image_path)
            logger.warning(f"PIL not available - cannot convert format. Actual format: {actual_format}")
            return image_path, actual_format
        
        try:
            actual_format = self._detect_image_format(image_path)
            file_ext = os.path.splitext(image_path)[1].lower().lstrip('.')
            
            # If format matches extension, no conversion needed
            if (actual_format == 'jpeg' and file_ext in ['jpg', 'jpeg']) or \
               (actual_format == file_ext):
                logger.info(f"Image format matches extension: {actual_format}")
                return image_path, actual_format
            
            # Format mismatch - need to convert
            logger.warning(f"Format mismatch detected: file is {actual_format} but extension is .{file_ext}")
            
            if actual_format == 'pdf':
                # Don't convert PDFs
                return image_path, 'pdf'
            
            # Convert image to match its extension or to PNG as default
            target_format = file_ext if file_ext in ['png', 'jpg', 'jpeg'] else 'png'
            
            # Open image with PIL
            img = Image.open(image_path)
            
            # Convert RGBA to RGB for JPEG
            if target_format in ['jpg', 'jpeg'] and img.mode in ['RGBA', 'LA', 'P']:
                logger.info(f"Converting {img.mode} to RGB for JPEG")
                rgb_img = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                rgb_img.paste(img, mask=img.split()[-1] if img.mode in ['RGBA', 'LA'] else None)
                img = rgb_img
            
            # Create new filename with correct format
            base_path = os.path.splitext(image_path)[0]
            if target_format in ['jpg', 'jpeg']:
                new_path = base_path + '_converted.jpg'
                img.save(new_path, 'JPEG', quality=95)
                logger.info(f"Converted to JPEG: {new_path}")
                return new_path, 'jpeg'
            else:
                new_path = base_path + '_converted.png'
                img.save(new_path, 'PNG')
                logger.info(f"Converted to PNG: {new_path}")
                return new_path, 'png'
                
        except Exception as e:
            logger.error(f"Error normalizing image format: {e}")
            # Return original path and detected format
            actual_format = self._detect_image_format(image_path)
            return image_path, actual_format
    
    def _encode_image_to_base64(self, image_path: str) -> tuple[str, str]:
        """
        Encode image or PDF to base64 with validation and format detection.
        Returns: (base64_data, media_type)
        """
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        file_size = os.path.getsize(image_path)
        file_ext = os.path.splitext(image_path)[1].lower()
        logger.info(f"Encoding file: {image_path} (size: {file_size} bytes, extension: {file_ext})")
        
        if file_size == 0:
            raise ValueError(f"File is empty: {image_path}")
        
        if file_size > 10 * 1024 * 1024:  # 10MB
            logger.warning(f"Large file ({file_size / 1024 / 1024:.1f}MB)")
        
        # Normalize image format to match extension
        normalized_path, actual_format = self._normalize_image_format(image_path)
        
        # Determine correct media type based on actual format
        if actual_format == 'jpeg':
            media_type = "image/jpeg"
        elif actual_format == 'png':
            media_type = "image/png"
        elif actual_format == 'pdf':
            media_type = "application/pdf"
        elif actual_format == 'gif':
            media_type = "image/gif"
        elif actual_format == 'webp':
            media_type = "image/webp"
        else:
            # Default to PNG for unknown formats
            media_type = "image/png"
            logger.warning(f"Unknown format, defaulting to image/png")
        
        logger.info(f"Using media type: {media_type} for format: {actual_format}")
        
        with open(normalized_path, "rb") as image_file:
            image_data = image_file.read()
            if not image_data:
                raise ValueError(f"Failed to read file data from: {normalized_path}")
            
            encoded = base64.b64encode(image_data).decode('utf-8')
            logger.info(f"File encoded successfully: {len(encoded)} base64 characters")
            
            # Clean up converted file if it's different from original
            if normalized_path != image_path and os.path.exists(normalized_path):
                try:
                    os.remove(normalized_path)
                    logger.info(f"Cleaned up converted file: {normalized_path}")
                except:
                    pass
            
            return encoded, media_type
    
    def _parse_document_date(self, date_str: Optional[str]) -> tuple[int, int, int]:
        """Parse document date and return year, month, day components"""
        if not date_str:
            now = datetime.now()
            return now.year, now.month, now.day
        
        try:
            date_formats = [
                "%d-%m-%Y",  # 02-06-2025
                "%d/%m/%Y",  # 02/06/2025
                "%Y-%m-%d",  # 2025-06-02
                "%Y/%m/%d",  # 2025/06/02
                "%m-%d-%Y",  # 06-02-2025
                "%m/%d/%Y",  # 06/02/2025
            ]
            
            for fmt in date_formats:
                try:
                    date_obj = datetime.strptime(date_str.strip(), fmt)
                    return date_obj.year, date_obj.month, date_obj.day
                except ValueError:
                    continue
            
            # Try to extract components
            match = re.match(r'(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})', date_str)
            if match:
                day, month, year = match.groups()
                year = int(year)
                if year < 100:
                    year += 2000 if year < 50 else 1900
                return year, int(month), int(day)
            
            match = re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', date_str)
            if match:
                year, month, day = match.groups()
                return int(year), int(month), int(day)
                
        except Exception as e:
            logger.error(f"Error parsing date '{date_str}': {e}")
        
        # Default to current date
        now = datetime.now()
        return now.year, now.month, now.day
    
    def _create_organized_path(
        self,
        document_no: str,
        document_date: Optional[str],
        branch_id: Optional[str],
        voucher_type: str
    ) -> Optional[str]:
        """Create the organized path structure"""
        try:
            year, month, day = self._parse_document_date(document_date)
            
            # Format branch ID
            if branch_id:
                try:
                    branch_num = int(branch_id)
                    branch_folder = f"Branch {branch_num:02d}"
                except:
                    branch_folder = f"Branch {branch_id}"
            else:
                branch_folder = "Branch 01"
            
            # Get month name
            month_name = self.month_names.get(month, f"month{month:02d}")
            
            # Format date folder
            date_folder = f"{day}-{month}-{year}"
            
            # Ensure voucher type is valid
            if not voucher_type or voucher_type not in self.voucher_types:
                voucher_type = self._extract_document_no_prefix(document_no)
                if not voucher_type or voucher_type not in self.voucher_types:
                    logger.warning(f"Invalid voucher type - cannot create organized path")
                    return None
            
            # Build the path
            path_components = [
                "organized_vouchers",
                str(year),
                branch_folder,
                month_name,
                date_folder,
                voucher_type
            ]
            
            organized_path = "/".join(path_components)
            logger.info(f"Created organized path: {organized_path}")
            return organized_path
            
        except Exception as e:
            logger.error(f"Error creating organized path: {e}")
            return None
    
    def _create_general_organized_path(self, document_type: str, document_date: Optional[str], document_no: str) -> Optional[str]:
        """
        Create organized path for general document types
        
        Structure: organized_documents/{document_type}/{year}/{month}/{date}/{document_no}/
        """
        try:
            year, month, day = self._parse_document_date(document_date)
            month_name = self.month_names.get(month, "unknown")
            
            # Sanitize document type for folder name
            doc_type_safe = document_type.lower().replace(' ', '_').replace('/', '_')
            
            # Sanitize document number for folder name
            doc_no_safe = re.sub(r'[<>:"/\\|?*]', '_', document_no.strip())
            
            organized_path = f"{settings.ORGANIZED_FOLDER}/{doc_type_safe}/{year}/{month_name}/{day}-{month}-{year}/{doc_no_safe}"
            
            logger.info(f"Generated general organized path: {organized_path}")
            return organized_path
            
        except Exception as e:
            logger.error(f"Error creating general organized path: {e}")
            return None
    
    def _extract_document_no_prefix(self, document_no: Optional[str]) -> Optional[str]:
        """Extract the prefix from Document No (e.g., MPU from MPU01-85285)"""
        if not document_no:
            return None
        
        match = re.match(r'^([A-Z]+)', document_no.strip())
        if match:
            prefix = match.group(1)
            return prefix if prefix in self.voucher_types else None
        return None
    
    def _classify_document_type(self, image_path: str) -> Dict[str, Any]:
        """
        Classify document type using general classification prompt
        
        Returns:
            Dict with document_type, confidence, and reasoning
        """
        max_retries = settings.OCR_MAX_RETRIES
        retry_delay = settings.OCR_RETRY_DELAY
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Classifying document type (attempt {attempt + 1})...")
                
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image file does not exist: {image_path}")
                
                # Encode and get correct media type based on actual file content
                base64_image, media_type = self._encode_image_to_base64(image_path)
                
                doc_content_type = "document" if media_type == "application/pdf" else "image"
                
                # Classification prompt
                classification_prompt = '''Analyze this document image and classify it into one of these categories based on its content, structure, and layout:

- Invoice: A bill requesting payment for goods or services provided
- Receipt: Proof of payment for goods or services already paid
- Contract/Agreement: Legal document outlining terms between parties
- Purchase Order: Document requesting goods or services from a vendor
- Legal Document: Court documents, legal notices, legal agreements, etc.
- Voucher: Payment voucher, credit voucher, or transaction voucher
- Real Estate: Property documents, lease agreements, property deeds, rental agreements, etc.
- Other: Any other official or business document not fitting the above categories

Consider these indicators:
- Document headers and titles
- Field labels and structure
- Presence of signatures or authorization
- Payment/amount sections
- Terms and conditions sections
- Document layout and formatting
- Content and context

Return your classification in JSON format:
{
    "document_type": "Invoice",
    "confidence": 0.95,
    "reasoning": "Brief explanation of why this classification was chosen"
}

Be specific and accurate. If uncertain, use lower confidence scores.'''
                
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": classification_prompt
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
                
                # Make Anthropic API call (reduced tokens for faster response)
                response = self.anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=256,  # Reduced from 512 for faster classification
                    messages=messages
                )
                
                # Parse response
                classification_result = response.content[0].text
                logger.info(f"Classification result received: {classification_result[:200]}")
                
                # Extract JSON from response
                json_match = re.search(r'\{[^}]*\}', classification_result, re.DOTALL)
                if json_match:
                    classification_data = json.loads(json_match.group())
                    return {
                        'document_type': classification_data.get('document_type', 'Other'),
                        'confidence': float(classification_data.get('confidence', 0.5)),
                        'reasoning': classification_data.get('reasoning', '')
                    }
                else:
                    # Fallback: try to extract document type from text
                    doc_type_match = re.search(r'"document_type":\s*"([^"]+)"', classification_result, re.IGNORECASE)
                    if doc_type_match:
                        return {
                            'document_type': doc_type_match.group(1),
                            'confidence': 0.7,
                            'reasoning': 'Extracted from response text'
                        }
                    return {
                        'document_type': 'Other',
                        'confidence': 0.5,
                        'reasoning': 'Could not parse classification response'
                    }
                
            except Exception as e:
                error_message = str(e)
                logger.error(f"Classification attempt {attempt + 1} failed: {error_message}")
                
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    # Return default on failure
                    logger.warning("Classification failed, using default 'Other'")
                    return {
                        'document_type': 'Other',
                        'confidence': 0.0,
                        'reasoning': f'Classification failed: {error_message}'
                    }
    
    def _extract_general_document_data(self, image_path: str, document_type: str) -> str:
        """
        Extract general document data using flexible prompt based on document type
        
        Args:
            image_path: Path to the document file
            document_type: Classified document type (Invoice, Receipt, Contract, etc.)
            
        Returns:
            JSON string with extracted data
        """
        max_retries = settings.OCR_MAX_RETRIES
        retry_delay = settings.OCR_RETRY_DELAY
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Extracting general document data (attempt {attempt + 1}) for type: {document_type}")
                
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image file does not exist: {image_path}")
                
                # Encode and get correct media type based on actual file content
                base64_image, media_type = self._encode_image_to_base64(image_path)
                
                doc_content_type = "document" if media_type == "application/pdf" else "image"
                doc_or_image_text = "document" if media_type == "application/pdf" else "image"
                
                # General extraction prompt
                extraction_prompt = f'''Extract all key information from this {document_type.lower()} document. 

Extract the following fields (include all that are present, omit those that are not):

1. **Document number/ID**: Any unique identifier, invoice number, receipt number, contract number, etc.
2. **Date(s)**: Document date, issue date, due date, effective date, expiration date - extract all dates found
3. **Amount/Total**: Total amount, subtotal, tax, fees, discounts - include currency (USD, EUR, AED, etc.)
4. **Parties involved**: 
   - Buyer, seller, client, customer, vendor, supplier
   - Names, addresses, contact information
   - For contracts: parties to the agreement
   - For real estate: buyer, seller, landlord, tenant, agent
5. **Items/services listed**: 
   - Line items, products, services
   - Quantities, descriptions, unit prices
   - For contracts: services or deliverables
   - For real estate: property details, address, square footage
6. **Terms and conditions**: 
   - Payment terms, delivery terms
   - Contract terms, conditions, clauses
   - Legal terms, warranties, guarantees
7. **Signature/authorization info**:
   - Signatures present (yes/no)
   - Signatory names and titles
   - Authorization stamps or seals
   - Notary information if present

Extraction Rules:
- Extract text EXACTLY as shown (preserve formatting, spaces, hyphens)
- For dates, preserve original format
- For amounts, include currency symbol or code
- For multi-page PDFs, extract from all pages
- If a field is not found, omit it from JSON (don't use null or empty strings)
- Extract all relevant information comprehensively

Return in JSON format with all extracted fields:
{{
    "document_number": "INV-2025-001",
    "document_id": "DOC-12345",
    "issue_date": "2025-01-15",
    "due_date": "2025-02-15",
    "total_amount": "1500.00",
    "currency": "USD",
    "subtotal": "1300.00",
    "tax": "200.00",
    "buyer": {{
        "name": "Company Name",
        "address": "123 Main St",
        "contact": "contact@company.com"
    }},
    "seller": {{
        "name": "Vendor Name",
        "address": "456 Vendor Ave"
    }},
    "items": [
        {{
            "description": "Product/Service Name",
            "quantity": "2",
            "unit_price": "650.00",
            "total": "1300.00"
        }}
    ],
    "terms": "Net 30 days, payment due upon receipt",
    "signatures": {{
        "present": true,
        "signatories": ["John Doe", "Jane Smith"],
        "titles": ["Manager", "Director"]
    }},
    "additional_info": "Any other relevant information"
}}

Adapt the extraction based on the document type ({document_type}). Be thorough and accurate.'''
                
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": extraction_prompt
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
                
                # Make Anthropic API call (optimized tokens for faster response)
                response = self.anthropic_client.messages.create(
                    model=self.model,
                    max_tokens=1536,  # Reduced from 2048 for faster extraction
                    messages=messages
                )
                
                # Parse response
                extraction_result = response.content[0].text
                logger.info(f"General extraction result received")
                return extraction_result
                
            except Exception as e:
                error_message = str(e)
                logger.error(f"General extraction attempt {attempt + 1} failed: {error_message}")
                
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"EXTRACTION_FAILED: {error_message}")
    
    def _extract_transaction_data(self, image_path: str) -> str:
        """Extract transaction data using Anthropic OCR"""
        max_retries = settings.OCR_MAX_RETRIES
        retry_delay = settings.OCR_RETRY_DELAY
        
        for attempt in range(max_retries + 1):
            try:
                logger.info(f"Attempting Anthropic OCR (attempt {attempt + 1})...")
                logger.info(f"Image path: {image_path}")
                
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image file does not exist: {image_path}")
                
                # Encode and get correct media type based on actual file content
                base64_image, media_type = self._encode_image_to_base64(image_path)
                
                logger.info(f"Media type: {media_type}")
                
                # Build content based on file type
                if media_type == "application/pdf":
                    doc_content_type = "document"
                    doc_or_image_text = "document/voucher"
                else:
                    doc_content_type = "image"
                    doc_or_image_text = "voucher image"
                
                # Prepare messages for Anthropic API
                messages = [
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": '''OCR and extract important information from voucher/invoice images or PDF documents accurately.

You need to extract:
1. **Document No** (e.g., "MPU01-85285") - Extract EXACTLY as shown without any spaces and hyphens
2. **Document Date** (e.g., "02/06/2025") - Extract EXACTLY as shown without any spaces and hyphens
3. **Branch ID** (extracted from Document No) - Extract EXACTLY as shown without any spaces and hyphens
4. **Invoice Amount USD** (e.g., "15000.00" or "15,000.00") - Extract USD amount if present
5. **Invoice Amount AED/DHS** (e.g., "55000.00") - Extract AED or DHS amount if present
6. **Gold Weight** (e.g., "20000.000" grams) - Extract weight in grams (CRITICAL for matching)
7. **Purity** (e.g., "1.000", "0.995", "22K", "24K") - Extract purity value (CRITICAL for matching)
8. **Discount Rate** (e.g., "5.0" or "-10.50$/OZ") - Extract discount rate if available

Extraction Rules:
- Extract the COMPLETE Document No preserving all spaces and hyphens
- DO NOT modify, sanitize, or change the format
- Keep it exactly: "MPU01-85285" not "MPU01_-_85285"
- For PDFs: Extract from the first page if multi-page document
- Extract BOTH currencies if available (USD and AED/DHS)
- Gold Weight should be in grams (remove commas: "20,000.00" → "20000.00")
- Purity can be decimal (1.000, 0.995) or karat (22K, 24K)
- If a field is not found, omit it from JSON

Return in JSON format:
{
    "document_no": "MPU01-85285",
    "category_type": "MPU",
    "branch_id": "01",
    "document_date": "02/06/2025",
    "filename": "MPU01-85285",
    "invoice_amount_usd": "2154100.49",
    "invoice_amount_aed": "7914165.20",
    "gold_weight": "20000.000",
    "purity": "1.000",
    "discount_rate": "-10.50$/OZ"
}'''
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
                    },
                    {
                        "role": "assistant",
                        "content": f"I understand perfectly. I will:\n\n1. Extract the **COMPLETE Document No** exactly as displayed (e.g., 'MPU01-85285')\n2. without modification\n3. Use this complete Document No as the filename\n4. Extract Category Type ('MPU') for folder organization\n5. Extract Branch ID ('01') for sub-folder structure\n6. Extract Document Date in original format\n\nReady to process your {doc_or_image_text}!"
                    },
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": f"Now process this {doc_or_image_text} and return the JSON response:"
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
                    max_tokens=1024,
                    messages=messages
                )
                
                # Parse response
                ocr_result = response.content[0].text
                logger.info(f"Anthropic OCR result received")
                return ocr_result
                
            except Exception as e:
                error_message = str(e)
                logger.error(f"OCR attempt {attempt + 1} failed: {error_message}")
                
                if attempt < max_retries:
                    logger.info(f"Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"OCR_FAILED: {error_message}")
    
    def _convert_image_to_pdf(self, image_path: str) -> Optional[str]:
        """Convert image to PDF format using pure Python"""
        try:
            # Create PDF file path
            pdf_path = image_path.rsplit('.', 1)[0] + '_0001.pdf'
            
            logger.info(f"Converting {image_path} to PDF...")
            
            # Read image file
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            if len(image_bytes) == 0:
                logger.error("Image file is empty")
                return None
            
            # Get image dimensions
            if image_bytes[0:2] == b'\xff\xd8':  # JPEG
                try:
                    width, height = self._get_jpeg_dimensions(image_bytes)
                    filter_type = '/DCTDecode'
                    colorspace = '/DeviceRGB'
                    bpc = 8
                    image_data = image_bytes
                    logger.info(f"JPEG image: {width}x{height}")
                except Exception as jpeg_error:
                    logger.error(f"Failed to parse JPEG: {jpeg_error}")
                    return None
                
            elif image_bytes[0:8] == b'\x89PNG\r\n\x1a\n':  # PNG
                width = struct.unpack('>I', image_bytes[16:20])[0]
                height = struct.unpack('>I', image_bytes[20:24])[0]
                bit_depth = image_bytes[24]
                color_type = image_bytes[25]
                
                logger.info(f"PNG image: {width}x{height}, bit_depth={bit_depth}, color_type={color_type}")
                
                # Extract IDAT chunks
                image_data = self._extract_png_idat(image_bytes)
                if not image_data:
                    raise ValueError("Failed to extract PNG image data")
                
                # Determine colorspace
                if color_type == 0:
                    colorspace = '/DeviceGray'
                    components = 1
                elif color_type == 2:
                    colorspace = '/DeviceRGB'
                    components = 3
                elif color_type == 3:
                    colorspace = '/DeviceRGB'
                    components = 3
                elif color_type == 4:
                    colorspace = '/DeviceGray'
                    components = 1
                elif color_type == 6:
                    colorspace = '/DeviceRGB'
                    components = 3
                else:
                    colorspace = '/DeviceRGB'
                    components = 3
                
                filter_type = '/FlateDecode'
                bpc = bit_depth
            else:
                raise ValueError("Unsupported image format (only JPEG and PNG supported)")
            
            # Create minimal PDF
            pdf_content = []
            pdf_content.append(b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
            
            # Catalog
            obj1_start = sum(len(x) for x in pdf_content)
            pdf_content.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
            
            # Pages
            obj2_start = sum(len(x) for x in pdf_content)
            pdf_content.append(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')
            
            # Page
            obj3_start = sum(len(x) for x in pdf_content)
            pdf_content.append(b'3 0 obj\n')
            pdf_content.append(f'<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] '.encode())
            pdf_content.append(b'/Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>\nendobj\n')
            
            # Content stream
            obj4_start = sum(len(x) for x in pdf_content)
            stream = f'q\n{width} 0 0 {height} 0 0 cm\n/Im1 Do\nQ\n'.encode()
            pdf_content.append(f'4 0 obj\n<< /Length {len(stream)} >>\nstream\n'.encode())
            pdf_content.append(stream)
            pdf_content.append(b'\nendstream\nendobj\n')
            
            # Image
            obj5_start = sum(len(x) for x in pdf_content)
            pdf_content.append(b'5 0 obj\n')
            pdf_content.append(f'<< /Type /XObject /Subtype /Image /Width {width} /Height {height} '.encode())
            pdf_content.append(f'/ColorSpace {colorspace} /BitsPerComponent {bpc} '.encode())
            
            if filter_type == '/FlateDecode':
                pdf_content.append(b'/Filter /FlateDecode ')
                pdf_content.append(b'/DecodeParms << /Predictor 15 /Colors 3 /BitsPerComponent 8 /Columns ')
                pdf_content.append(f'{width} >> '.encode())
            else:
                pdf_content.append(f'/Filter {filter_type} '.encode())
            
            pdf_content.append(f'/Length {len(image_data)} >>\nstream\n'.encode())
            pdf_content.append(image_data)
            pdf_content.append(b'\nendstream\nendobj\n')
            
            # xref and trailer
            xref_start = sum(len(x) for x in pdf_content)
            pdf_content.append(b'xref\n0 6\n0000000000 65535 f \n')
            pdf_content.append(f'{obj1_start:010d} 00000 n \n'.encode())
            pdf_content.append(f'{obj2_start:010d} 00000 n \n'.encode())
            pdf_content.append(f'{obj3_start:010d} 00000 n \n'.encode())
            pdf_content.append(f'{obj4_start:010d} 00000 n \n'.encode())
            pdf_content.append(f'{obj5_start:010d} 00000 n \n'.encode())
            pdf_content.append(b'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n')
            pdf_content.append(f'{xref_start}\n'.encode())
            pdf_content.append(b'%%EOF\n')
            
            # Write PDF
            with open(pdf_path, 'wb') as f:
                for chunk in pdf_content:
                    f.write(chunk)
            
            if os.path.exists(pdf_path):
                pdf_size = os.path.getsize(pdf_path)
                logger.info(f"Successfully converted to PDF: {pdf_path} ({pdf_size} bytes)")
                return pdf_path
            else:
                logger.error("PDF file was not created")
                return None
                
        except Exception as e:
            logger.error(f"Error converting to PDF: {e}")
            return None
    
    def _extract_png_idat(self, png_bytes: bytes) -> Optional[bytes]:
        """Extract and combine all IDAT chunks from PNG"""
        if png_bytes[0:8] != b'\x89PNG\r\n\x1a\n':
            return None
        
        idat_data = b''
        pos = 8
        
        while pos < len(png_bytes):
            if pos + 8 > len(png_bytes):
                break
            
            chunk_length = struct.unpack('>I', png_bytes[pos:pos+4])[0]
            chunk_type = png_bytes[pos+4:pos+8]
            
            if chunk_type == b'IDAT':
                chunk_data = png_bytes[pos+8:pos+8+chunk_length]
                idat_data += chunk_data
            
            if chunk_type == b'IEND':
                break
            
            pos += 4 + 4 + chunk_length + 4
        
        return idat_data if idat_data else None
    
    def _get_jpeg_dimensions(self, jpeg_bytes: bytes) -> tuple[int, int]:
        """Extract width and height from JPEG"""
        try:
            i = 0
            if jpeg_bytes[0:2] != b'\xff\xd8':
                raise ValueError("Not a valid JPEG file")
            
            i = 2
            
            while i < len(jpeg_bytes) - 10:
                if jpeg_bytes[i] != 0xFF:
                    i += 1
                    continue
                
                while i < len(jpeg_bytes) and jpeg_bytes[i] == 0xFF:
                    i += 1
                
                if i >= len(jpeg_bytes):
                    break
                    
                marker = jpeg_bytes[i]
                i += 1
                
                if 0xC0 <= marker <= 0xCF and marker not in [0xC4, 0xC8, 0xCC]:
                    if i + 5 < len(jpeg_bytes):
                        i += 3
                        height = (jpeg_bytes[i] << 8) | jpeg_bytes[i+1]
                        width = (jpeg_bytes[i+2] << 8) | jpeg_bytes[i+3]
                        logger.info(f"JPEG dimensions found: {width}x{height}")
                        return width, height
                
                if i + 1 < len(jpeg_bytes):
                    length = (jpeg_bytes[i] << 8) | jpeg_bytes[i+1]
                    i += length
                else:
                    break
            
            raise ValueError("Could not find JPEG dimensions")
            
        except Exception as e:
            logger.error(f"Error parsing JPEG dimensions: {e}")
            raise ValueError(f"Could not find JPEG dimensions: {e}")
    
    def process_document(self, image_path: str, original_filename: Optional[str] = None) -> Dict[str, Any]:
        """
        Process a document - classify type first, then extract data using OCR
        
        Args:
            image_path: Path to the document file
            original_filename: Original filename for reference
            
        Returns:
            Dict with processing results including classification and extracted data
        """
        try:
            logger.info(f"Processing document: {image_path}")
            
            file_ext = os.path.splitext(image_path)[1].lower()
            if file_ext == '.pdf':
                logger.info("Processing PDF directly via Claude API")
            
            # Step 1: Classify document type (can be skipped for faster processing)
            if hasattr(settings, 'SKIP_CLASSIFICATION') and settings.SKIP_CLASSIFICATION:
                logger.info("Skipping classification step for faster processing")
                document_type = 'Other'
                classification_confidence = 0.5
                classification_reasoning = 'Classification skipped for performance'
            else:
                logger.info("Step 1: Classifying document type...")
                classification_result = self._classify_document_type(image_path)
                document_type = classification_result.get('document_type', 'Other')
                classification_confidence = classification_result.get('confidence', 0.0)
                classification_reasoning = classification_result.get('reasoning', '')
                logger.info(f"Document classified as: {document_type} (confidence: {classification_confidence:.2f})")
            
            # Step 2: Extract data based on document type
            logger.info(f"Step 2: Extracting data for {document_type}...")
            
            # Initialize result structure
            result = {
                'success': True,
                'document_type': document_type,
                'classification': 'UNKNOWN',
                'classification_confidence': classification_confidence,
                'classification_reasoning': classification_reasoning,
                'document_no': None,
                'document_date': None,
                'branch_id': None,
                'ocr_text': None,
                'extracted_data': {},
                'confidence': classification_confidence,
                'method': 'anthropic_ocr',
                'organized_path': None,
                'complete_filename': None,
                'invoice_amount_usd': None,
                'invoice_amount_aed': None,
                'gold_weight': None,
                'purity': None,
                'discount_rate': None,
                'is_valid_voucher': False,
                'needs_attachment': False
            }
            
            # Use voucher-specific extraction for vouchers, general extraction for others
            if document_type.lower() == 'voucher':
                logger.info("Using voucher-specific extraction method")
                transaction_data = self._extract_transaction_data(image_path)
                result['ocr_text'] = transaction_data
                extraction_method = 'voucher_specific'
            else:
                logger.info(f"Using general extraction method for {document_type}")
                transaction_data = self._extract_general_document_data(image_path, document_type)
                result['ocr_text'] = transaction_data
                extraction_method = 'general'
            
            result['extraction_method'] = extraction_method
            
            # Try to parse JSON response
            try:
                json_match = re.search(r'\{[^}]*\}', transaction_data, re.DOTALL)
                if json_match:
                    json_data = json.loads(json_match.group())
                    result['extracted_data'] = json_data
                    
                    # Handle voucher-specific extraction
                    if extraction_method == 'voucher_specific':
                        # Extract data from JSON
                        result['document_no'] = json_data.get('document_no', '').strip()
                        result['document_date'] = json_data.get('document_date', '').strip()
                        result['branch_id'] = json_data.get('branch_id', '').strip()
                        raw_classification = json_data.get('category_type', '').strip()
                        
                        # Extract classification from document_no if missing
                        if not raw_classification and result['document_no']:
                            extracted_prefix = self._extract_document_no_prefix(result['document_no'])
                            if extracted_prefix:
                                raw_classification = extracted_prefix
                                logger.info(f"Extracted classification from document_no: '{raw_classification}'")
                        
                        if raw_classification and raw_classification in self.voucher_types:
                            result['classification'] = raw_classification
                            result['is_valid_voucher'] = True
                            logger.info(f"Valid voucher type: '{raw_classification}'")
                        else:
                            result['classification'] = raw_classification if raw_classification else 'UNKNOWN'
                            result['is_valid_voucher'] = False
                            logger.warning(f"Invalid voucher type '{raw_classification}' - will treat as attachment")
                        
                        result['complete_filename'] = json_data.get('filename', '').strip()
                        
                        # Extract financial fields
                        usd_amount = json_data.get('invoice_amount_usd', '').strip().replace(',', '') or None
                        aed_amount = json_data.get('invoice_amount_aed', '').strip().replace(',', '') or None
                        weight = json_data.get('gold_weight', '').strip().replace(',', '') or None
                        purity = json_data.get('purity', '').strip() or None
                        
                        result['invoice_amount_usd'] = usd_amount
                        result['invoice_amount_aed'] = aed_amount
                        result['gold_weight'] = weight
                        result['purity'] = purity
                        result['discount_rate'] = json_data.get('discount_rate', '').strip() or None
                        
                        logger.info(f"Extracted: Document No: {result['document_no']}, Date: {result['document_date']}, Branch: {result['branch_id']}, Category: {result['classification']}")
                    
                    # Handle general extraction
                    else:
                        # Extract common fields from general extraction
                        result['document_no'] = json_data.get('document_number') or json_data.get('document_id') or json_data.get('document_no', '').strip()
                        
                        # Extract date (prefer issue_date, fallback to document_date or date)
                        result['document_date'] = (
                            json_data.get('issue_date') or 
                            json_data.get('document_date') or 
                            json_data.get('date') or 
                            ''
                        ).strip()
                        
                        # Extract amount and currency
                        total_amount = json_data.get('total_amount', '')
                        currency = json_data.get('currency', '')
                        if total_amount:
                            if currency.upper() == 'USD':
                                result['invoice_amount_usd'] = str(total_amount).replace(',', '')
                            elif currency.upper() in ['AED', 'DHS']:
                                result['invoice_amount_aed'] = str(total_amount).replace(',', '')
                        
                        # Set classification to document_type
                        result['classification'] = document_type
                        result['complete_filename'] = result['document_no'] or original_filename or 'document'
                        
                        # Store all extracted data
                        logger.info(f"Extracted general document data: Type={document_type}, Doc No={result['document_no']}, Date={result['document_date']}")
                    
                else:
                    raise ValueError("No JSON found in response")
                    
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                logger.warning(f"JSON parsing failed, falling back to regex: {e}")
                
                # Fallback to regex extraction
                document_no_match = re.search(r'Document No:\s*([A-Z0-9\s\-]+)', transaction_data, re.IGNORECASE)
                document_date_match = re.search(r'Document Date:\s*([\d/-]+)', transaction_data, re.IGNORECASE)
                branch_id_match = re.search(r'Branch ID:\s*([0-9]+)', transaction_data, re.IGNORECASE)
                
                if document_no_match:
                    result['document_no'] = document_no_match.group(1).strip()
                    result['classification'] = self._extract_document_no_prefix(result['document_no']) or 'UNKNOWN'
                    result['complete_filename'] = result['document_no']
                    result['is_valid_voucher'] = result['classification'] in self.voucher_types
                    
                    if document_date_match:
                        result['document_date'] = document_date_match.group(1).strip()
                    if branch_id_match:
                        result['branch_id'] = branch_id_match.group(1).strip()
                else:
                    # Try alternative patterns
                    alt_match = re.search(r'([A-Z]{2,}\d{2,}[\s\-]*\d+)', transaction_data)
                    if alt_match:
                        result['document_no'] = alt_match.group(1).strip()
                        result['classification'] = self._extract_document_no_prefix(result['document_no']) or 'UNKNOWN'
                        result['complete_filename'] = result['document_no']
                        result['is_valid_voucher'] = result['classification'] in self.voucher_types
                    else:
                        filename = os.path.basename(image_path)
                        result['document_no'] = os.path.splitext(filename)[0]
                        result['complete_filename'] = result['document_no']
                        result['classification'] = 'UNKNOWN'
                        result['success'] = False
                        result['error'] = "Could not extract Document No from voucher"
                        result['organized_path'] = None
            
            # Generate organized path
            if result['success'] and result['document_no']:
                # For vouchers, use existing voucher path structure
                if result.get('is_valid_voucher') and result['classification'] in self.voucher_types:
                    result['organized_path'] = self._create_organized_path(
                        document_no=result['document_no'],
                        document_date=result['document_date'],
                        branch_id=result['branch_id'],
                        voucher_type=result['classification']
                    )
                    logger.info(f"Valid voucher - will organize to: {result['organized_path']}")
                else:
                    # For general documents, create path based on document type
                    result['organized_path'] = self._create_general_organized_path(
                        document_type=document_type,
                        document_date=result['document_date'],
                        document_no=result['document_no']
                    )
                    logger.info(f"General document - will organize to: {result['organized_path']}")
            elif result['success'] and not result.get('is_valid_voucher') and document_type.lower() == 'voucher':
                result['organized_path'] = None
                result['needs_attachment'] = True
                logger.info("Attachment document - will search for matching valid voucher")
            
            # Convert image to PDF
            pdf_path = None
            if result['success']:
                try:
                    file_extension = os.path.splitext(image_path)[1].lower()
                    
                    if file_extension != '.pdf':
                        logger.info(f"Converting image to PDF: {image_path}")
                        pdf_path = self._convert_image_to_pdf(image_path)
                        if pdf_path:
                            result['pdf_path'] = pdf_path
                            result['converted_to_pdf'] = True
                            logger.info(f"Successfully converted to PDF: {pdf_path}")
                        else:
                            result['pdf_path'] = image_path
                            result['converted_to_pdf'] = False
                    else:
                        result['pdf_path'] = image_path
                        result['converted_to_pdf'] = False
                except Exception as e:
                    logger.error(f"Error during PDF conversion: {e}")
                    result['pdf_path'] = image_path
                    result['converted_to_pdf'] = False
            else:
                result['pdf_path'] = image_path
                result['converted_to_pdf'] = False
            
            logger.info(f"Processing result: success={result['success']}, classification={result['classification']}")
            return result
            
        except Exception as e:
            logger.error(f"Error processing document: {str(e)}")
            return {
                'success': False,
                'error': str(e),
                'document_no': None,
                'document_type': 'Other',
                'classification': 'UNKNOWN',
                'classification_confidence': 0.0,
                'extracted_data': {},
                'method': 'error',
                'organized_path': None
            }

