#!/usr/bin/env python3
"""
Diagnostic helper to inspect a document in Firestore/GCS and understand why it
may be stuck, failed, or not yet ready for compliance checking.
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from google.cloud import firestore, storage

# Load env so we respect the same config used elsewhere in the repo
load_dotenv()

PROJECT_ID = os.getenv("GCS_PROJECT_ID", "rocasoft")
BUCKET_NAME = os.getenv("GCS_BUCKET_NAME", "voucher-bucket-1")
DOCUMENTS_COLLECTION = os.getenv("FIRESTORE_DOCUMENTS_COLLECTION", "documents")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Diagnose a document's processing/compliance status in Firestore"
    )
    parser.add_argument(
        "document_id",
        help="Document UUID to inspect (e.g. 17d3ee9d-8d71-4aec-98f8-2a8b8d4cff2c)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output raw Firestore document as JSON (in addition to formatted info)",
    )
    return parser.parse_args()


def format_ts(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S %Z")
        except ValueError:
            return value
    return str(value)


def fetch_document(document_id: str) -> Optional[Dict[str, Any]]:
    client = firestore.Client(project=PROJECT_ID)
    doc_ref = client.collection(DOCUMENTS_COLLECTION).document(document_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    data = snapshot.to_dict()
    data["document_id"] = snapshot.id
    return data


def check_gcs_paths(doc: Dict[str, Any]) -> List[str]:
    """Check whether referenced GCS blobs exist."""
    messages: List[str] = []
    storage_client = storage.Client(project=PROJECT_ID)
    bucket = storage_client.bucket(BUCKET_NAME)

    def _check_path(label: str, path: Optional[str]) -> None:
        if not path:
            messages.append(f"⚪ {label}: not set")
            return
        if path.startswith("gs://"):
            _, _, bucket_name, *rest = path.split("/", 3)
            blob_path = rest[0] if rest else ""
            target_bucket = (
                storage_client.bucket(bucket_name) if bucket_name else bucket
            )
        else:
            target_bucket = bucket
            blob_path = path
        blob = target_bucket.blob(blob_path)
        if blob.exists():
            size_kb = blob.size / 1024 if blob.size else 0
            messages.append(
                f"✅ {label}: found ({blob_path}, {size_kb:.1f} KB in {target_bucket.name})"
            )
        else:
            messages.append(f"⚠️ {label}: NOT FOUND ({blob_path} in {target_bucket.name})")

    _check_path("gcs_path", doc.get("gcs_path"))
    _check_path("gcs_temp_path", doc.get("gcs_temp_path"))
    return messages


def summarize_metadata(doc: Dict[str, Any]) -> List[str]:
    metadata = doc.get("metadata") or {}
    summary = []
    key_fields = [
        "classification",
        "document_no",
        "document_date",
        "branch_id",
        "invoice_amount_usd",
        "invoice_amount_aed",
        "gold_weight",
        "purity",
        "discount_rate",
        "ui_category",
    ]
    for key in key_fields:
        if metadata.get(key) is not None:
            summary.append(f"• {key}: {metadata.get(key)}")
    return summary or ["(no metadata fields present)"]


def summarize_extracted(doc: Dict[str, Any]) -> Tuple[str, Optional[str]]:
    extracted = doc.get("extracted_data")
    if not extracted:
        return "No extracted_data recorded.", None
    if isinstance(extracted, dict):
        pretty = json.dumps(extracted, indent=2, ensure_ascii=False)
        return "Extracted data (JSON):", pretty
    if isinstance(extracted, str):
        return "Extracted data (string):", extracted
    return "Extracted data present, unknown type.", str(extracted)


def summarize_compliance(doc: Dict[str, Any]) -> List[str]:
    compliance = doc.get("compliance_check")
    if not compliance:
        return ["No compliance check results stored."]
    lines = [
        f"Overall status: {compliance.get('overall_status', 'unknown')}",
        f"Checked at: {format_ts(compliance.get('check_timestamp'))}",
    ]
    if compliance.get("issues"):
        lines.append(
            f"Issues ({len(compliance['issues'])}): "
            + ", ".join(issue.get("field", "?") for issue in compliance["issues"])
        )
    if compliance.get("missing_fields"):
        lines.append(
            "Missing fields: " + ", ".join(compliance["missing_fields"])
        )
    if compliance.get("missing_signatures"):
        lines.append(
            "Missing signatures: " + ", ".join(compliance["missing_signatures"])
        )
    if compliance.get("missing_attachments"):
        lines.append(
            "Missing attachments: " + ", ".join(compliance["missing_attachments"])
        )
    return lines


def analyze(doc: Dict[str, Any]) -> List[str]:
    recommendations: List[str] = []
    status = doc.get("processing_status", "pending")
    created_at = doc.get("created_at")
    updated_at = doc.get("updated_at")
    now = datetime.now(timezone.utc)

    def _age(ts: Any) -> Optional[float]:
        if isinstance(ts, datetime):
            return (now - ts).total_seconds() / 60.0
        if isinstance(ts, str):
            try:
                parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                return (now - parsed).total_seconds() / 60.0
            except ValueError:
                return None
        return None

    minutes_since_create = _age(created_at)
    minutes_since_update = _age(updated_at)

    if status == "failed":
        recommendations.append(
            "❌ Document failed processing. Re-run OCR or re-upload the original file."
        )
        if doc.get("error"):
            recommendations.append(f"   Reason: {doc['error']}")
    elif status == "pending":
        if minutes_since_create and minutes_since_create > 5:
            recommendations.append(
                f"⏳ Document has been pending for {minutes_since_create:.1f} min. "
                "Verify the background task is running."
            )
        else:
            recommendations.append(
                "ℹ️ Document is pending. Wait for processing or trigger manual re-processing."
            )
    elif status == "processing":
        if minutes_since_update and minutes_since_update > 5:
            recommendations.append(
                f"⚠️ Document stuck in processing for {minutes_since_update:.1f} min. "
                "Check task queue logs."
            )
        else:
            recommendations.append(
                "⚙️ Document currently processing. Monitor until completion."
            )
    elif status == "completed":
        recommendations.append(
            "✅ Document processed. You can run compliance check if required."
        )
        if not doc.get("metadata"):
            recommendations.append(
                "⚠️ No metadata present despite completion. Confirm OCR extracted data."
            )
    else:
        recommendations.append(f"ℹ️ Unknown status '{status}'.")

    return recommendations


def print_section(title: str) -> None:
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def main():
    args = parse_args()
    document_id = args.document_id

    print_section(f"Document Diagnostics: {document_id}")
    print(f"Firestore project: {PROJECT_ID}")
    print(f"GCS bucket: {BUCKET_NAME}")

    doc = fetch_document(document_id)
    if not doc:
        print(f"❌ Document '{document_id}' not found in Firestore collection '{DOCUMENTS_COLLECTION}'.")
        return

    if args.json:
        print_section("Raw Firestore Document")
        print(json.dumps(doc, indent=2, default=str, ensure_ascii=False))

    print_section("Basic Information")
    print(f"Filename: {doc.get('filename') or doc.get('original_filename')}")
    print(f"Processing Status: {doc.get('processing_status', 'pending')}")
    print(f"Error: {doc.get('error') or '(none)'}")
    print(f"Created At: {format_ts(doc.get('created_at'))}")
    print(f"Updated At: {format_ts(doc.get('updated_at'))}")
    print(f"Document Type: {doc.get('document_type')}")
    print(f"Confidence: {doc.get('confidence')}")
    print(f"Flow ID: {doc.get('flow_id') or '(none)'}")

    print_section("Metadata")
    for line in summarize_metadata(doc):
        print(line)

    print_section("Extracted Data")
    header, body = summarize_extracted(doc)
    print(header)
    if body:
        print(body)

    print_section("Compliance Check")
    for line in summarize_compliance(doc):
        print(line)

    print_section("Storage Verification")
    for line in check_gcs_paths(doc):
        print(line)

    print_section("Recommendations")
    for line in analyze(doc):
        print(line)

    print("\nDone ✅")


if __name__ == "__main__":
    main()

