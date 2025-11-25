import os
import base64
from datetime import datetime
import re
import json
import shutil
import urllib.request
import urllib.error

try:
    import fitz  # PyMuPDF
    PYMUPDF_AVAILABLE = True
except ImportError:
    PYMUPDF_AVAILABLE = False
    print("PyMuPDF not available, PDF processing disabled")

# Use AWS Bedrock for Claude models
import boto3
from services.json_utils import extract_json_from_text

try:
    from PIL import Image
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("PIL library not available, using basic image handling")

# Set environment variable to avoid tokenizer warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"

class VoucherOCRService:
    def __init__(self):
        """Initialize the Voucher OCR Service for Lambda"""
        print("🔧 Initializing OCR service...")
        print(f"📦 PyMuPDF available: {PYMUPDF_AVAILABLE}")
        
        # Initialize AWS Bedrock client for Claude
        try:
            # Always use us-east-1 for Bedrock (regardless of Lambda region)
            # Bedrock is available in limited regions: us-east-1, us-west-2, eu-west-1, etc.
            bedrock_region = "us-east-1"
            self.bedrock_client = boto3.client(
                service_name='bedrock-runtime',
                region_name=bedrock_region
            )
            # Use cross-region inference profile for Claude Sonnet 4
            # Format: us.anthropic.{model-name}
            # This allows on-demand throughput without provisioning
            self.model_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"
            print(f"✅ AWS Bedrock client initialized (region: {bedrock_region}, model: {self.model_id})")
        except Exception as e:
            print(f"❌ Warning: Failed to initialize AWS Bedrock client: {e}")
            self.bedrock_client = None
            self.model_id = None
        
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
        
        # Zero-shot validation configuration
        self.zero_shot_enabled = True
        self.zero_shot_confidence_threshold = 0.8
        print(f"🔍 Zero-shot validation enabled: {self.zero_shot_enabled} (threshold: {self.zero_shot_confidence_threshold})")
        
        # Lambda doesn't need example images - will use fallback extraction
        self.example_images = {}
        
        # Set base_dir for Lambda (not used in Lambda but needed for compatibility)
        self.base_dir = "/tmp"
    
    def _load_example_images(self):
        """Lambda version - no example images needed, will use fallback extraction"""
        self.example_images = {}
    

    def _encode_image_to_base64(self, image_path):
        """Encode image or PDF to base64 with validation"""
        
        # Verify file exists
        if not os.path.exists(image_path):
            raise FileNotFoundError(f"Image file not found: {image_path}")
        
        # Check file size
        file_size = os.path.getsize(image_path)
        file_ext = os.path.splitext(image_path)[1].lower()
        print(f"📷 Encoding file: {image_path} (size: {file_size} bytes, type: {file_ext})")
        
        if file_size == 0:
            raise ValueError(f"File is empty: {image_path}")
        
        if file_size > 10 * 1024 * 1024:  # 10MB
            print(f"⚠️ Warning: Large file ({file_size / 1024 / 1024:.1f}MB)")
        
        with open(image_path, "rb") as image_file:
            image_data = image_file.read()
            if not image_data:
                raise ValueError(f"Failed to read file data from: {image_path}")
            
            encoded = base64.b64encode(image_data).decode('utf-8')
            print(f"✅ File encoded successfully: {len(encoded)} base64 characters")
            return encoded
    
    def _encode_image(self, image_path):
        """Wrapper for image encoding"""
        return self._encode_image_to_base64(image_path)
    
    def _validate_voucher_with_zero_shot(self, image_path, confidence_threshold=0.8):
        """
        Validate if image/PDF is a voucher/receipt using zero-shot classification
        Classifies into 2 categories: "voucher receipt" or "none voucher receipt"
        
        Args:
            image_path: Path to the image or PDF file
            confidence_threshold: Minimum confidence to consider as voucher (default: 0.8)
        
        Returns:
            dict: {'is_voucher': bool, 'confidence': float, 'reasoning': str, 'category': str}
        """
        temp_image_path = None
        try:
            print(f"🔍 Zero-shot validation: {image_path}")
            
            # Check file type and set appropriate media type
            file_extension = os.path.splitext(image_path)[1].lower().lstrip('.')
            
            # Claude API supports PDF files directly!
            if file_extension == 'pdf':
                print("📄 Processing PDF directly with Claude API")
                validation_path = image_path
                media_type = "application/pdf"
            elif file_extension in ['jpg', 'jpeg']:
                validation_path = image_path
                media_type = "image/jpeg"
            elif file_extension == 'png':
                validation_path = image_path
                media_type = "image/png"
            else:
                # Default to PNG for other formats
                validation_path = image_path
                media_type = "image/png"
            
            # Encode file (works for both images and PDFs)
            base64_image = self._encode_image_to_base64(validation_path)
            
            # Build content array based on file type
            content_items = [
                {
                    "type": "text",
                    "text": """Classify this document/image into exactly ONE of these 2 categories:
1. "voucher receipt" - Invoice, receipt, payment voucher, or financial document
2. "none voucher receipt" - Not a financial document

Respond ONLY with a JSON object in this exact format:
{
    "category": "voucher receipt" or "none voucher receipt",
    "confidence": 0.0-1.0,
    "reasoning": "brief explanation"
}

Category: "voucher receipt"
- Invoice, receipt, payment voucher, or financial transaction document
- Contains transaction details, amounts, dates, document numbers
- Business or official financial document
- Scanned/photographed voucher images or PDF documents

Category: "none voucher receipt"
- Screenshots of applications WITHOUT visible voucher content
- Random photos (landscapes, people, animals, objects)
- Text documents without financial information
- Blank or non-document images
- Any image/document that is NOT a financial document

Important: If a screenshot contains a visible voucher/receipt, classify as "voucher receipt"."""
                }
            ]
            
            # Add document/image content based on media type
            if media_type == "application/pdf":
                # For PDFs, use document type
                content_items.append({
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_image
                    }
                })
            else:
                # For images, use image type
                content_items.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_image
                    }
                })
            
            # Prepare request for Bedrock
            request_body = {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": 500,
                "messages": [{
                    "role": "user",
                    "content": content_items
                }]
            }
            
            # Make Bedrock API call
            response = self.bedrock_client.invoke_model(
                modelId=self.model_id,
                body=json.dumps(request_body)
            )
            
            # Parse response
            result = json.loads(response['body'].read())
            validation_text = result['content'][0]['text']
            print(f"📋 Zero-shot validation response: {validation_text}")
            
            # Parse JSON response
            validation_data = extract_json_from_text(validation_text)
            if validation_data:
                category = validation_data.get('category', 'none voucher receipt')
                confidence = float(validation_data.get('confidence', 0.0))
                reasoning = validation_data.get('reasoning', 'No reasoning provided')
                
                # Determine if it's a voucher based on category
                is_voucher_category = category.lower() == "voucher receipt"
                
                # Apply threshold: treat uncertain as non-voucher
                is_valid = is_voucher_category and confidence >= confidence_threshold
                
                print(f"✅ Zero-shot result: category={category}, confidence={confidence:.2f}, valid={is_valid}")
                
                return {
                    'is_voucher': is_valid,
                    'category': category,
                    'confidence': confidence,
                    'reasoning': reasoning
                }
            else:
                # If no JSON, treat as non-voucher
                print(f"⚠️ Failed to parse zero-shot response")
                return {
                    'is_voucher': False,
                    'category': 'none voucher receipt',
                    'confidence': 0.0,
                    'reasoning': 'Failed to parse validation response'
                }
                    
        except Exception as e:
            error_str = str(e)
            print(f"⚠️ Zero-shot validation error: {e}")
            
            # If it's a throttling error, skip validation and treat as voucher (proceed to OCR)
            # ThrottlingException means we hit rate limits, not that the document is invalid
            if 'ThrottlingException' in error_str or 'Too many requests' in error_str:
                print(f"⚠️ Throttling error detected - skipping validation, proceeding to OCR")
                return {
                    'is_voucher': True,  # Allow processing to continue
                    'category': 'voucher receipt',
                    'confidence': 0.8,  # Default confidence
                    'reasoning': 'Validation skipped due to throttling - proceeding to OCR'
                }
            
            # For other errors, fail safe: treat as non-voucher
            return {
                'is_voucher': False,
                'category': 'none voucher receipt',
                'confidence': 0.0,
                'reasoning': f'Validation error: {str(e)}'
            }
        finally:
            # Clean up temporary image file if it was created for PDF validation
            if temp_image_path and os.path.exists(temp_image_path):
                try:
                    os.unlink(temp_image_path)
                    print(f"🧹 Cleaned up temp validation image: {temp_image_path}")
                except:
                    pass
    
    def _parse_document_date(self, date_str):
        """Parse document date and return year, month, day components"""
        if not date_str:
            now = datetime.now()
            return now.year, now.month, now.day
        
        try:
            # Try different date formats
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
            
            # If no format matches, try to extract components
            # Match patterns like d-m-y or d/m/y
            match = re.match(r'(\d{1,2})[-/](\d{1,2})[-/](\d{2,4})', date_str)
            if match:
                day, month, year = match.groups()
                year = int(year)
                if year < 100:  # Two-digit year
                    year += 2000 if year < 50 else 1900
                return year, int(month), int(day)
            
            # Try y-m-d or y/m/d
            match = re.match(r'(\d{4})[-/](\d{1,2})[-/](\d{1,2})', date_str)
            if match:
                year, month, day = match.groups()
                return int(year), int(month), int(day)
                
        except Exception as e:
            print(f"Error parsing date '{date_str}': {e}")
        
        # Default to current date if parsing fails
        now = datetime.now()
        return now.year, now.month, now.day
    
    def _create_organized_path(self, document_no, document_date, branch_id, voucher_type):
        """Create the organized path structure based on extracted data
        Format: organized_vouchers/year/Branch XX/month/date/type/filename
        """
        try:
            # Parse the date
            year, month, day = self._parse_document_date(document_date)
            
            # Format branch ID (ensure it's 2 digits)
            if branch_id:
                try:
                    branch_num = int(branch_id)
                    branch_folder = f"Branch {branch_num:02d}"
                except:
                    branch_folder = f"Branch {branch_id}"
            else:
                branch_folder = "Branch 01"  # Default
            
            # Get month name
            month_name = self.month_names.get(month, f"month{month:02d}")
            
            # Format date folder
            date_folder = f"{day}-{month}-{year}"
            
            # Ensure voucher type is valid (only create paths for valid voucher types)
            if not voucher_type or voucher_type not in self.voucher_types:
                voucher_type = self._extract_document_no_prefix(document_no)
                if not voucher_type or voucher_type not in self.voucher_types:
                    print(f"⚠️ Invalid voucher type - cannot create organized path")
                    return None  # Don't organize invalid voucher types
            
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
            print(f"Created organized path: {organized_path}")
            
            return organized_path
            
        except Exception as e:
            print(f"❌ Error creating organized path: {e}")
            # Don't create fallback path for UNKNOWN - return None
            return None
    
    def _generate_base_filename(self, transaction_data):
        """Generate base filename from transaction data"""
        try:
            date_match = re.search(r'\d{1,4}[-/]\d{1,2}[-/]\d{1,4}', transaction_data)
            if date_match:
                date_str = date_match.group().replace('/', '-')
            else:
                date_str = datetime.now().strftime('%Y-%m-%d')
        except (TypeError, AttributeError, ValueError):
            date_str = datetime.now().strftime('%Y-%m-%d')
        
        timestamp = datetime.now().strftime('%H%M%S')
        return f"voucher_{date_str}_{timestamp}"
    
    def _extract_document_no_prefix(self, document_no):
        """Extract the prefix from Document No (e.g., MPU from MPU01-85285)"""
        if not document_no:
            return None
        
        # Extract prefix before the first number
        match = re.match(r'^([A-Z]+)', document_no.strip())
        if match:
            prefix = match.group(1)
            return prefix if prefix in self.voucher_types else None
        return None
    
    def _create_voucher_folder(self, document_no_prefix):
        """Create folder for the voucher type if it doesn't exist"""
        if not document_no_prefix or document_no_prefix not in self.voucher_types:
            return None
        
        folder_name = self.voucher_types[document_no_prefix]
        folder_path = os.path.join(self.base_dir, "organized_vouchers", folder_name)
        os.makedirs(folder_path, exist_ok=True)
        return folder_path
    
    def _sanitize_document_no(self, document_no):
        """Sanitize document number for safe filenames"""
        if not document_no:
            return None
        try:
            sanitized = re.sub(r"[^A-Za-z0-9_-]+", "", str(document_no))
            return sanitized or None
        except Exception:
            return None

    def _extract_branch_digits_from_doc_no(self, document_no):
        """Extract branch digits from document number like MPU01-85285 -> '01'"""
        if not document_no:
            return None
        m = re.match(r"^[A-Z]+(\d{1,3})", document_no.strip())
        if m:
            digits = m.group(1)
            if len(digits) >= 2:
                return digits
            try:
                return f"{int(digits):02d}"
            except Exception:
                return digits
        return None

    def _process_image(self, file_path, output_folder="converted_images"):
        """Process uploaded image or PDF"""
        os.makedirs(output_folder, exist_ok=True)
        
        file_extension = os.path.splitext(file_path)[1].lower().lstrip('.')
        
        try:
            if file_extension in {"jpg", "jpeg", "png"}:
                # Verify the image can be opened and re-save to ensure it's valid
                with Image.open(file_path) as img:
                    # Convert to RGB if necessary (for JPEG compatibility)
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    # Save the processed image
                    processed_path = os.path.join(output_folder, f"processed_{os.path.basename(file_path)}")
                    img.save(processed_path)
                    return processed_path
                    
            elif file_extension == "pdf":
                doc = fitz.open(file_path)
                page = doc.load_page(0)
                pix = page.get_pixmap()
                output_path = os.path.join(output_folder, f"converted_page_1.png")
                pix.save(output_path)
                doc.close()
                return output_path
                
        except (OSError, IOError, ValueError) as e:
            print(f"Error processing image: {e}")
            return None
        
        return None
    
    def _extract_pdf_pages(self, pdf_path):
        """Extract all pages from PDF as temporary PNG files"""
        if not PYMUPDF_AVAILABLE:
            raise Exception("PyMuPDF not available")
        
        import tempfile
        temp_dir = tempfile.mkdtemp()
        extracted_pages = []
        
        doc = fitz.open(pdf_path)
        print(f"📄 PDF has {len(doc)} pages")
        
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(dpi=150)
            page_path = os.path.join(temp_dir, f"page_{page_num + 1}.png")
            pix.save(page_path)
            extracted_pages.append((page_num + 1, page_path))
        
        doc.close()
        return extracted_pages
    
    def _extract_transaction_data(self, image_path):
        """Extract transaction data using OCR only - no filename fallback"""
        
        # If Bedrock client is missing, fail immediately with clear error
        if not self.bedrock_client:
            raise Exception("OCR_API_KEY_MISSING: AWS Bedrock client is not configured")
        
        import time
        
        max_retries = 1
        retry_delay = 30  # seconds
        
        for attempt in range(max_retries + 1):
            try:
                print(f"Attempting Anthropic OCR via REST API (attempt {attempt + 1})...")
                print(f"📄 Image path: {image_path}")
                
                # Verify image exists before encoding
                if not os.path.exists(image_path):
                    raise FileNotFoundError(f"Image file does not exist: {image_path}")
                
                base64_image = self._encode_image_to_base64(image_path)
                
                # Determine the correct media type based on file extension
                file_extension = os.path.splitext(image_path)[1].lower().lstrip('.')
                print(f"📋 File extension: {file_extension}")
                
                if file_extension in ['jpg', 'jpeg']:
                    media_type = "image/jpeg"
                elif file_extension == 'png':
                    media_type = "image/png"
                elif file_extension == 'pdf':
                    media_type = "application/pdf"  # Claude API supports PDF directly!
                    print("📄 Using PDF media type for direct processing")
                else:
                    media_type = "image/png"  # default fallback
                
                print(f"📋 Media type: {media_type}")
                print(f"📋 Base64 length: {len(base64_image)} characters")
                
                # Build content based on file type
                if media_type == "application/pdf":
                    doc_content_type = "document"
                    doc_or_image_text = "document/voucher"
                else:
                    doc_content_type = "image"
                    doc_or_image_text = "voucher image"
                
                # Prepare request for Bedrock
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
                
                # Prepare request body for Bedrock
                request_body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": messages
                }
                
                # Make Bedrock API call
                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(request_body)
                )
                
                # Parse response
                result = json.loads(response['body'].read())
                ocr_result = result['content'][0]['text']
                print(f"Bedrock OCR result: {ocr_result}")
                return ocr_result
                
            except Exception as e:
                error_message = str(e)
                print(f"OCR attempt {attempt + 1} failed: {error_message}")
                
                if attempt < max_retries:
                    print(f"Generic error occurred. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"OCR_FAILED: {error_message}")
    
    def _convert_image_to_pdf(self, image_path):
        """Convert image to PDF format using custom pure Python converter (NO dependencies!)"""
        try:
            import struct
            import zlib
            
            # Create PDF file path
            pdf_path = image_path.rsplit('.', 1)[0] + '_0001.pdf'
            
            print(f"🔄 Converting {image_path} to PDF using pure Python...")
            
            # Read image file
            with open(image_path, 'rb') as f:
                image_bytes = f.read()
            
            if len(image_bytes) == 0:
                print("❌ Image file is empty")
                return None
            
            # Get image dimensions and prepare data
            if image_bytes[0:2] == b'\xff\xd8':  # JPEG
                try:
                    width, height = self._get_jpeg_dimensions(image_bytes)
                    filter_type = '/DCTDecode'
                    colorspace = '/DeviceRGB'
                    bpc = 8
                    image_data = image_bytes  # JPEG can be embedded directly
                    print(f"📐 JPEG image: {width}x{height}")
                except Exception as jpeg_error:
                    print(f"❌ Failed to parse JPEG: {jpeg_error}")
                    print("⚠️ Keeping original file instead of converting to PDF")
                    return None
                
            elif image_bytes[0:8] == b'\x89PNG\r\n\x1a\n':  # PNG
                width = struct.unpack('>I', image_bytes[16:20])[0]
                height = struct.unpack('>I', image_bytes[20:24])[0]
                bit_depth = image_bytes[24]
                color_type = image_bytes[25]
                
                print(f"📐 PNG image: {width}x{height}, bit_depth={bit_depth}, color_type={color_type}")
                
                # Extract IDAT chunks (compressed image data)
                image_data = self._extract_png_idat(image_bytes)
                
                if not image_data:
                    raise ValueError("Failed to extract PNG image data")
                
                # Determine colorspace based on color type
                if color_type == 0:  # Grayscale
                    colorspace = '/DeviceGray'
                    components = 1
                elif color_type == 2:  # RGB
                    colorspace = '/DeviceRGB'
                    components = 3
                elif color_type == 3:  # Indexed
                    colorspace = '/DeviceRGB'
                    components = 3
                elif color_type == 4:  # Grayscale + Alpha
                    colorspace = '/DeviceGray'
                    components = 1
                elif color_type == 6:  # RGBA
                    colorspace = '/DeviceRGB'
                    components = 3
                else:
                    colorspace = '/DeviceRGB'
                    components = 3
                
                filter_type = '/FlateDecode'
                bpc = bit_depth
                
                print(f"📊 PNG data extracted: {len(image_data)} bytes, colorspace={colorspace}")
                
            else:
                raise ValueError("Unsupported image format (only JPEG and PNG supported)")
            
            # Create minimal PDF with embedded image
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
            
            # Add PNG-specific parameters
            if filter_type == '/FlateDecode':
                pdf_content.append(b'/Filter /FlateDecode ')
                # Add predictor for PNG
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
            
            # Verify
            if os.path.exists(pdf_path):
                pdf_size = os.path.getsize(pdf_path)
                print(f"✅ Successfully converted to PDF: {pdf_path} ({pdf_size} bytes)")
                return pdf_path
            else:
                print(f"❌ PDF file was not created")
                return None
                
        except Exception as e:
            print(f"❌ Error converting to PDF: {e}")
            import traceback
            traceback.print_exc()
            return None
    
    def _extract_png_idat(self, png_bytes):
        """Extract and combine all IDAT chunks from PNG"""
        import struct
        
        if png_bytes[0:8] != b'\x89PNG\r\n\x1a\n':
            return None
        
        idat_data = b''
        pos = 8  # Skip PNG signature
        
        while pos < len(png_bytes):
            if pos + 8 > len(png_bytes):
                break
            
            # Read chunk length and type
            chunk_length = struct.unpack('>I', png_bytes[pos:pos+4])[0]
            chunk_type = png_bytes[pos+4:pos+8]
            
            # If this is an IDAT chunk, extract its data
            if chunk_type == b'IDAT':
                chunk_data = png_bytes[pos+8:pos+8+chunk_length]
                idat_data += chunk_data
            
            # If we hit IEND, we're done
            if chunk_type == b'IEND':
                break
            
            # Move to next chunk (length + type + data + CRC)
            pos += 4 + 4 + chunk_length + 4
        
        return idat_data if idat_data else None
    
    def _get_jpeg_dimensions(self, jpeg_bytes):
        """Extract width and height from JPEG without any libraries - ROBUST VERSION"""
        try:
            i = 0
            # Verify JPEG header
            if jpeg_bytes[0:2] != b'\xff\xd8':
                raise ValueError("Not a valid JPEG file (missing SOI marker)")
            
            i = 2  # Skip SOI marker
            
            while i < len(jpeg_bytes) - 10:  # Need at least 10 bytes for dimension reading
                # Find next marker
                if jpeg_bytes[i] != 0xFF:
                    i += 1
                    continue
                
                # Skip padding bytes
                while i < len(jpeg_bytes) and jpeg_bytes[i] == 0xFF:
                    i += 1
                
                if i >= len(jpeg_bytes):
                    break
                    
                marker = jpeg_bytes[i]
                i += 1
                
                # Check if this is a SOF (Start Of Frame) marker
                # SOF markers: 0xC0-0xCF except 0xC4 (DHT), 0xC8 (JPG), 0xCC (DAC)
                if 0xC0 <= marker <= 0xCF and marker not in [0xC4, 0xC8, 0xCC]:
                    # Found SOF marker - read dimensions
                    if i + 5 < len(jpeg_bytes):
                        # Skip length (2 bytes) and precision (1 byte)
                        i += 3
                        # Read height and width
                        height = (jpeg_bytes[i] << 8) | jpeg_bytes[i+1]
                        width = (jpeg_bytes[i+2] << 8) | jpeg_bytes[i+3]
                        print(f"✅ JPEG dimensions found: {width}x{height}")
                        return width, height
                
                # Skip to next segment
                if i + 1 < len(jpeg_bytes):
                    # Read segment length
                    length = (jpeg_bytes[i] << 8) | jpeg_bytes[i+1]
                    i += length
                else:
                    break
            
            raise ValueError("Could not find JPEG dimensions (no SOF marker found)")
            
        except Exception as e:
            print(f"❌ Error parsing JPEG dimensions: {e}")
            raise ValueError(f"Could not find JPEG dimensions: {e}")
    
    def _extract_first_page_only(self, pdf_path, output_path):
        """Extract ONLY the first page from a PDF - byte-for-byte copy to preserve quality"""
        try:
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            
            # Strategy: Find and manually parse the first image object to handle nested dictionaries
            # Standard regex fails because DecodeParms contains << >> which confuses non-greedy matching
            
            # Find start of first image object
            start_pattern = rb'(\d+)\s+0\s+obj\s*<<\s*/Type\s*/XObject\s*/Subtype\s*/Image\s*'
            start_match = re.search(start_pattern, pdf_data)
            if not start_match:
                print(f"  ⚠️ Could not find image object, copying entire PDF")
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            
            obj_num = start_match.group(1)
            dict_start = start_match.end()
            
            # Manually find the matching >> for the dictionary (handling nested << >>)
            depth = 1  # We're already inside the outer <<
            dict_end = dict_start
            while dict_end < len(pdf_data) and depth > 0:
                if pdf_data[dict_end:dict_end+2] == b'<<':
                    depth += 1
                    dict_end += 2
                elif pdf_data[dict_end:dict_end+2] == b'>>':
                    depth -= 1
                    dict_end += 2
                else:
                    dict_end += 1
            
            if depth != 0:
                print(f"  ⚠️ Could not parse dictionary, copying entire PDF")
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            
            # Extract the complete dictionary content
            obj_dict = pdf_data[dict_start:dict_end-2]  # -2 to exclude the final >>
            
            # Find stream data
            stream_marker = b'>>\nstream\n'
            stream_start_pos = pdf_data.find(stream_marker, start_match.start())
            if stream_start_pos == -1:
                print(f"  ⚠️ Could not find stream, copying entire PDF")
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            
            stream_start = stream_start_pos + len(stream_marker)
            # Use /Length from dictionary to extract exact stream bytes
            length_match = re.search(rb'/Length\s+(\d+)', obj_dict)
            if not length_match:
                print(f"  ⚠️ Could not find /Length, copying entire PDF")
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            stream_length = int(length_match.group(1))
            stream_end = stream_start + stream_length
            if stream_end > len(pdf_data):
                print(f"  ⚠️ Stream length exceeds file size, copying entire PDF")
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            
            stream_data = pdf_data[stream_start:stream_end]
            
            # Parse width and height from dict for page size
            width_match = re.search(rb'/Width\s+(\d+)', obj_dict)
            height_match = re.search(rb'/Height\s+(\d+)', obj_dict)
            
            if not (width_match and height_match):
                print(f"  ⚠️ Could not parse dimensions, copying entire PDF")
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            
            width = int(width_match.group(1))
            height = int(height_match.group(1))
            
            # Build PDF using the EXACT original object (byte-for-byte copy)
            # This preserves all compression, filtering, and decode params perfectly
            pdf_content = []
            pdf_content.append(b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
            
            # Object 1: Catalog
            pdf_content.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
            
            # Object 2: Pages
            pdf_content.append(b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n')
            
            # Object 3: Page
            page_obj = f'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>\nendobj\n'.encode()
            pdf_content.append(page_obj)
            
            # Object 4: Content stream
            stream = f'q\n{width} 0 0 {height} 0 0 cm\n/Im1 Do\nQ\n'.encode()
            content_obj = f'4 0 obj\n<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream\nendobj\n'
            pdf_content.append(content_obj)
            
            # Object 5: Image - USE EXACT BYTES FROM SOURCE (including all dict entries)
            # Rebuild the object with renumbered ID but exact same dict and stream
            image_obj = b'5 0 obj\n<< /Type /XObject /Subtype /Image ' + obj_dict + b'>>\nstream\n' + stream_data + b'\nendstream\nendobj\n'
            pdf_content.append(image_obj)
            
            print(f"  ✅ Extracted first page using byte-for-byte copy: {width}x{height}, {len(stream_data)} bytes")
            
            # Cross-reference table
            xref_start = len(b''.join(pdf_content))
            xref = b'xref\n0 6\n0000000000 65535 f \n'
            
            # Calculate offsets
            offset = 0
            for chunk in pdf_content:
                xref += f'{offset:010d} 00000 n \n'.encode()
                offset += len(chunk)
            
            pdf_content.append(xref)
            
            # Trailer
            trailer = f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n'.encode()
            pdf_content.append(trailer)
            
            # Write single-page PDF
            with open(output_path, 'wb') as f:
                for chunk in pdf_content:
                    f.write(chunk)
            
            return output_path
            
        except Exception as e:
            print(f"  ❌ Error extracting first page: {e}")
            import traceback
            traceback.print_exc()
            # Fallback: copy entire PDF
            try:
                with open(pdf_path, 'rb') as f:
                    pdf_data = f.read()
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            except:
                raise
    
    def _extract_images_from_pdf(self, pdf_path):
        """Extract ALL embedded images from a PDF (handles multi-page PDFs)"""
        try:
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            
            # Find all /XObject /Image entries - extract full object dictionary
            # We need to capture ColorSpace, BitsPerComponent, Filter, and DecodeParms
            image_pattern = rb'(\d+)\s+0\s+obj\s*<<\s*/Type\s*/XObject\s*/Subtype\s*/Image\s*(.*?)>>\s*stream\n'
            
            images = []
            pos = 0
            
            while True:
                match = re.search(image_pattern, pdf_data[pos:], re.DOTALL)
                if not match:
                    break
                
                obj_num = match.group(1).decode()
                obj_dict = match.group(2)
                
                # Extract parameters from the object dictionary
                width_match = re.search(rb'/Width\s+(\d+)', obj_dict)
                height_match = re.search(rb'/Height\s+(\d+)', obj_dict)
                filter_match = re.search(rb'/Filter\s*/(\w+)', obj_dict)
                colorspace_match = re.search(rb'/ColorSpace\s*/(\w+)', obj_dict)
                bpc_match = re.search(rb'/BitsPerComponent\s+(\d+)', obj_dict)
                
                # Extract DecodeParms if present - more robust pattern
                # Handles both: /DecodeParms << ... >> and /DecodeParms <</...>>
                decode_params_dict = None
                decode_params_match = re.search(rb'/DecodeParms\s*<<([^>]*?)>>', obj_dict, re.DOTALL)
                if decode_params_match:
                    # Extract the full DecodeParms dictionary content
                    params_content = decode_params_match.group(1).decode(errors='ignore').strip()
                    decode_params_dict = f'<< {params_content} >>'
                    print(f"  📊 Found DecodeParms: {decode_params_dict}")
                
                if not (width_match and height_match):
                    pos += match.end()
                    continue
                
                width = int(width_match.group(1))
                height = int(height_match.group(1))
                filter_type = filter_match.group(1).decode() if filter_match else None
                colorspace = colorspace_match.group(1).decode() if colorspace_match else 'DeviceRGB'
                bpc = int(bpc_match.group(1)) if bpc_match else 8
                
                # Find the stream data for this image using /Length
                stream_marker = b'>>\nstream\n'
                stream_pos = pdf_data.find(stream_marker, pos + match.start())
                if stream_pos == -1:
                    pos += match.end()
                    continue
                stream_start = stream_pos + len(stream_marker)
                length_match = re.search(rb'/Length\s+(\d+)', obj_dict)
                if not length_match:
                    pos += match.end()
                    continue
                stream_length = int(length_match.group(1))
                stream_end = stream_start + stream_length
                if stream_end > len(pdf_data):
                    pos += match.end()
                    continue
                
                if stream_end > stream_start:
                    image_data = pdf_data[stream_start:stream_end]
                    
                    is_png = filter_type == 'FlateDecode'
                    is_jpeg = filter_type == 'DCTDecode'
                    
                    # Only include large streams (actual images, not small content streams)
                    if len(image_data) > 1000:
                        images.append({
                            'data': image_data,
                            'width': width,
                            'height': height,
                            'is_png': is_png,
                            'is_jpeg': is_jpeg,
                            'filter': filter_type,
                            'colorspace': colorspace,
                            'bpc': bpc,
                            'decode_params': decode_params_dict
                        })
                        log_msg = f"  Extracted image {len(images)}: {len(image_data)} bytes, {width}x{height}, filter={filter_type}, colorspace={colorspace}, bpc={bpc}"
                        if decode_params_dict:
                            log_msg += f", decode_params={decode_params_dict}"
                        print(log_msg)
                    
                    # Move position to after endstream marker
                    end_marker_pos = pdf_data.find(b'endstream', stream_end)
                    if end_marker_pos == -1:
                        pos = stream_end
                    else:
                        pos = end_marker_pos + len(b'endstream')
                else:
                    pos += match.end()
            
            if images:
                print(f"  ✅ Extracted {len(images)} image(s) from PDF with full parameters")
                return images
            
            return []
            
        except Exception as e:
            print(f"  ⚠️ Could not extract images from PDF: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _extract_png_from_pdf(self, pdf_path, output_dir):
        """Extract all pages from PDF as PNG images"""
        try:
            print(f"🖼️ Extracting PNG images from PDF: {pdf_path}")
            
            with open(pdf_path, 'rb') as f:
                pdf_data = f.read()
            
            # Find all image objects
            image_pattern = rb'(\d+)\s+0\s+obj\s*<<\s*/Type\s*/XObject\s*/Subtype\s*/Image\s*(.*?)>>\s*stream\n'
            
            png_files = []
            pos = 0
            page_num = 1
            
            while True:
                match = re.search(image_pattern, pdf_data[pos:], re.DOTALL)
                if not match:
                    break
                
                obj_dict = match.group(2)
                
                # Extract image parameters
                width_match = re.search(rb'/Width\s+(\d+)', obj_dict)
                height_match = re.search(rb'/Height\s+(\d+)', obj_dict)
                
                if not (width_match and height_match):
                    pos += match.end()
                    continue
                
                # Find stream data using /Length
                stream_marker = b'>>\nstream\n'
                stream_pos = pdf_data.find(stream_marker, pos + match.start())
                if stream_pos == -1:
                    pos += match.end()
                    continue
                
                stream_start = stream_pos + len(stream_marker)
                length_match = re.search(rb'/Length\s+(\d+)', obj_dict)
                if not length_match:
                    pos += match.end()
                    continue
                
                stream_length = int(length_match.group(1))
                stream_end = stream_start + stream_length
                if stream_end > len(pdf_data):
                    pos += match.end()
                    continue
                
                image_data = pdf_data[stream_start:stream_end]
                
                # Only process large streams (actual images)
                if len(image_data) > 1000:
                    # Save as PNG file
                    import struct
                    import zlib
                    
                    width = int(width_match.group(1))
                    height = int(height_match.group(1))
                    
                    # Build PNG from the compressed data
                    png_path = f"{output_dir}/page_{page_num:04d}.png"
                    
                    # Create PNG header
                    png_data = b'\x89PNG\r\n\x1a\n'
                    
                    # IHDR chunk
                    ihdr = struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0)  # RGB, 8-bit
                    png_data += struct.pack('>I', 13) + b'IHDR' + ihdr
                    png_data += struct.pack('>I', zlib.crc32(b'IHDR' + ihdr) & 0xffffffff)
                    
                    # IDAT chunk (use extracted data directly)
                    png_data += struct.pack('>I', len(image_data)) + b'IDAT' + image_data
                    png_data += struct.pack('>I', zlib.crc32(b'IDAT' + image_data) & 0xffffffff)
                    
                    # IEND chunk
                    png_data += struct.pack('>I', 0) + b'IEND'
                    png_data += struct.pack('>I', zlib.crc32(b'IEND') & 0xffffffff)
                    
                    # Write PNG file
                    with open(png_path, 'wb') as f:
                        f.write(png_data)
                    
                    png_files.append(png_path)
                    print(f"  ✅ Extracted page {page_num}: {width}x{height} → {png_path}")
                    page_num += 1
                
                pos = stream_end + len(b'endstream')
            
            print(f"  ✅ Extracted {len(png_files)} PNG image(s) from PDF")
            return png_files
            
        except Exception as e:
            print(f"  ❌ Error extracting PNG from PDF: {e}")
            import traceback
            traceback.print_exc()
            return []
    
    def _merge_png_images_to_pdf(self, png_paths, output_path):
        """Merge multiple PNG images into a single multi-page PDF - DIRECT image embedding"""
        try:
            import struct
            
            print(f"🔀 Merging {len(png_paths)} PNG images into multi-page PDF...")
            
            if not png_paths:
                raise ValueError("No PNG images to merge")
            
            if len(png_paths) == 1:
                # Single image - convert to PDF
                return self._convert_image_to_pdf(png_paths[0])
            
            # Process each PNG to extract dimensions and prepare data
            pages_data = []
            for i, png_path in enumerate(png_paths):
                print(f"  Processing PNG {i+1}/{len(png_paths)}: {png_path}")
                
                with open(png_path, 'rb') as f:
                    png_bytes = f.read()
                
                if png_bytes[0:8] != b'\x89PNG\r\n\x1a\n':
                    print(f"  ⚠️ File is not PNG, skipping: {png_path}")
                    continue
                
                # Parse PNG dimensions
                width = struct.unpack('>I', png_bytes[16:20])[0]
                height = struct.unpack('>I', png_bytes[20:24])[0]
                bit_depth = png_bytes[24]
                color_type = png_bytes[25]
                
                # Extract IDAT data
                idat_data = self._extract_png_idat(png_bytes)
                if not idat_data:
                    print(f"  ⚠️ Failed to extract IDAT, skipping: {png_path}")
                    continue
                
                # Determine colorspace
                if color_type == 0:  # Grayscale
                    colorspace = '/DeviceGray'
                    components = 1
                elif color_type == 2:  # RGB
                    colorspace = '/DeviceRGB'
                    components = 3
                else:
                    colorspace = '/DeviceRGB'
                    components = 3
                
                pages_data.append({
                    'width': width,
                    'height': height,
                    'data': idat_data,
                    'colorspace': colorspace,
                    'bpc': bit_depth,
                    'components': components
                })
                print(f"    ✅ Prepared page {i+1}: {width}x{height}, {len(idat_data)} bytes")
            
            if not pages_data:
                raise ValueError("No valid PNG images to merge")
            
            # Build multi-page PDF
            print(f"📄 Building {len(pages_data)}-page PDF from PNG images...")
            pdf_content = []
            pdf_content.append(b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
            
            num_pages = len(pages_data)
            obj_offsets = [0]  # Placeholder
            
            # Object 1: Catalog
            obj_offsets.append(len(b''.join(pdf_content)))
            pdf_content.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
            
            # Object 2: Pages
            obj_offsets.append(len(b''.join(pdf_content)))
            page_refs = ' '.join([f'{3+i} 0 R' for i in range(num_pages)])
            pdf_content.append(f'2 0 obj\n<< /Type /Pages /Kids [{page_refs}] /Count {num_pages} >>\nendobj\n'.encode())
            
            # Create page objects
            for i in range(num_pages):
                page = pages_data[i]
                page_obj_num = 3 + i
                content_obj_num = 3 + num_pages + i
                image_obj_num = 3 + 2*num_pages + i
                
                obj_offsets.append(len(b''.join(pdf_content)))
                page_obj = f'{page_obj_num} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {page["width"]} {page["height"]}] /Contents {content_obj_num} 0 R /Resources << /XObject << /Im1 {image_obj_num} 0 R >> >> >>\nendobj\n'.encode()
                pdf_content.append(page_obj)
            
            # Create content streams
            for i in range(num_pages):
                page = pages_data[i]
                content_obj_num = 3 + num_pages + i
                
                obj_offsets.append(len(b''.join(pdf_content)))
                stream = f'q\n{page["width"]} 0 0 {page["height"]} 0 0 cm\n/Im1 Do\nQ\n'.encode()
                content_obj = f'{content_obj_num} 0 obj\n<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream\nendobj\n'
                pdf_content.append(content_obj)
            
            # Create image objects
            for i in range(num_pages):
                page = pages_data[i]
                image_obj_num = 3 + 2*num_pages + i
                
                obj_offsets.append(len(b''.join(pdf_content)))
                
                # Embed PNG data with proper parameters
                image_obj_header = f'{image_obj_num} 0 obj\n<< /Type /XObject /Subtype /Image /Width {page["width"]} /Height {page["height"]} /ColorSpace {page["colorspace"]} /BitsPerComponent {page["bpc"]} /Filter /FlateDecode /DecodeParms << /Predictor 15 /Colors {page["components"]} /BitsPerComponent {page["bpc"]} /Columns {page["width"]} >> /Length {len(page["data"])} >>\nstream\n'
                
                image_obj = image_obj_header.encode() + page['data'] + b'\nendstream\nendobj\n'
                pdf_content.append(image_obj)
            
            # Cross-reference table
            xref_start = len(b''.join(pdf_content))
            total_objects = 3 + 3*num_pages
            xref = f'xref\n0 {total_objects}\n0000000000 65535 f \n'.encode()
            for offset in obj_offsets[1:]:
                xref += f'{offset:010d} 00000 n \n'.encode()
            pdf_content.append(xref)
            
            # Trailer
            trailer = f'trailer\n<< /Size {total_objects} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n'.encode()
            pdf_content.append(trailer)
            
            # Write merged PDF
            with open(output_path, 'wb') as f:
                for chunk in pdf_content:
                    f.write(chunk)
            
            final_size = sum(len(c) for c in pdf_content)
            print(f"✅ Created {num_pages}-page PDF from PNG images: {output_path} ({final_size} bytes)")
            return output_path
            
        except Exception as e:
            print(f"❌ Error merging PNG images: {e}")
            import traceback
            traceback.print_exc()
            raise
    
    def _merge_pdfs(self, pdf_paths, output_path):
        """Merge multiple PDFs by extracting images and creating a new multi-page PDF"""
        try:
            print(f"🔀 Merging {len(pdf_paths)} PDFs by extracting and rebuilding...")
            
            if len(pdf_paths) == 0:
                raise ValueError("No PDF files to merge")
            
            if len(pdf_paths) == 1:
                # Only one PDF, just copy it
                with open(pdf_paths[0], 'rb') as f:
                    pdf_data = f.read()
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                print(f"✅ Single PDF copied: {output_path}")
                return output_path
            
            # Extract ALL images from all PDFs (handles multi-page PDFs)
            images = []
            for i, pdf_path in enumerate(pdf_paths):
                print(f"  Extracting from PDF {i+1}/{len(pdf_paths)}: {pdf_path}")
                extracted_images = self._extract_images_from_pdf(pdf_path)
                
                # Process each extracted image - use parameters from source PDF AS-IS
                for image_info in extracted_images:
                    if image_info and image_info.get('width') and image_info.get('height'):
                        # Log what we're adding
                        log_msg = f"    ✅ Added image: {image_info['width']}x{image_info['height']}, filter={image_info.get('filter')}, colorspace={image_info.get('colorspace')}, bpc={image_info.get('bpc', 8)}"
                        if image_info.get('decode_params'):
                            log_msg += f", decode_params={image_info['decode_params']}"
                        print(log_msg)
                        images.append(image_info)
            
            if not images:
                # Fallback: just copy first PDF if we can't extract images
                print(f"⚠️ Could not extract images, using first PDF only")
                with open(pdf_paths[0], 'rb') as f:
                    pdf_data = f.read()
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            
            # Build multi-page PDF
            print(f"📄 Building multi-page PDF with {len(images)} pages...")
            pdf_content = []
            pdf_content.append(b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n')
            
            # Calculate object numbers
            num_pages = len(images)
            # Object 1: Catalog
            # Object 2: Pages
            # Object 3+: Page objects (one per page)
            # Object 3+num_pages+: Content streams (one per page)
            # Object 3+2*num_pages+: Image objects (one per page)
            
            # Track object offsets
            obj_offsets = [0]  # Placeholder for object 0
            
            # Object 1: Catalog
            obj_offsets.append(len(b''.join(pdf_content)))
            pdf_content.append(b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n')
            
            # Object 2: Pages with all page references
            obj_offsets.append(len(b''.join(pdf_content)))
            page_refs = ' '.join([f'{3+i} 0 R' for i in range(num_pages)])
            pdf_content.append(f'2 0 obj\n<< /Type /Pages /Kids [{page_refs}] /Count {num_pages} >>\nendobj\n'.encode())
            
            # Create page objects
            for i in range(num_pages):
                img = images[i]
                page_obj_num = 3 + i
                content_obj_num = 3 + num_pages + i
                image_obj_num = 3 + 2*num_pages + i
                
                obj_offsets.append(len(b''.join(pdf_content)))
                page_obj = f'{page_obj_num} 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {img["width"]} {img["height"]}] /Contents {content_obj_num} 0 R /Resources << /XObject << /Im1 {image_obj_num} 0 R >> >> >>\nendobj\n'.encode()
                pdf_content.append(page_obj)
            
            # Create content stream objects
            for i in range(num_pages):
                img = images[i]
                content_obj_num = 3 + num_pages + i
                
                obj_offsets.append(len(b''.join(pdf_content)))
                stream = f'q\n{img["width"]} 0 0 {img["height"]} 0 0 cm\n/Im1 Do\nQ\n'.encode()
                content_obj = f'{content_obj_num} 0 obj\n<< /Length {len(stream)} >>\nstream\n'.encode() + stream + b'\nendstream\nendobj\n'
                pdf_content.append(content_obj)
            
            # Create image objects
            for i in range(num_pages):
                img = images[i]
                image_obj_num = 3 + 2*num_pages + i
                
                obj_offsets.append(len(b''.join(pdf_content)))
                
                # Build image object using extracted parameters from source PDF
                colorspace_str = img.get('colorspace', 'DeviceRGB')
                if not colorspace_str.startswith('/'):
                    colorspace_str = f'/{colorspace_str}'
                
                filter_str = img.get('filter', 'DCTDecode')
                if not filter_str.startswith('/'):
                    filter_str = f'/{filter_str}'
                
                image_obj_header = f'{image_obj_num} 0 obj\n<< /Type /XObject /Subtype /Image /Width {img["width"]} /Height {img["height"]} /ColorSpace {colorspace_str} /BitsPerComponent {img.get("bpc", 8)} /Filter {filter_str} '
                
                # Add decode parameters if present in source (CRITICAL for PNG images)
                if img.get('decode_params'):
                    image_obj_header += f'/DecodeParms {img["decode_params"]} '
                    print(f"  📊 Including DecodeParms for page {i+1}: {img['decode_params']}")
                
                image_obj_header += f'/Length {len(img["data"])} >>\nstream\n'
                
                image_obj = image_obj_header.encode()
                image_obj += img['data']
                image_obj += b'\nendstream\nendobj\n'
                pdf_content.append(image_obj)
            
            # Cross-reference table
            xref_start = len(b''.join(pdf_content))
            total_objects = 3 + 3*num_pages
            xref = f'xref\n0 {total_objects}\n0000000000 65535 f \n'.encode()
            for offset in obj_offsets[1:]:
                xref += f'{offset:010d} 00000 n \n'.encode()
            pdf_content.append(xref)
            
            # Trailer
            trailer = f'trailer\n<< /Size {total_objects} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n'.encode()
            pdf_content.append(trailer)
            
            # Write merged PDF
            with open(output_path, 'wb') as f:
                for chunk in pdf_content:
                    f.write(chunk)
            
            final_size = sum(len(c) for c in pdf_content)
            print(f"✅ Created {num_pages}-page PDF: {output_path} ({final_size} bytes)")
            return output_path
            
        except Exception as e:
            print(f"❌ Error merging PDFs: {e}")
            import traceback
            traceback.print_exc()
            # Fallback: copy first PDF
            print(f"⚠️ Falling back to first PDF only")
            try:
                with open(pdf_paths[0], 'rb') as f:
                    pdf_data = f.read()
                with open(output_path, 'wb') as f:
                    f.write(pdf_data)
                return output_path
            except:
                raise
    
    def _create_pdf_from_jpeg(self, jpeg_bytes, width, height):
        """Create a minimal PDF with embedded JPEG image"""
        # PDF header
        pdf_content = b'%PDF-1.4\n%\xE2\xE3\xCF\xD3\n'
        
        # Object 1: Catalog
        obj1_start = len(pdf_content)
        pdf_content += b'1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n'
        
        # Object 2: Pages
        obj2_start = len(pdf_content)
        pdf_content += b'2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n'
        
        # Object 3: Page
        obj3_start = len(pdf_content)
        page_content = f'3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {width} {height}] /Contents 4 0 R /Resources << /XObject << /Im1 5 0 R >> >> >>\nendobj\n'
        pdf_content += page_content.encode('latin-1')
        
        # Object 4: Content stream
        obj4_start = len(pdf_content)
        stream = f'q\n{width} 0 0 {height} 0 0 cm\n/Im1 Do\nQ\n'
        stream_data = stream.encode('latin-1')
        content_obj = f'4 0 obj\n<< /Length {len(stream_data)} >>\nstream\n'.encode('latin-1')
        content_obj += stream_data
        content_obj += b'\nendstream\nendobj\n'
        pdf_content += content_obj
        
        # Object 5: Image
        obj5_start = len(pdf_content)
        image_obj = f'5 0 obj\n<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace /DeviceRGB /BitsPerComponent 8 /Filter /DCTDecode /Length {len(jpeg_bytes)} >>\nstream\n'.encode('latin-1')
        image_obj += jpeg_bytes
        image_obj += b'\nendstream\nendobj\n'
        pdf_content += image_obj
        
        # Cross-reference table
        xref_start = len(pdf_content)
        xref = b'xref\n0 6\n0000000000 65535 f \n'
        xref += f'{obj1_start:010d} 00000 n \n'.encode('latin-1')
        xref += f'{obj2_start:010d} 00000 n \n'.encode('latin-1')
        xref += f'{obj3_start:010d} 00000 n \n'.encode('latin-1')
        xref += f'{obj4_start:010d} 00000 n \n'.encode('latin-1')
        xref += f'{obj5_start:010d} 00000 n \n'.encode('latin-1')
        pdf_content += xref
        
        # Trailer
        trailer = f'trailer\n<< /Size 6 /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n'.encode('latin-1')
        pdf_content += trailer
        
        return pdf_content
    
    def process_voucher_simple(self, image_path, original_filename=None):
        """
        Simple voucher processing for Lambda - returns extracted data without saving files
        Uses zero-shot validation + OCR
        """
        try:
            print(f"Processing voucher: {image_path}")
            
            # PDF files are now processed directly via Claude API (no page extraction needed)
            # This simplifies the code and avoids PyMuPDF dependency issues
            file_ext = os.path.splitext(image_path)[1].lower()
            if file_ext == '.pdf':
                print("📄 Processing PDF directly via Claude API (no page extraction)")
            
            # STEP 1: Zero-shot validation (TEMPORARILY DISABLED - causing throttling)
            # if self.zero_shot_enabled:
            #     validation = self._validate_voucher_with_zero_shot(
            #         image_path, 
            #         self.zero_shot_confidence_threshold
            #     )
            #     
            #     if not validation['is_voucher']:
            #         print(f"❌ Zero-shot validation failed: category={validation['category']}, confidence={validation['confidence']:.2f}")
            #         print(f"   Reasoning: {validation['reasoning']}")
            #         return {
            #             'success': False,
            #             'document_no': None,
            #             'document_date': None,
            #             'branch_id': None,
            #             'classification': validation['category'],
            #             'ocr_text': validation['reasoning'],
            #             'confidence': validation['confidence'],
            #             'method': 'zero_shot_validation',
            #             'organized_path': None,
            #             'complete_filename': None,
            #             'error': 'voucher new review',  # Custom error message
            #             'validation_failed': True
            #         }
            #     else:
            #         print(f"✅ Zero-shot validation passed: category={validation['category']}, confidence={validation['confidence']:.2f}")
            
            print("⚠️ Zero-shot validation temporarily disabled - proceeding directly to OCR")
            
            # STEP 2: Extract transaction data using OCR
            transaction_data = self._extract_transaction_data(image_path)
            
            result = {
                'success': True,
                'document_no': None,
                'document_date': None,
                'branch_id': None,
                'classification': 'UNKNOWN',
                'ocr_text': transaction_data,
                'confidence': 0.95,
                'method': 'lambda_ocr_extraction',
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
            
            # Try to parse JSON response first
            try:
                # Look for JSON in the response
                json_data = extract_json_from_text(transaction_data)
                if json_data:
                    
                    # Extract data from JSON response
                    result['document_no'] = json_data.get('document_no', '').strip()
                    result['document_date'] = json_data.get('document_date', '').strip()
                    result['branch_id'] = json_data.get('branch_id', '').strip()
                    raw_classification = json_data.get('category_type', '').strip()
                    
                    # Validate classification - must be in valid voucher types
                    # Valid types: MPU, MPV, MRT, MSL, REC, PAY, MJV
                    # Other types (FHE, TIS, etc.) are attachments
                    
                    # CRITICAL FIX: If category_type is empty/missing, try to extract from document_no
                    if not raw_classification and result['document_no']:
                        extracted_prefix = self._extract_document_no_prefix(result['document_no'])
                        if extracted_prefix:
                            raw_classification = extracted_prefix
                            print(f"✅ Extracted classification from document_no: '{raw_classification}'")
                    
                    if raw_classification and raw_classification in self.voucher_types:
                        result['classification'] = raw_classification
                        result['is_valid_voucher'] = True
                        print(f"✅ Valid voucher type: '{raw_classification}'")
                    else:
                        result['classification'] = raw_classification if raw_classification else 'UNKNOWN'
                        result['is_valid_voucher'] = False
                        print(f"⚠️ Invalid voucher type '{raw_classification}' - will treat as attachment")
                    
                    result['complete_filename'] = json_data.get('filename', '').strip()
                    
                    # Extract new fields (invoice amounts in both currencies, gold weight, purity, discount rate)
                    # Remove commas from numeric values
                    usd_amount = json_data.get('invoice_amount_usd', '').strip().replace(',', '') or None
                    aed_amount = json_data.get('invoice_amount_aed', '').strip().replace(',', '') or None
                    weight = json_data.get('gold_weight', '').strip().replace(',', '') or None
                    purity = json_data.get('purity', '').strip() or None
                    
                    result['invoice_amount_usd'] = usd_amount
                    result['invoice_amount_aed'] = aed_amount
                    result['gold_weight'] = weight
                    result['purity'] = purity
                    result['discount_rate'] = json_data.get('discount_rate', '').strip() or None
                    
                    print(f"📋 Extracted from JSON: Document No: {result['document_no']}, Date: {result['document_date']}, Branch: {result['branch_id']}, Category: {result['classification']}")
                    print(f"💰 Financial Data: USD: {result.get('invoice_amount_usd')}, AED: {result.get('invoice_amount_aed')}, Weight: {result.get('gold_weight')}, Purity: {result.get('purity')}, Discount: {result.get('discount_rate')}")
                    
                else:
                    raise ValueError("No JSON found in response")
                    
            except (json.JSONDecodeError, ValueError, KeyError) as e:
                print(f"⚠️ JSON parsing failed, falling back to regex: {e}")
                
                # Fallback to regex extraction with enhanced patterns
                document_no_match = re.search(r'Document No:\s*([A-Z0-9\s\-]+)', transaction_data, re.IGNORECASE)
                document_date_match = re.search(r'Document Date:\s*([\d/-]+)', transaction_data, re.IGNORECASE)
                branch_id_match = re.search(r'Branch ID:\s*([0-9]+)', transaction_data, re.IGNORECASE)
                
                if document_no_match:
                    result['document_no'] = document_no_match.group(1).strip()
                    result['classification'] = self._extract_document_no_prefix(result['document_no']) or 'UNKNOWN'
                    result['complete_filename'] = result['document_no']
                    
                    # Set is_valid_voucher based on classification
                    result['is_valid_voucher'] = result['classification'] in self.voucher_types
                    
                    if document_date_match:
                        result['document_date'] = document_date_match.group(1).strip()
                    if branch_id_match:
                        result['branch_id'] = branch_id_match.group(1).strip()
                        
                    print(f"📋 Extracted from regex: Document No: {result['document_no']}, Date: {result['document_date']}, Branch: {result['branch_id']}, Category: {result['classification']}, Valid: {result['is_valid_voucher']}")
                else:
                    # Try alternative patterns
                    alt_match = re.search(r'([A-Z]{2,}\d{2,}[\s\-]*\d+)', transaction_data)
                    if alt_match:
                        result['document_no'] = alt_match.group(1).strip()
                        result['classification'] = self._extract_document_no_prefix(result['document_no']) or 'UNKNOWN'
                        result['complete_filename'] = result['document_no']
                        
                        # Set is_valid_voucher based on classification
                        result['is_valid_voucher'] = result['classification'] in self.voucher_types
                        
                        if document_date_match:
                            result['document_date'] = document_date_match.group(1).strip()
                        if branch_id_match:
                            result['branch_id'] = branch_id_match.group(1).strip()
                            
                        print(f"📋 Extracted from alt pattern: Document No: {result['document_no']}, Date: {result['document_date']}, Branch: {result['branch_id']}, Category: {result['classification']}, Valid: {result['is_valid_voucher']}")
                    else:
                        # Use filename as fallback
                        filename = os.path.basename(image_path)
                        result['document_no'] = os.path.splitext(filename)[0]
                        result['complete_filename'] = result['document_no']
                        result['classification'] = 'UNKNOWN'
                        result['success'] = False
                        result['error'] = "Could not extract Document No from voucher"
                        result['organized_path'] = None  # Don't organize UNKNOWN files
                        print(f"⚠️ UNKNOWN classification - file will be moved to failed folder")
            
            # Generate the organized path ONLY for valid vouchers
            if result['success'] and result['document_no'] and result.get('is_valid_voucher'):
                result['organized_path'] = self._create_organized_path(
                    document_no=result['document_no'],
                    document_date=result['document_date'],
                    branch_id=result['branch_id'],
                    voucher_type=result['classification']
                )
                print(f"✅ Valid voucher - will organize to: {result['organized_path']}")
            elif result['success'] and not result.get('is_valid_voucher'):
                # Invalid category - will search for matching valid voucher
                result['organized_path'] = None
                result['needs_attachment'] = True
                print(f"⚠️ Attachment document - will search for matching valid voucher")
            
            # Convert image to PDF after OCR processing
            pdf_path = None
            if result['success']:
                try:
                    # Check if the file is already a PDF
                    file_extension = os.path.splitext(image_path)[1].lower()
                    print(f"🔍 DEBUG: Processing file {image_path} with extension {file_extension}")
                    
                    if file_extension != '.pdf':
                        print(f"🔄 Converting image to PDF: {image_path}")
                        pdf_path = self._convert_image_to_pdf(image_path)
                        if pdf_path:
                            result['pdf_path'] = pdf_path
                            result['converted_to_pdf'] = True
                            print(f"✅ Successfully converted to PDF: {pdf_path}")
                        else:
                            print("❌ PDF conversion failed, keeping original file")
                            result['pdf_path'] = image_path
                            result['converted_to_pdf'] = False
                    else:
                        print("📄 File is already PDF, no conversion needed")
                        result['pdf_path'] = image_path
                        result['converted_to_pdf'] = False
                except Exception as e:
                    print(f"❌ Error during PDF conversion: {e}")
                    result['pdf_path'] = image_path
                    result['converted_to_pdf'] = False
            else:
                print("❌ OCR processing failed, skipping PDF conversion")
                result['pdf_path'] = image_path
                result['converted_to_pdf'] = False
                    
            print(f"Processing result: {result}")
            
            return result
            
        except Exception as e:
            print(f"Error processing voucher: {str(e)}")
            
            return {
                'success': False,
                'error': str(e),
                'document_no': None,
                'classification': 'UNKNOWN',
                'method': 'error',
                'organized_path': None
            }
    
    def process_voucher(self, file_path, validate_voucher=True):
        """
        Main method to process a voucher file
        
        Args:
            file_path (str): Path to the voucher file (image or PDF)
            validate_voucher (bool): Whether to validate if the file is a voucher
        
        Returns:
            dict: Processing results including success status, document_no, folder_path, etc.
        """
        result = {
            "success": False,
            "document_no": None,
            "document_no_prefix": None,
            "document_date": None,
            "branch_id": None,
            "folder_path": None,
            "text_filepath": None,
            "image_filepath": None,
            "error": None,
            "organized_path": None
        }
        
        try:
            # Process the image
            processed_file = self._process_image(file_path)
            if not processed_file:
                result["error"] = "Failed to process the uploaded file"
                return result
            
            # Validate if it's a voucher (optional) - COMMENTED OUT FOR NOW
            if validate_voucher:
                # try:
                #     scores = self.classifier(processed_file, candidate_labels=self.labels)
                #     is_voucher = scores[0]['label'] == "voucher" and scores[0]['score'] > self.confidence_threshold
                #     if not is_voucher:
                #         result["error"] = "File does not appear to be a valid voucher"
                #         return result
                # except Exception as e:
                #     print(f"Warning: Error during image classification: {str(e)}")
                #     # Continue processing even if classification fails
                print("Voucher validation skipped (zero-shot learning disabled)")
                pass
            
            # Extract transaction data
            transaction_data = self._extract_transaction_data(processed_file)
            
            # Extract Document No from the transaction data
            document_no_match = re.search(r'Document No:\s*([A-Z0-9-]+)', transaction_data, re.IGNORECASE)
            document_date_match = re.search(r'Document Date:\s*([\d/-]+)', transaction_data, re.IGNORECASE)
            branch_id_match = re.search(r'Branch ID:\s*([0-9]+)', transaction_data, re.IGNORECASE)
            document_date_match = re.search(r'Document Date:\s*([\d/-]+)', transaction_data, re.IGNORECASE)
            
            if document_no_match:
                document_no = document_no_match.group(1).strip()
                result["document_no"] = document_no
                result["document_no_prefix"] = self._extract_document_no_prefix(document_no)
                if document_date_match:
                    result["document_date"] = document_date_match.group(1).strip()
                if branch_id_match:
                    result["branch_id"] = branch_id_match.group(1).strip()
            else:
                # Try alternative patterns
                alt_match = re.search(r'([A-Z]{2,}\d{2,}-?\d+)', transaction_data)
                if alt_match:
                    document_no = alt_match.group(1)
                    result["document_no"] = document_no
                    result["document_no_prefix"] = self._extract_document_no_prefix(document_no)
                    if document_date_match:
                        result["document_date"] = document_date_match.group(1).strip()
                    if branch_id_match:
                        result["branch_id"] = branch_id_match.group(1).strip()
                else:
                    result["error"] = "Could not extract Document No from the voucher"
                    return result
            
            # Generate the organized path
            result["organized_path"] = self._create_organized_path(
                document_no=result["document_no"],
                document_date=result["document_date"],
                branch_id=result["branch_id"],
                voucher_type=result["document_no_prefix"]
            )
            
            # Save files to appropriate folder (use document number for filenames)
            text_filepath, image_filepath, folder_path = self._save_voucher_files(
                transaction_data, processed_file, result["document_no_prefix"],
                document_no=result.get("document_no"), branch_id=result.get("branch_id"),
                organized_path=result["organized_path"]
            )
            
            result["success"] = True
            result["folder_path"] = folder_path
            result["text_filepath"] = text_filepath
            result["image_filepath"] = image_filepath
            
            # Clean up processed file
            if os.path.exists(processed_file) and processed_file != file_path:
                os.unlink(processed_file)
            
        except (OSError, IOError, ValueError, KeyError, AttributeError) as e:
            result["error"] = f"Error processing voucher: {str(e)}"
        
        return result
    
    def _save_voucher_files(self, transaction_data, image_path, document_no_prefix, document_no=None, branch_id=None, organized_path=None):
        """Save voucher files to the appropriate folder based on the organized path structure.
        """
        # Use the organized path if provided
        if organized_path:
            folder_path = os.path.join(self.base_dir, organized_path)
        else:
            # Fallback to old structure
            folder_path = self._create_voucher_folder(document_no_prefix)
            if not folder_path:
                print("Warning: Could not determine folder for Document No prefix:", document_no_prefix)
                folder_path = os.path.join(self.base_dir, "organized_vouchers", "UNKNOWN")
        
        os.makedirs(folder_path, exist_ok=True)
        
        # Ensure transaction_data is a string
        if not isinstance(transaction_data, str):
            try:
                transaction_data = str(transaction_data)
            except (TypeError, ValueError):
                transaction_data = "Error: Unable to convert transaction data to string"
        
        # Determine base filename
        preferred_base = self._sanitize_document_no(document_no) if document_no else None
        base_filename = preferred_base or self._generate_base_filename(transaction_data)
        
        # Save text file alongside document name
        text_filepath = os.path.join(folder_path, f"{base_filename}.txt")
        with open(text_filepath, 'w', encoding='utf-8') as f:
            f.write(transaction_data)
        
        # Save as PDF with document number name
        pdf_filepath = os.path.join(folder_path, f"{base_filename}_0001.pdf")
        try:
            # First, ensure we have a proper JPEG image for PDF conversion
            temp_jpeg_path = None
            with Image.open(image_path) as img:
                # Convert to RGB mode for JPEG compatibility
                if img.mode in ("RGBA", "P", "LA", "L"):
                    img = img.convert("RGB")
                # Save as temporary JPEG for PDF conversion
                temp_jpeg_path = os.path.join(folder_path, f"{base_filename}_temp.jpg")
                img.save(temp_jpeg_path, format="JPEG", quality=95)
            
            # Convert JPEG to PDF
            if temp_jpeg_path and os.path.exists(temp_jpeg_path):
                with open(temp_jpeg_path, 'rb') as f:
                    image_bytes = f.read()
                
                # Get JPEG dimensions
                width, height = self._get_jpeg_dimensions(image_bytes)
                
                # Create PDF with embedded JPEG
                pdf_content = self._create_pdf_from_jpeg(image_bytes, width, height)
                
                # Write PDF file
                with open(pdf_filepath, 'wb') as f:
                    f.write(pdf_content)
                
                # Clean up temporary JPEG
                os.unlink(temp_jpeg_path)
                
                print(f"✅ Successfully created PDF: {pdf_filepath}")
            
        except Exception as e:
            print(f"❌ PDF conversion failed: {e}")
            # Fallback: save as JPEG if PDF conversion fails
            pdf_filepath = os.path.join(folder_path, f"{base_filename}.jpg")
            try:
                with Image.open(image_path) as img:
                    if img.mode in ("RGBA", "P"):
                        img = img.convert("RGB")
                    img.save(pdf_filepath, format="JPEG", quality=95)
            except Exception:
                # Last resort: copy original file
                image_extension = os.path.splitext(image_path)[1]
                pdf_filepath = os.path.join(folder_path, f"{base_filename}{image_extension}")
                shutil.copy2(image_path, pdf_filepath)
        
        return text_filepath, pdf_filepath, folder_path
    
    def process_multiple_vouchers(self, file_paths, validate_voucher=True):
        """
        Process multiple voucher files
        
        Args:
            file_paths (list): List of file paths to process
            validate_voucher (bool): Whether to validate if files are vouchers
        
        Returns:
            list: List of processing results for each file
        """
        results = []
        for file_path in file_paths:
            print(f"Processing: {file_path}")
            result = self.process_voucher(file_path, validate_voucher)
            results.append(result)
            
            if result["success"]:
                print(f"✅ Success: {result['document_no']} -> {result['folder_path']}")
            else:
                print(f"❌ Failed: {result['error']}")
        
        return results


def main():
    """Example usage of the VoucherOCRService"""
    # Initialize the service
    ocr_service = VoucherOCRService()
    
    # Example: Process a single voucher
    # file_path = "path/to/your/voucher.pdf"
    # result = ocr_service.process_voucher(file_path)
    # print(f"Processing result: {result}")
    
    # Example: Process multiple vouchers
    # file_paths = ["voucher1.pdf", "voucher2.png", "voucher3.jpg"]
    # results = ocr_service.process_multiple_vouchers(file_paths)
    # print(f"Processed {len(results)} vouchers")
    
    print("VoucherOCRService initialized successfully!")
    print("Available voucher types:", list(ocr_service.voucher_types.keys()))


if __name__ == "__main__":
    main()