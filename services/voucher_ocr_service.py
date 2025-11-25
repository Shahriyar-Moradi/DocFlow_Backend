
import os
import shutil
import base64
from datetime import datetime
import re
import json
import boto3
from dotenv import load_dotenv
from PIL import Image
import fitz  # PyMuPDF for PDF processing
# from transformers import pipeline  # COMMENTED OUT FOR NOW

# Load environment variables from backend directory
import os
backend_env_path = os.path.join(os.path.dirname(__file__), '..', '.env')
load_dotenv(backend_env_path)

# Set environment variable to avoid tokenizer warnings
os.environ["TOKENIZERS_PARALLELISM"] = "false"

class VoucherOCRService:
    def __init__(self):
        """Initialize the Voucher OCR Service"""
        # Initialize models - COMMENTED OUT FOR NOW
        # self.model_name = "openai/clip-vit-large-patch14-336"
        # self.classifier = pipeline("zero-shot-image-classification", model=self.model_name)
        # self.labels = ["voucher", "other"]
        # self.confidence_threshold = 0.7
        
        # AWS Bedrock client for Claude
        try:
            # Initialize Bedrock client
            # You can specify AWS region via AWS_REGION env var or it will use default
            aws_region = os.getenv("AWS_REGION", "us-east-1")
            self.bedrock_client = boto3.client(
                service_name='bedrock-runtime',
                region_name=aws_region
            )
            # Use cross-region inference profile for Claude Sonnet 4
            # Format: us.anthropic.{model-name}
            self.model_id = "us.anthropic.claude-sonnet-4-20250514-v1:0"
            print(f"✅ AWS Bedrock client initialized (region: {aws_region}, model: {self.model_id})")
        except Exception as e:
            print(f"Warning: Failed to initialize AWS Bedrock client: {e}")
            self.bedrock_client = None
            self.model_id = None
        
        # Base directory (backend), services directory, and data directory
        self.services_dir = os.path.dirname(__file__)
        self.base_dir = os.path.dirname(self.services_dir)  # backend directory
        self.data_dir = os.path.join(self.base_dir, "data")
        self.image_dir = os.path.join(self.services_dir, "voucher_sample")
        
        # Define voucher type prefixes and their corresponding folders
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
        
        # Load example images for OCR training (if available)
        self._load_example_images()
    
    def _load_example_images(self):
        """Load example voucher images for OCR training"""
        self.example_images = {}
        
        # Check if voucher_sample directory exists
        if not os.path.exists(self.image_dir):
            print(f"Warning: Voucher sample directory not found at {self.image_dir}")
            print("OCR service will work without example images (reduced accuracy)")
            return
        
        # Define the example image paths
        example_paths = {
            "MPU": os.path.join(self.image_dir, "MPU/MPU01-85285_0001.png"),
            "MPV": os.path.join(self.image_dir, "MPV/MPV01-82404_0001.png"),
            "MRT": os.path.join(self.image_dir, "MRT/MRT01-85695_0001.png"),
            "MSL": os.path.join(self.image_dir, "MSL/MSL01-414585_0001.png"),
            "REC": os.path.join(self.image_dir, "REC/REC01-422556_0001.png"),
            "PAY": os.path.join(self.image_dir, "PAY/PAY01-239100_0001.png"),
            "MJV": os.path.join(self.image_dir, "MJV/MJV01-01294_0001.png")
        }
        
        # Load available example images
        for voucher_type, image_path in example_paths.items():
            if os.path.exists(image_path):
                try:
                    self.example_images[voucher_type] = self._encode_image(image_path)
                    print(f"Loaded example image for {voucher_type}")
                except Exception as e:
                    print(f"Warning: Failed to load example image for {voucher_type}: {e}")
            else:
                print(f"Warning: Example image not found for {voucher_type}: {image_path}")
        
        if not self.example_images:
            print("No example images loaded. OCR service will work without examples (reduced accuracy)")
        else:
            print(f"Loaded {len(self.example_images)} example images for OCR training")
    
    def _encode_image_to_base64(self, image_path):
        """Encode image to base64"""
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    
    def _encode_image(self, image_path):
        """Wrapper for image encoding"""
        return self._encode_image_to_base64(image_path)
    
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
            
            # Ensure voucher type is valid
            if not voucher_type or voucher_type not in self.voucher_types:
                voucher_type = self._extract_document_no_prefix(document_no) or "UNKNOWN"
            
            # Build the path (relative to data directory)
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
            print(f"Error creating organized path: {e}")
            # Fallback path
            return f"organized_vouchers/UNKNOWN/{datetime.now().strftime('%Y-%m-%d')}"
    
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
        folder_path = os.path.join(self.data_dir, "organized_vouchers", folder_name)
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
    
    def _extract_transaction_data(self, image_path):
        """Extract transaction data using Claude OCR"""
        base64_image = self._encode_image_to_base64(image_path)
        
        # Determine the correct media type based on file extension
        file_extension = os.path.splitext(image_path)[1].lower().lstrip('.')
        if file_extension in ['jpg', 'jpeg']:
            media_type = "image/jpeg"
        elif file_extension == 'png':
            media_type = "image/png"
        else:
            media_type = "image/png"  # default fallback
        
        # Prepare messages with examples
        messages = [
            {
                "role": "user",
                "content": (
                    '''OCR and extract important information like Document No and Document Date and Branch ID from the image accurately. 
                    We will provide example images with the correct extracted text. Then you'll get a new image
                    and should provide the extracted text in Persian, Extract the following transaction details:
                    - Document No
                    - Document Date
                    - Branch ID
                    Return in a clear, structured format.'''    
                ),
            },
            {
                "role": "assistant",
                "content": "I understand. I will help you extract Document No from voucher images. Please provide the example images and I will learn from them to accurately extract the Document No , Document Date, and Branch ID from new images."
            }
        ]
        
        # Add example images (if available)
        examples = [
            ("MPU", "MPU01-85285", "02-06-2025", "01"),
            ("MPV", "MPV01-82404", "02-06-2025", "01"),
            ("MRT", "MRT01-85695", "02-06-2025", "01"),
            ("MJV", "MJV13 No: 01294", "02-06-2025","13")
        ]
        
        # Only add examples if we have the corresponding images
        for i, (voucher_type, doc_no, doc_date, branch_id) in enumerate(examples, 1):
            if voucher_type in self.example_images:
                messages.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": f"Here is **Example {i}**. Please extract the Document No, Document Date, and Branch ID from this image:",
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": self.example_images[voucher_type],
                            },
                        },
                    ]
                })
                
                # Add assistant response for the example
                messages.append({
                    "role": "assistant",
                    "content": f"Document No: {doc_no}, Document Date: {doc_date}, Branch ID: {branch_id}"
                })
        
        # Add the new image to process
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "Now process this **NEW receipt** image. "
                        "Please extract the Document No, Document Date, and Branch ID in the same style. Document No: [value], Document Date: [value], Branch ID: [value]"
                    )
                },
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": base64_image,
                    },
                },
            ]
        })
        
        # If bedrock client is missing, fail immediately with clear error
        if not self.bedrock_client:
            raise Exception("OCR_API_KEY_MISSING: AWS Bedrock client is not configured")

        import time
        
        max_retries = 1
        retry_delay = 30  # seconds
        
        for attempt in range(1, max_retries + 1):
            try:
                # Format request for AWS Bedrock
                request_body = {
                    "anthropic_version": "bedrock-2023-05-31",
                    "max_tokens": 1024,
                    "messages": messages
                }
                
                # Call Bedrock API
                response = self.bedrock_client.invoke_model(
                    modelId=self.model_id,
                    body=json.dumps(request_body)
                )
                
                # Parse response
                response_body = json.loads(response['body'].read())
                return response_body['content'][0]['text']
                
            except Exception as e:
                error_message = str(e)
                print(f"OCR attempt {attempt} failed: {error_message}")
                
                # Classify the error type
                if "authentication" in error_message.lower() or "invalid" in error_message.lower():
                    raise Exception("OCR_AUTH_FAILED: Invalid API key")
                elif "rate" in error_message.lower() or "limit" in error_message.lower():
                    if attempt < max_retries:
                        print(f"Rate limit hit. Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise Exception("OCR_RATE_LIMIT: Rate limit exceeded")
                elif "insufficient" in error_message.lower() or "balance" in error_message.lower():
                    raise Exception("OCR_INSUFFICIENT_BALANCE: Insufficient API balance")
                elif "timeout" in error_message.lower():
                    if attempt < max_retries:
                        print(f"Timeout occurred. Retrying in {retry_delay} seconds...")
                        time.sleep(retry_delay)
                        continue
                    else:
                        raise Exception("OCR_TIMEOUT: API request timed out")
                elif attempt < max_retries:
                    print(f"Generic error occurred. Retrying in {retry_delay} seconds...")
                    time.sleep(retry_delay)
                    continue
                else:
                    raise Exception(f"OCR_FAILED: {error_message}")
    
    def _save_voucher_files(self, transaction_data, image_path, document_no_prefix, document_no=None, branch_id=None, document_date=None, organized_path=None):
        """Save voucher files to the appropriate folder based on the organized path structure.
        Save image as <DocumentNo>.jpg and text as <DocumentNo>.txt when possible.
        """
        # Use the organized path if provided
        if organized_path:
            folder_path = os.path.join(self.data_dir, organized_path)
        else:
            # Fallback to old structure
            folder_path = self._create_voucher_folder(document_no_prefix)
            if not folder_path:
                print("Warning: Could not determine folder for Document No prefix:", document_no_prefix)
                folder_path = os.path.join(self.data_dir, "organized_vouchers", "UNKNOWN")
        
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
        
        # Save image as JPEG with document number name (for now - PDF conversion requires additional libraries)
        image_filepath = os.path.join(folder_path, f"{base_filename}.jpg")
        try:
            with Image.open(image_path) as img:
                # Convert to RGB mode for JPEG compatibility
                if img.mode in ("RGBA", "P", "LA", "L"):
                    img = img.convert("RGB")
                img.save(image_filepath, format="JPEG", quality=95)
        except Exception:
            # Fallback: copy original extension if conversion fails
            image_extension = os.path.splitext(image_path)[1]
            image_filepath = os.path.join(folder_path, f"{base_filename}{image_extension}")
            shutil.copy2(image_path, image_filepath)
        
        return text_filepath, image_filepath, folder_path
    
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
            "error": None
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
            organized_path = self._create_organized_path(
                document_no=result["document_no"],
                document_date=result["document_date"],
                branch_id=result["branch_id"],
                voucher_type=result["document_no_prefix"]
            )
            
            # Save files to appropriate folder (use document number for filenames)
            text_filepath, image_filepath, folder_path = self._save_voucher_files(
                transaction_data, processed_file, result["document_no_prefix"],
                document_no=result.get("document_no"), 
                branch_id=result.get("branch_id"),
                document_date=result.get("document_date"),
                organized_path=organized_path
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
