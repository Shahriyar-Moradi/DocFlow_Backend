"""
Comprehensive Lambda handler using the full OCR service
"""

import json
import boto3
import tempfile
import os
import re
import ssl
from datetime import datetime
from voucher_ocr_service_lambda_full import VoucherOCRService

# Configure SSL certificate handling for Lambda
try:
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    print(f"✅ SSL certificate configured: {certifi.where()}")
except ImportError:
    # Fallback: Use system CA bundle
    os.environ['SSL_CERT_FILE'] = '/etc/ssl/certs/ca-bundle.crt'
    print("⚠️ certifi not available, using system CA bundle")

# AWS clients - configured with SSL
s3_client = boto3.client('s3', region_name='me-central-1')
sqs_client = boto3.client('sqs', region_name='me-central-1')

# Queue URLs
PROCESSED_QUEUE_URL = 'https://sqs.me-central-1.amazonaws.com/930816733230/doc-processed-queue'

# Initialize OCR service once (Lambda container reuse)
ocr_service = None


def find_matching_vouchers_in_s3(bucket, weight, purity, date, amount_usd, amount_aed, exclude_key=None):
    """
    Find vouchers with matching criteria:
    - (Weight OR Amount) must match
    - Date must match
    - Final: (Weight OR Amount) AND Date
    """
    # At least weight or amount is required
    if not weight and not amount_usd and not amount_aed:
        print("⚠️ Weight and amount both missing - cannot match")
        return []
    
    print(f"🔍 Searching for matching vouchers:")
    print(f"   Weight: {weight}, Purity: {purity}, Date: {date}")
    print(f"   USD: {amount_usd}, AED: {amount_aed}")
    
    matches = []
    
    try:
        paginator = s3_client.get_paginator('list_objects_v2')
        
        for page in paginator.paginate(Bucket=bucket, Prefix='organized_vouchers/'):
            if 'Contents' not in page:
                continue
                
            for obj in page['Contents']:
                s3_key = obj['Key']
                
                # Skip current file and non-PDF files
                if s3_key == exclude_key or not s3_key.endswith('.pdf'):
                    continue
                
                try:
                    # Get object metadata
                    metadata_response = s3_client.head_object(Bucket=bucket, Key=s3_key)
                    metadata = metadata_response.get('Metadata', {})
                    
                    # CRITERION 0: Must be a VALID voucher type (not an attachment)
                    # Valid types: MPU, MPV, MRT, MSL, REC, PAY, MJV
                    stored_classification = metadata.get('classification', '')
                    valid_types = ['MPU', 'MPV', 'MRT', 'MSL', 'REC', 'PAY', 'MJV']
                    if stored_classification not in valid_types:
                        # Skip attachments and invalid types
                        continue
                    
                    # CRITERION 1: Check if weight matches (if available)
                    weight_matches = False
                    if weight:
                        stored_weight = metadata.get('gold-weight')
                        if stored_weight:
                            # Compare weights as integers only (ignore decimals)
                            try:
                                weight_val = int(float(str(weight).replace(',', '')))
                                stored_weight_val = int(float(str(stored_weight).replace(',', '')))
                                # Compare integer parts only
                                if weight_val == stored_weight_val:
                                    weight_matches = True
                                    print(f"  ⚖️ Weight matches (integer): {weight_val} == {stored_weight_val}")
                                else:
                                    print(f"  ⚠️ Weight doesn't match: {weight_val} vs {stored_weight_val}")
                            except (ValueError, TypeError) as e:
                                # Fallback to string comparison
                                if str(weight) == str(stored_weight):
                                    weight_matches = True
                                    print(f"  ⚖️ Weight matches (string): {weight}")
                                else:
                                    print(f"  ⚠️ Weight string comparison failed: '{weight}' vs '{stored_weight}'")
                    
                    # CRITERION 2: Purity should match if available (optional for attachments)
                    # If purity is provided for attachment, it must match
                    # If purity is missing in attachment, we skip this check
                    if purity:
                        stored_purity = metadata.get('purity')
                        if stored_purity:
                            # Compare purity values - handle both numeric (1.000) and karat (22K) formats
                            try:
                                # Try numeric comparison first (for values like 1.000, 0.995)
                                purity_match = False
                                
                                # Remove common non-numeric chars
                                clean_purity = str(purity).replace('K', '').replace('k', '').strip()
                                clean_stored = str(stored_purity).replace('K', '').replace('k', '').strip()
                                
                                try:
                                    purity_val = float(clean_purity)
                                    stored_val = float(clean_stored)
                                    # Allow tiny tolerance for float comparison (e.g., 1.000 vs 1.0000000)
                                    if abs(purity_val - stored_val) < 0.0001:
                                        purity_match = True
                                except ValueError:
                                    # If can't convert to float, do string comparison
                                    if str(purity) == str(stored_purity):
                                        purity_match = True
                                
                                if not purity_match:
                                    continue
                            except Exception:
                                # Fallback to string comparison
                                if str(purity) != str(stored_purity):
                                    continue
                    
                    # CRITERION 3: Check if date matches (normalize different formats)
                    stored_date = metadata.get('document-date')
                    date_matches = False
                    if date and stored_date:
                        # Try to normalize dates for comparison (handle 02/06/2025 vs 02-Jun-25)
                        try:
                            from datetime import datetime
                            
                            # Common date formats
                            date_formats = [
                                "%d/%m/%Y",   # 02/06/2025
                                "%d-%m-%Y",   # 02-06-2025
                                "%d-%b-%y",   # 02-Jun-25
                                "%d-%b-%Y",   # 02-Jun-2025
                                "%Y-%m-%d",   # 2025-06-02
                            ]
                            
                            parsed_date = None
                            parsed_stored = None
                            
                            # Try to parse current date
                            for fmt in date_formats:
                                try:
                                    parsed_date = datetime.strptime(str(date), fmt).date()
                                    break
                                except:
                                    pass
                            
                            # Try to parse stored date
                            for fmt in date_formats:
                                try:
                                    parsed_stored = datetime.strptime(str(stored_date), fmt).date()
                                    break
                                except:
                                    pass
                            
                            # Compare normalized dates
                            if parsed_date and parsed_stored and parsed_date == parsed_stored:
                                date_matches = True
                                print(f"  📅 Date matches: {date} == {stored_date}")
                            elif str(date) == str(stored_date):
                                # Fallback to string comparison
                                date_matches = True
                                print(f"  📅 Date matches (string): {date}")
                        except:
                            # Fallback to string comparison
                            if str(date) == str(stored_date):
                                date_matches = True
                                print(f"  📅 Date matches: {date}")
                    
                    # CRITERION 4: Check if amount matches within 1% tolerance in EITHER currency
                    stored_usd = metadata.get('invoice-amount-usd')
                    stored_aed = metadata.get('invoice-amount-aed')
                    
                    amount_matches = False
                    
                    # Check USD if both have USD amounts
                    if amount_usd and stored_usd:
                        try:
                            current_usd = float(amount_usd)
                            stored_usd_val = float(stored_usd)
                            # Check if within 1% tolerance
                            if stored_usd_val > 0:
                                diff_percent = abs(current_usd - stored_usd_val) / stored_usd_val
                                if diff_percent <= 0.01:
                                    amount_matches = True
                                    print(f"  💵 USD amount matches within tolerance: {current_usd} ≈ {stored_usd_val} (diff: {diff_percent*100:.2f}%)")
                        except (ValueError, ZeroDivisionError):
                            pass
                    
                    # Check AED if USD didn't match (or wasn't available)
                    if not amount_matches and amount_aed and stored_aed:
                        try:
                            current_aed = float(amount_aed)
                            stored_aed_val = float(stored_aed)
                            # Check if within 1% tolerance
                            if stored_aed_val > 0:
                                diff_percent = abs(current_aed - stored_aed_val) / stored_aed_val
                                if diff_percent <= 0.01:
                                    amount_matches = True
                                    print(f"  💵 AED amount matches within tolerance: {current_aed} ≈ {stored_aed_val} (diff: {diff_percent*100:.2f}%)")
                        except (ValueError, ZeroDivisionError):
                            pass
                    
                    # FINAL CHECK: (Weight OR Amount) AND Date must all match
                    # Logic: (weight_matches OR amount_matches) AND date_matches
                    if (weight_matches or amount_matches) and date_matches:
                        matches.append(s3_key)
                        match_reason = []
                        if weight_matches:
                            match_reason.append("weight")
                        if amount_matches:
                            match_reason.append("amount")
                        if date_matches:
                            match_reason.append("date")
                        print(f"  ✅ Match found: {s3_key} (matched: {', '.join(match_reason)})")
                    else:
                        print(f"  ⚠️ No match: weight={weight_matches}, amount={amount_matches}, date={date_matches}")
                        
                except Exception as e:
                    # Skip files that can't be checked
                    continue
        
        print(f"🔍 Found {len(matches)} matching vouchers")
        return matches
        
    except Exception as e:
        print(f"❌ Error searching for matches: {e}")
        return []


