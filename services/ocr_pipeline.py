import base64
import os
import tempfile
from typing import Dict, Any

from anthropic import Anthropic


def _encode_image_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def _guess_media_type(filename: str) -> str:
    lower = filename.lower()
    if lower.endswith(".png"):
        return "image/png"
    if lower.endswith(".jpg") or lower.endswith(".jpeg"):
        return "image/jpeg"
    if lower.endswith(".pdf"):
        return "application/pdf"
    return "image/jpeg"


class OcrPipeline:
    """
    Small wrapper around Anthropic Claude Sonnet for OCR/classification.
    Takes raw bytes, writes to temp, encodes to base64, and sends a prompt.
    """

    def __init__(self, api_key: str | None = None):
        key = api_key or os.getenv("ANTHROPIC_API_KEY") or os.getenv("CLAUDE_API_KEY")
        if not key:
            raise ValueError("ANTHROPIC_API_KEY is required for OCR pipeline")
        self.client = Anthropic(api_key=key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-5-20250929")

    def process_file(self, data: bytes, filename: str) -> Dict[str, Any]:
        media_type = _guess_media_type(filename)

        # Persist to a temp file so we can encode reliably (works for pdf/images)
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1] or ".bin") as tmp:
            tmp.write(data)
            tmp_path = tmp.name

        try:
            base64_image = _encode_image_to_base64(tmp_path)
            response = self.client.messages.create(
                model=self.model,
                max_tokens=1024,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    "You are an OCR and document classification assistant. "
                                    "Extract key fields (voucher type, document number, date, amounts, branch) "
                                    "and return concise JSON. Include a short summary too."
                                ),
                            },
                            {
                                "type": "input_data",
                                "input_data": {
                                    "type": media_type,
                                    "data": base64_image,
                                },
                            },
                        ],
                    }
                ],
            )

            # Response content comes back as list; capture the first text block.
            text_blocks = [c.text for c in response.content if getattr(c, "type", "") == "text"]
            extracted = text_blocks[0] if text_blocks else ""
            return {
                "success": True,
                "model": self.model,
                "media_type": media_type,
                "raw_response": extracted,
            }
        except Exception as exc:
            return {"success": False, "error": str(exc), "model": self.model}
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
