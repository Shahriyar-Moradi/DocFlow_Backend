# Performance Analysis - Document Upload and Processing

## Current Bottlenecks Identified

### 1. **Two Sequential API Calls** (Major Impact)
- **Classification**: ~2-5 seconds per call
- **Extraction**: ~3-8 seconds per call
- **Total**: 5-13 seconds just for API calls
- **Location**: `process_document()` calls `_classify_document_type()` then `_extract_general_document_data()`

### 2. **Long Retry Delays** (Major Impact)
- **Current**: 30 seconds delay between retries
- **Max Retries**: 3 attempts
- **Worst Case**: Up to 90 seconds of waiting on retries alone
- **Location**: `config.py` - `OCR_RETRY_DELAY = 30`

### 3. **Large Token Limits** (Moderate Impact)
- **Classification**: 512 tokens
- **General Extraction**: 2048 tokens
- **Voucher Extraction**: 1024 tokens
- **Impact**: Larger token limits = slower API responses

### 4. **GCS Operations** (Moderate Impact)
- Download from GCS temp folder
- Process document
- Upload back to organized location
- **Total**: ~1-3 seconds for GCS operations

### 5. **Base64 Encoding** (Minor Impact)
- Encoding large images to base64
- **Impact**: ~0.5-1 second for large images

### 6. **PDF Conversion** (Minor Impact)
- Converting images to PDF
- **Impact**: ~0.5-2 seconds

## Total Estimated Time

**Current Average**: 10-20 seconds per document
**Worst Case**: 60-120 seconds (with retries)

## Optimization Recommendations

### Quick Wins (High Impact, Low Effort)

1. **Reduce Retry Delay**
   - Change from 30 seconds to 5-10 seconds
   - **Impact**: Reduces worst-case time by 60-75 seconds

2. **Combine Classification and Extraction**
   - Single API call that does both
   - **Impact**: Reduces API time by 50% (5-13s → 3-8s)

3. **Reduce Token Limits**
   - Classification: 512 → 256 tokens
   - Extraction: 2048 → 1024 tokens
   - **Impact**: Faster API responses

4. **Make PDF Conversion Optional**
   - Only convert if needed
   - **Impact**: Saves 0.5-2 seconds

### Medium Effort (High Impact)

5. **Parallel Processing for Batch Uploads**
   - Process multiple documents concurrently
   - **Impact**: Batch uploads much faster

6. **Cache Classification Results**
   - Cache similar document classifications
   - **Impact**: Skip classification for similar documents

### Advanced Optimizations

7. **Streaming Responses**
   - Use streaming API for faster responses
   - **Impact**: Perceived faster responses

8. **Image Compression**
   - Compress images before API calls
   - **Impact**: Faster encoding and API calls

9. **Async GCS Operations**
   - Make GCS operations non-blocking
   - **Impact**: Better concurrency

## Recommended Immediate Changes

1. Reduce `OCR_RETRY_DELAY` from 30 to 5 seconds
2. Combine classification and extraction into one prompt
3. Reduce max_tokens for classification to 256
4. Add progress updates to user