def lambda_handler(event, context):
    """
    Main Lambda handler using comprehensive OCR service
    """
    global ocr_service
    
    print(f"Received event: {event}")
    
    try:
        # Initialize OCR service if needed
        if ocr_service is None:
            print("Initializing comprehensive OCR service...")
            ocr_service = VoucherOCRService()
            print("OCR service initialized successfully")
        
        # Handle test events (non-SQS)
        if 'test' in event:
            return handle_test_event(event)
            
        # Handle SQS events
        if 'Records' in event:
            return handle_sqs_event(event)
            
        return {
            'statusCode': 400,
            'body': json.dumps({'error': 'Unsupported event type'})
        }
        
    except Exception as e:
        print(f"Error in lambda_handler: {str(e)}")
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }

def handle_test_event(event):
    """Handle test events"""
    print("Processing test event")
    return {
        'statusCode': 200,
        'body': json.dumps({
            'message': 'Comprehensive Lambda OCR handler working!',
            'timestamp': datetime.now().isoformat(),
            'ocr_service_available': ocr_service is not None,
            'anthropic_available': hasattr(ocr_service, 'anthropic_client') and ocr_service.anthropic_client is not None,
            'supported_types': list(ocr_service.voucher_types.keys()) if ocr_service else [],
            'event': event
        })
    }

def handle_sqs_event(event):
    """Handle SQS triggered events"""
    records = event.get('Records', [])
    print(f"Received {len(records)} messages")
    
    results = []
    failed_records = []  # Track records that failed processing
    
    for record in records:
        try:
            result = process_sqs_message(record)
            results.append(result)
            
            # If processing failed, we need to track this for partial batch failure handling
            if not result.get('success', False):
                failed_records.append({
                    'itemIdentifier': record.get('messageId'),
                    'receiptHandle': record.get('receiptHandle')
                })
                print(f"❌ Processing failed for message {record.get('messageId')}: {result.get('error', 'Unknown error')}")
            else:
                print(f"✅ Processing successful for message {record.get('messageId')}")
                
        except Exception as e:
            print(f"❌ Exception processing record {record.get('messageId')}: {str(e)}")
            results.append({
                'success': False,
                'error': str(e),
                'record': record.get('messageId', 'unknown')
            })
            # Track failed records for partial batch failure handling
            failed_records.append({
                'itemIdentifier': record.get('messageId'),
                'receiptHandle': record.get('receiptHandle')
            })
    
    # Return response with batch item failures if any records failed
    response = {
        'statusCode': 200,
        'body': json.dumps({
            'processed': len(results),
            'results': results
        })
    }
    
    # If we have failed records, return them for partial batch failure handling
    if failed_records:
        response['batchItemFailures'] = failed_records
        print(f"⚠️ Returning {len(failed_records)} failed records for retry")
    
    return response

def process_sqs_message(record):
    """Process a single SQS message using comprehensive OCR service"""
    try:
        # Parse the message body
        body = json.loads(record['body'])
        s3_key = body['s3_key']
        batch_id = body.get('batch_id', 'unknown')
        filename = body.get('filename', 'unknown')
        document_id = body.get('document_id', 'unknown')  # Extract document_id for voucher_id
        
        print(f"Processing: {s3_key}")
        
        # Download the image from S3
        bucket = body.get('bucket', 'rocabucket-1')
        filename_only = os.path.basename(s3_key)
        
        # DEFENSIVE CHECK: Before processing, check if file already exists in final locations
        # This handles duplicate SQS messages gracefully
        try:
            # Check if file exists in organized folder (successful processing)
            organized_prefix = f"batches/{batch_id}/organized/"
            org_response = s3_client.list_objects_v2(
                Bucket=bucket,
                Prefix=organized_prefix,
                MaxKeys=1000
            )
            
            if 'Contents' in org_response:
                for obj in org_response['Contents']:
                    # Check if any file in organized folder matches our original filename
                    if filename_only.replace('.jpg', '').replace('.png', '').replace('.pdf', '') in obj['Key']:
                        print(f"✅ File already processed - found in organized folder: {obj['Key']}")
                        return {
                            'success': True,
                            'already_processed': True,
                            'original_key': s3_key,
                            'batch_id': batch_id,
                            'organized_key': obj['Key'],
                            'message': 'File already processed and moved to organized folder'
                        }
            
            # Check if file exists in failed folder
            failed_key = f"batches/{batch_id}/failed/{filename_only}"
            try:
                s3_client.head_object(Bucket=bucket, Key=failed_key)
                print(f"✅ File already processed - found in failed folder: {failed_key}")
                return {
                    'success': True,
                    'already_processed': True,
                    'original_key': s3_key,
                    'batch_id': batch_id,
                    'failed_key': failed_key,
                    'message': 'File already processed and moved to failed folder'
                }
            except:
                # File not in failed folder, continue processing
                pass
                
        except Exception as check_error:
            # If defensive check fails, log it but continue with normal processing
            print(f"⚠️ Defensive check failed (non-critical): {check_error}")
        
        # Get the correct file extension from the original filename
        _, file_extension = os.path.splitext(s3_key)
        if not file_extension:
            file_extension = '.jpg'  # default fallback
        
        with tempfile.NamedTemporaryFile(suffix=file_extension, delete=False) as temp_file:
            try:
                # Try to download the file from S3
                try:
                    s3_client.download_file(bucket, s3_key, temp_file.name)
                    print(f"Downloaded {s3_key} to {temp_file.name}")
                except Exception as download_error:
                    # Check if it's a 404 (file not found) error
                    if '404' in str(download_error) or 'Not Found' in str(download_error):
                        print(f"✅ File {s3_key} not found in temp - likely already processed by duplicate message")
                        print(f"Marking message as successfully handled to prevent retry loop")
                        # Return success to tell SQS this message was handled
                        # The file was already processed and deleted by a previous duplicate message
                        return {
                            'success': True,
                            'already_processed': True,
                            'original_key': s3_key,
                            'batch_id': batch_id,
                            'message': 'File already processed and deleted from temp folder'
                        }
                    else:
                        # For other S3 errors (network, permissions, etc.), re-raise to trigger retry
                        raise
                
                # Process the image/PDF using comprehensive OCR service
                # Pass original filename for proper document number extraction
                # Note: PDFs are now processed directly by Claude API (no page extraction)
                result = ocr_service.process_voucher_simple(temp_file.name, original_filename=filename)
                
                # NEW: Check for UNKNOWN classification BEFORE any upload
                if result.get('classification') == 'UNKNOWN' or (result.get('organized_path') and '/UNKNOWN/' in str(result.get('organized_path'))):
                    print(f"❌ UNKNOWN classification detected for {s3_key}, moving to failed folder")
                    result['success'] = False
                    result['error'] = 'Document classified as UNKNOWN - unable to determine document type'
                    result['validation_failed'] = True
                    result['organized_path'] = None  # Clear organized path
                
                # Handle failed files FIRST - move to failed folder BEFORE sending processed message
                # This prevents race conditions where duplicate SQS messages might delete the file
                # before we can copy it to the failed folder
                if not result.get('success') or result.get('validation_failed'):
                    print(f"❌ Processing failed for {s3_key}, moving to failed folder")
                    try:
                        filename_only = os.path.basename(s3_key)
                        failed_key = f"batches/{batch_id}/failed/{filename_only}"
                        
                        # Copy to failed location FIRST (before any other operations)
                        s3_client.copy_object(
                            Bucket=bucket,
                            CopySource={'Bucket': bucket, 'Key': s3_key},
                            Key=failed_key
                        )
                        print(f"✅ Copied file to failed location: {failed_key}")
                        
                        # Delete from temp AFTER successful copy
                        s3_client.delete_object(Bucket=bucket, Key=s3_key)
                        print(f"🗑️ Deleted file from temp location: {s3_key}")
                        
                        result['failed_key'] = failed_key
                        result['moved_to_failed'] = True
                        
                        # CRITICAL FIX: Mark as successfully handled for SQS
                        # The file was processed correctly (outcome: validation failed)
                        # We don't want SQS to retry this message
                        result['success'] = True
                        result['sqs_success'] = True  # Track that this was handled
                        print(f"✅ Marked as successfully handled (moved to failed folder)")
                        
                    except Exception as e:
                        print(f"❌ Failed to move file to failed folder: {e}")
                        result['failed_move_error'] = str(e)
                        # Keep success=False here because file wasn't handled properly
                
                # Send processed message to SQS AFTER handling failed files
                # This ensures the file is already in its final location before notifying other systems
                success = send_processed_message(s3_key, batch_id, result, document_id)
                print(f"Sent processed message for {s3_key}: {success}")
                
                # Check if this is a valid voucher or attachment document
                is_valid_voucher = result.get('is_valid_voucher', False)
                needs_attachment = result.get('needs_attachment', False)
                
                # CASE 1: Valid voucher - organize normally and search for matches
                if result['success'] and is_valid_voucher and result.get('organized_path'):
                    # Determine which file to upload (PDF if converted, otherwise original)
                    file_to_upload = result.get('pdf_path', temp_file.name)
                    is_pdf = result.get('converted_to_pdf', False)
                    
                    # For valid vouchers, we don't check for matches here
                    # Valid vouchers are uploaded as originals, attachments will merge into them later
                    print(f"✅ Valid voucher - uploading as original")
                    # No matching/merging for valid vouchers - they are the "main" documents
                    
                    # Check if original file is already a PDF (for direct PDF processing)
                    original_filename = os.path.basename(s3_key)
                    file_ext = os.path.splitext(original_filename)[1].lower()
                    if file_ext == '.pdf':
                        is_pdf = True  # Original file is PDF
                        file_to_upload = temp_file.name  # Use the original PDF
                    
                    print(f"🔍 DEBUG: file_to_upload={file_to_upload}, is_pdf={is_pdf}, file_ext={file_ext}")
                    print(f"🔍 DEBUG: result keys: {list(result.keys())}")
                    
                    # Use complete filename from OCR result if available
                    if result.get('complete_filename') and result['complete_filename'].strip():
                        complete_doc_no = result['complete_filename'].strip()
                        # Sanitize filename for S3 compatibility while preserving the Document No format
                        # Replace problematic characters but keep spaces and hyphens
                        safe_filename = re.sub(r'[<>:"/\\|?*]', '_', complete_doc_no)
                        
                        # Use .pdf extension for PDF files, otherwise use original extension
                        if is_pdf:
                            final_filename = f"{safe_filename}_0001.pdf"
                            print(f"🔍 DEBUG: Using complete Document No for PDF: {original_filename} -> {final_filename}")
                        else:
                            # Get original extension for non-PDF files
                            original_ext = os.path.splitext(original_filename)[1]
                            final_filename = f"{safe_filename}_0001{original_ext}"
                            print(f"🔍 DEBUG: Using complete Document No for image: {original_filename} -> {final_filename}")
                    else:
                        # Fallback to original logic if complete filename not available
                        filename_without_ext = os.path.splitext(original_filename)[0]
                        
                        if is_pdf:
                            final_filename = f"{filename_without_ext}.pdf"  # Keep PDF extension
                            print(f"🔍 DEBUG: Fallback - PDF filename: {final_filename}")
                        else:
                            original_ext = os.path.splitext(original_filename)[1]
                            final_filename = f"{filename_without_ext}{original_ext}"  # Keep original extension
                            print(f"🔍 DEBUG: Fallback - Image filename: {final_filename}")
                    
                    organized_key = f"{result['organized_path']}/{final_filename}"
                    batch_organized_key = None
                    
                    try:
                        # Prepare metadata with extracted fields for S3 querying
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
                        
                        # Upload the file (PDF or original) to global organized location
                        with open(file_to_upload, 'rb') as file_data:
                            content_type = 'application/pdf' if is_pdf else 'image/jpeg'
                            s3_client.put_object(
                                Bucket=bucket,
                                Key=organized_key,
                                Body=file_data.read(),
                                ContentType=content_type,
                                Metadata=metadata
                            )
                        print(f"Uploaded file to organized location: {organized_key}")
                        result['organized_key'] = organized_key
                        
                        # ALSO upload original PNG alongside PDF for future merging
                        png_key = organized_key.replace('.pdf', '_original.png')
                        with open(temp_file.name, 'rb') as png_data:  # temp_file is the original PNG
                            s3_client.put_object(
                                Bucket=bucket,
                                Key=png_key,
                                Body=png_data.read(),
                                ContentType='image/png',
                                Metadata=metadata
                            )
                        print(f"📦 Stored original PNG: {png_key}")

                        # Also upload to batch-specific organized prefix when batch_id is available
                        if batch_id and batch_id.lower() != 'unknown':
                            organized_relative_path = result['organized_path']
                            if organized_relative_path.startswith('organized_vouchers/'):
                                organized_relative_path = organized_relative_path[len('organized_vouchers/') :]
                            elif organized_relative_path.startswith('/'):
                                organized_relative_path = organized_relative_path[1:]

                            batch_prefix = f"batches/{batch_id}/organized"
                            batch_organized_key = f"{batch_prefix}/{organized_relative_path}/{final_filename}" if organized_relative_path else f"{batch_prefix}/{final_filename}"

                            with open(file_to_upload, 'rb') as file_data:
                                s3_client.put_object(
                                    Bucket=bucket,
                                    Key=batch_organized_key,
                                    Body=file_data.read(),
                                    ContentType=content_type,
                                    Metadata=metadata
                                )
                            print(f"Uploaded file to batch organized location: {batch_organized_key}")
                            result['batch_organized_key'] = batch_organized_key

                        # If this was a merged PDF, replace all matching vouchers with the merged PDF
                        if result.get('merged') and matching_keys:
                            print(f"🔄 Replacing {len(matching_keys)} matching vouchers with merged PDF...")
                            for match_key in matching_keys:
                                try:
                                    with open(file_to_upload, 'rb') as merged_data:
                                        # Get original metadata from the matching file
                                        try:
                                            orig_metadata_response = s3_client.head_object(Bucket=bucket, Key=match_key)
                                            orig_metadata = orig_metadata_response.get('Metadata', {})
                                        except:
                                            orig_metadata = metadata  # Use current metadata if can't get original
                                        
                                        s3_client.put_object(
                                            Bucket=bucket,
                                            Key=match_key,
                                            Body=merged_data.read(),
                                            ContentType='application/pdf',
                                            Metadata=orig_metadata
                                        )
                                    print(f"  ✅ Replaced {match_key} with merged PDF")
                                except Exception as replace_error:
                                    print(f"  ❌ Failed to replace {match_key}: {replace_error}")

                        # No metadata files created - user requested to eliminate them
                        print(f"Skipping metadata creation for file: {final_filename}")

                        # Delete from temp folder after successful organization
                        try:
                            s3_client.delete_object(Bucket=bucket, Key=s3_key)
                            print(f"🗑️ Deleted file from temp location: {s3_key}")
                        except Exception as delete_error:
                            print(f"⚠️ Failed to delete temp file (non-critical): {delete_error}")

                    except Exception as e:
                        print(f"Failed to copy to organized location: {str(e)}")
                        result['organized_key'] = None
                        result['batch_organized_key'] = None
                
                # CASE 2: Attachment document (FHE, TIS, etc.) - search for matching valid voucher
                elif result['success'] and needs_attachment:
                    print(f"📎 Processing attachment document: {result.get('classification')}")
                    
                    # Get matching criteria
                    weight = result.get('gold_weight')
                    purity = result.get('purity')
                    date = result.get('document_date')
                    amount_usd = result.get('invoice_amount_usd')
                    amount_aed = result.get('invoice_amount_aed')
                    
                    # Ensure we have the PDF file ready
                    file_to_upload = result.get('pdf_path', temp_file.name)
                    
                    # For attachments, either weight OR amount is required (along with date)
                    if weight or amount_usd or amount_aed:
                        print(f"🔍 Searching for matching valid voucher to attach to...")
                        matching_keys = find_matching_vouchers_in_s3(
                            bucket, weight, purity, date, amount_usd, amount_aed
                        )
                        
                        if matching_keys:
                            print(f"✅ Found {len(matching_keys)} matching voucher(s) for attachment")
                            
                            try:
                                # Use original PNG files from organized folder (stored alongside PDFs)
                                # This preserves perfect quality without any conversion!
                                temp_images = []
                                temp_files_to_cleanup = []
                                duplicate_attachment = False  # Track if attachment is a duplicate
                                
                                for match_key in matching_keys:
                                    # Look for ALL PNG files in same directory as PDF
                                    # Pattern: organized_vouchers/.../MPU01-85286_0001.pdf
                                    #   → MPU01-85286_0001_original.png (original voucher)
                                    #   → MPU01-85286_0001_attachment_1.png (first attachment)
                                    #   → MPU01-85286_0001_attachment_2.png (second attachment)
                                    # etc.
                                    
                                    # Get directory path
                                    directory = '/'.join(match_key.split('/')[:-1])
                                    print(f"  🔍 Looking for all PNGs in: {directory}/")
                                    
                                    try:
                                        # List all objects in this directory
                                        paginator = s3_client.get_paginator('list_objects_v2')
                                        found_pngs = []
                                        
                                        for page in paginator.paginate(Bucket=bucket, Prefix=directory + '/'):
                                            if 'Contents' in page:
                                                for obj in page['Contents']:
                                                    key = obj['Key']
                                                    # Look for PNG files with same base name
                                                    if key.endswith('.png') and match_key.replace('.pdf', '') in key:
                                                        found_pngs.append(key)
                                        
                                        # Sort PNGs: original first, then attachments in order
                                        found_pngs.sort(key=lambda x: (0 if '_original.png' in x else 1, x))
                                        
                                        print(f"  ✅ Found {len(found_pngs)} PNG file(s): {found_pngs}")
                                        
                                        # Check if this attachment already exists (by document_no and file size)
                                        current_doc_no = result.get('document_no')
                                        current_file_size = os.path.getsize(temp_file.name)
                                        duplicate_found = False
                                        
                                        if current_doc_no:
                                            print(f"  🔍 Checking for duplicate attachment: {current_doc_no} (size: {current_file_size} bytes)")
                                            checked_count = 0
                                            for png_key in found_pngs:
                                                if '_attachment_' in png_key:
                                                    checked_count += 1
                                                    try:
                                                        # Check metadata of existing attachment
                                                        meta_response = s3_client.head_object(Bucket=bucket, Key=png_key)
                                                        existing_doc_no = meta_response.get('Metadata', {}).get('document-no')
                                                        existing_size = meta_response.get('ContentLength', 0)
                                                        
                                                        print(f"    📋 Checking {png_key}: doc_no={existing_doc_no}, size={existing_size}")
                                                        
                                                        # Check by document number first (most reliable)
                                                        if existing_doc_no and existing_doc_no == current_doc_no:
                                                            print(f"  ⚠️ Duplicate attachment detected by document_no! {current_doc_no} already exists in {png_key}")
                                                            duplicate_found = True
                                                            break
                                                        
                                                        # Fallback: Check by file size (for old attachments without metadata)
                                                        if existing_size == current_file_size:
                                                            print(f"  ⚠️ Duplicate attachment detected by file size! {current_file_size} bytes matches {png_key}")
                                                            duplicate_found = True
                                                            break
                                                            
                                                    except Exception as meta_err:
                                                        print(f"    ⚠️ Could not check {png_key}: {meta_err}")
                                                        pass
                                            
                                            print(f"  ✅ Checked {checked_count} existing attachments - duplicate_found={duplicate_found}")
                                        
                                        if duplicate_found:
                                            print(f"  ⏭️ Skipping duplicate attachment - already merged")
                                            result['success'] = True
                                            result['duplicate_skipped'] = True
                                            result['message'] = f"Attachment {current_doc_no} already exists - skipped"
                                            duplicate_attachment = True
                                            break  # Break out of match_key loop
                                        
                                        # Download all PNGs
                                        for png_key in found_pngs:
                                            temp_png = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
                                            s3_client.download_file(bucket, png_key, temp_png.name)
                                            temp_images.append(temp_png.name)
                                            temp_files_to_cleanup.append(temp_png.name)
                                            print(f"    📥 Downloaded: {png_key}")
                                        
                                    except Exception as png_err:
                                        print(f"  ⚠️ Could not find PNGs: {png_err}")
                                        print(f"  ⚠️ Skipping match - original PNG not available")
                                        continue
                                
                                if duplicate_attachment:
                                    # Duplicate was detected and skipped - this is a success case
                                    print(f"  ✅ Duplicate attachment handling complete")
                                    pass  # Result already set to success, nothing more to do
                                elif not temp_images:
                                    # No valid images to merge with
                                    print(f"  ⚠️ Could not find original PNG files for matching vouchers")
                                    print(f"  ⚠️ Attachment will be marked as failed")
                                    result['success'] = False
                                    result['error'] = "Original PNG not found in organized folder for matching voucher"
                                    result['validation_failed'] = True
                                else:
                                    # Add current attachment image (PNG)
                                    temp_images.append(temp_file.name)  # Original PNG, not PDF
                                    print(f"  📎 Adding new attachment PNG to merge")
                                    
                                    # Merge all PNG images directly into one multi-page PDF
                                    merged_pdf_path = tempfile.NamedTemporaryFile(suffix='_merged.pdf', delete=False).name
                                    temp_files_to_cleanup.append(merged_pdf_path)
                                    ocr_service._merge_png_images_to_pdf(temp_images, merged_pdf_path)
                                    print(f"  ✅ Merged {len(temp_images)} PNG images into multi-page PDF")
                                    
                                    # Store the current attachment as a numbered PNG file
                                    # This allows future attachments to include ALL previous ones
                                    for match_key in matching_keys:
                                        # Get original metadata first
                                        try:
                                            orig_metadata_response = s3_client.head_object(Bucket=bucket, Key=match_key)
                                            orig_metadata = orig_metadata_response.get('Metadata', {})
                                        except:
                                            orig_metadata = {}
                                        
                                        # Count existing attachments to determine next number
                                        directory = '/'.join(match_key.split('/')[:-1])
                                        attachment_num = 1
                                        
                                        # Find highest attachment number
                                        try:
                                            paginator = s3_client.get_paginator('list_objects_v2')
                                            for page in paginator.paginate(Bucket=bucket, Prefix=directory + '/'):
                                                if 'Contents' in page:
                                                    for obj in page['Contents']:
                                                        if '_attachment_' in obj['Key']:
                                                            # Extract number from _attachment_N.png
                                                            num_match = re.search(r'_attachment_(\d+)\.png', obj['Key'])
                                                            if num_match:
                                                                num = int(num_match.group(1))
                                                                attachment_num = max(attachment_num, num + 1)
                                        except Exception as count_err:
                                            print(f"  ⚠️ Error counting attachments: {count_err}")
                                            pass
                                        
                                        # Store current attachment PNG with its own document_no in metadata
                                        attachment_png_key = match_key.replace('.pdf', f'_attachment_{attachment_num}.png')
                                        
                                        # Create metadata for attachment (include attachment's document_no for duplicate detection)
                                        attachment_metadata = orig_metadata.copy()
                                        if result.get('document_no'):
                                            attachment_metadata['document-no'] = result.get('document_no')
                                        if result.get('classification'):
                                            attachment_metadata['classification'] = result.get('classification')
                                        if result.get('document_date'):
                                            attachment_metadata['document-date'] = result.get('document_date')
                                        
                                        with open(temp_file.name, 'rb') as attachment_data:
                                            s3_client.put_object(
                                                Bucket=bucket,
                                                Key=attachment_png_key,
                                                Body=attachment_data.read(),
                                                ContentType='image/png',
                                                Metadata=attachment_metadata
                                            )
                                        print(f"  📦 Stored attachment PNG: {attachment_png_key}")
                                        
                                        # Replace PDF with merged version
                                        with open(merged_pdf_path, 'rb') as merged_data:
                                            
                                            s3_client.put_object(
                                                Bucket=bucket,
                                                Key=match_key,
                                                Body=merged_data.read(),
                                                ContentType='application/pdf',
                                                Metadata=orig_metadata
                                            )
                                        print(f"  ✅ Merged attachment into: {match_key}")
                                        
                                        # Also upload to batch organized folder if this is under organized_vouchers
                                        if match_key.startswith('organized_vouchers/') and batch_id and batch_id.lower() != 'unknown':
                                            # Extract the relative path from organized_vouchers
                                            relative_path = match_key[len('organized_vouchers/'):]
                                            batch_key = f"batches/{batch_id}/organized/{relative_path}"
                                            
                                            with open(merged_pdf_path, 'rb') as merged_data:
                                                s3_client.put_object(
                                                    Bucket=bucket,
                                                    Key=batch_key,
                                                    Body=merged_data.read(),
                                                    ContentType='application/pdf',
                                                    Metadata=orig_metadata
                                                )
                                            print(f"  ✅ Also uploaded merged PDF to batch: {batch_key}")
                                    
                                    result['attached_to'] = matching_keys
                                    result['merged'] = True
                                    result['merged_count'] = len(matching_keys) + 1
                                    
                                    # Clean up all temp files
                                    for temp_file_path in temp_files_to_cleanup:
                                        try:
                                            if os.path.isdir(temp_file_path):
                                                import shutil
                                                shutil.rmtree(temp_file_path)
                                            elif os.path.exists(temp_file_path):
                                                os.unlink(temp_file_path)
                                        except Exception as cleanup_err:
                                            print(f"  ⚠️ Cleanup error (non-critical): {cleanup_err}")
                                
                                # Delete attachment from temp folder after successful merge
                                try:
                                    s3_client.delete_object(Bucket=bucket, Key=s3_key)
                                    print(f"🗑️ Deleted attachment from temp location: {s3_key}")
                                except Exception as delete_error:
                                    print(f"⚠️ Failed to delete temp file (non-critical): {delete_error}")
                                
                            except Exception as merge_error:
                                print(f"❌ Error merging attachment: {merge_error}")
                                import traceback
                                traceback.print_exc()
                                result['success'] = False
                                result['error'] = f"Failed to merge attachment: {str(merge_error)}"
                                result['validation_failed'] = True
                                
                                # Clean up temp files on error
                                for temp_file_path in temp_files_to_cleanup:
                                    try:
                                        if os.path.isdir(temp_file_path):
                                            import shutil
                                            shutil.rmtree(temp_file_path)
                                        elif os.path.exists(temp_file_path):
                                            os.unlink(temp_file_path)
                                    except:
                                        pass
                        else:
                            # No matching voucher found for attachment - store in attached_voucher folder for future use
                            print(f"📎 No matching voucher found for attachment {result.get('classification')} - storing for future use")
                            
                            # Get original file extension
                            file_extension = os.path.splitext(filename)[1]  # Will be .png, .jpg, or .jpeg
                            attachment_filename = f"{result.get('document_no', filename_only)}{file_extension}"
                            attachment_key = f"attached_voucher/{batch_id}/{attachment_filename}"
                            
                            try:
                                # Copy attachment to attached_voucher folder (keep original image format)
                                s3_client.copy_object(
                                    Bucket=bucket,
                                    CopySource={'Bucket': bucket, 'Key': s3_key},
                                    Key=attachment_key,
                                    MetadataDirective='COPY'
                                )
                                print(f"📎 Stored unmatched attachment: {attachment_key}")
                                
                                # Delete from temp folder
                                s3_client.delete_object(Bucket=bucket, Key=s3_key)
                                print(f"🗑️ Deleted from temp location: {s3_key}")
                                
                                # Mark as successfully handled (no retry needed)
                                result['success'] = True
                                result['processing_status'] = 'completed'  # Pending attachments are successfully processed
                                result['attached_voucher_key'] = attachment_key
                                result['message'] = 'Attachment stored for future matching'
                                result['validation_failed'] = False
                                
                            except Exception as storage_error:
                                print(f"❌ Failed to store attachment: {storage_error}")
                                result['success'] = False
                                result['error'] = f"Failed to store attachment: {str(storage_error)}"
                                result['validation_failed'] = True
                    else:
                        # Missing both weight and amount data - store in attached_voucher for future use
                        print(f"📎 Attachment missing weight AND amount data - storing for future use")
                        
                        # Get original file extension
                        file_extension = os.path.splitext(filename)[1]  # Will be .png, .jpg, or .jpeg
                        attachment_filename = f"{result.get('document_no', filename_only)}{file_extension}"
                        attachment_key = f"attached_voucher/{batch_id}/{attachment_filename}"
                        
                        try:
                            # Copy attachment to attached_voucher folder (keep original image format)
                            s3_client.copy_object(
                                Bucket=bucket,
                                CopySource={'Bucket': bucket, 'Key': s3_key},
                                Key=attachment_key,
                                MetadataDirective='COPY'
                            )
                            print(f"📎 Stored attachment with missing data: {attachment_key}")
                            
                            # Delete from temp folder
                            s3_client.delete_object(Bucket=bucket, Key=s3_key)
                            print(f"🗑️ Deleted from temp location: {s3_key}")
                            
                            # Mark as successfully handled (no retry needed)
                            result['success'] = True
                            result['processing_status'] = 'completed'  # Pending attachments are successfully processed
                            result['attached_voucher_key'] = attachment_key
                            result['message'] = 'Attachment stored (missing matching data)'
                            result['validation_failed'] = False
                            
                        except Exception as storage_error:
                            print(f"❌ Failed to store attachment: {storage_error}")
                            result['success'] = False
                            result['error'] = f"Failed to store attachment: {str(storage_error)}"
                            result['validation_failed'] = True
                
                return {
                    'success': result['success'],
                    'document_no': result.get('document_no'),
                    'classification': result.get('classification'), 
                    'document_date': result.get('document_date'),
                    'branch_id': result.get('branch_id'),
                    'method': result.get('method'),
                    'confidence': result.get('confidence'),
                    'original_key': s3_key,
                    'batch_id': batch_id,
                    'organized_path': result.get('organized_path'),
                    'organized_key': result.get('organized_key'),
                    'batch_organized_key': result.get('batch_organized_key'),
                    'failed_key': result.get('failed_key'),
                    'validation_failed': result.get('validation_failed', False),
                    'error': result.get('error'),
                    'invoice_amount_usd': result.get('invoice_amount_usd'),
                    'invoice_amount_aed': result.get('invoice_amount_aed'),
                    'gold_weight': result.get('gold_weight'),
                    'purity': result.get('purity'),
                    'discount_rate': result.get('discount_rate'),
                    'is_valid_voucher': result.get('is_valid_voucher', False),
                    'needs_attachment': result.get('needs_attachment', False),
                    'attached_to': result.get('attached_to', []),
                    'merged': result.get('merged', False),
                    'merged_count': result.get('merged_count', 0)
                }
                
            finally:
                # Clean up temp files (both original and converted PDF if exists)
                if os.path.exists(temp_file.name):
                    os.unlink(temp_file.name)
                    print(f"Cleaned up temp file: {temp_file.name}")
                
                # Clean up converted PDF file if it exists and is different from temp file
                pdf_path = result.get('pdf_path') if 'result' in locals() else None
                if pdf_path and pdf_path != temp_file.name and os.path.exists(pdf_path):
                    os.unlink(pdf_path)
                    print(f"Cleaned up converted PDF file: {pdf_path}")
                    
    except Exception as e:
        print(f"Error in process_single_image: {str(e)}")
        return {
            'success': False,
            'error': str(e),
            'original_key': s3_key if 's3_key' in locals() else 'unknown'
        }

def send_processed_message(s3_key, batch_id, processing_result, document_id):
    """Send processing result to processed queue"""
    try:
        message_body = {
            'voucher_id': document_id,  # Add voucher_id for DynamoDB saver Lambda
            'status': 'processed',
            'processing_status': processing_result.get('processing_status', 'completed'),  # Default to completed
            'timestamp': datetime.now().isoformat(),
            'original_key': s3_key,
            'batch_id': batch_id,
            'success': processing_result['success'],
            'document_no': processing_result.get('document_no'),
            'classification': processing_result.get('classification'),
            'document_date': processing_result.get('document_date'),
            'branch_id': processing_result.get('branch_id'),
            'method': processing_result.get('method', 'comprehensive_ocr'),
            'confidence': processing_result.get('confidence', 0.95),
            'ocr_text': processing_result.get('ocr_text', ''),
            'organized_path': processing_result.get('organized_path'),
            'organized_key': processing_result.get('organized_key'),
            'batch_organized_key': processing_result.get('batch_organized_key'),
            'converted_to_pdf': processing_result.get('converted_to_pdf', False),
            'file_format': 'pdf' if processing_result.get('converted_to_pdf', False) else 'image',
            'pdf_path': processing_result.get('pdf_path', ''),
            'invoice_amount_usd': processing_result.get('invoice_amount_usd'),
            'invoice_amount_aed': processing_result.get('invoice_amount_aed'),
            'gold_weight': processing_result.get('gold_weight'),
            'purity': processing_result.get('purity'),
            'discount_rate': processing_result.get('discount_rate'),
            'is_valid_voucher': processing_result.get('is_valid_voucher', False),
            'needs_attachment': processing_result.get('needs_attachment', False),
            'attached_to': processing_result.get('attached_to', []),
            'merged': processing_result.get('merged', False),
            'merged_count': processing_result.get('merged_count', 0)
        }
        
        if not processing_result['success']:
            message_body['error'] = processing_result.get('error', 'Unknown error')
        
        response = sqs_client.send_message(
            QueueUrl=PROCESSED_QUEUE_URL,
            MessageBody=json.dumps(message_body),
            MessageAttributes={
                'BatchId': {
                    'DataType': 'String',
                    'StringValue': batch_id
                },
                'Status': {
                    'DataType': 'String', 
                    'StringValue': 'processed'
                },
                'Success': {
                    'DataType': 'String',
                    'StringValue': str(processing_result['success']).lower()
                },
                'Classification': {
                    'DataType': 'String',
                    'StringValue': processing_result.get('classification', 'UNKNOWN')
                }
            }
        )
        
        return True
        
    except Exception as e:
        print(f"Error sending processed message: {str(e)}")
        return False
