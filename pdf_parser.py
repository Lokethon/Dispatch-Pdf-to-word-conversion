"""
pdf_parser.py — Extracts dispatch-relevant data from GST Invoice PDFs.

Parses the "Ship To" section and "Order No" from Dazller-style GST invoices.
Supports both text-based PDFs (via pdfplumber) and image-based/scanned PDFs
(via pypdfium2 rendering + EasyOCR).

Handles multi-page PDFs where each page is a separate invoice.
"""

import re
import os
import logging
import numpy as np
import pdfplumber
import pypdfium2 as pdfium
from PIL import Image

logger = logging.getLogger("DispatchBot")

# Lazy-loaded EasyOCR reader (initialized on first OCR call)
_ocr_reader = None


def _get_ocr_reader():
    """Lazy-initialize EasyOCR reader (downloads model on first run)."""
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        logger.info("🔤 Initializing OCR engine (first time may download models)...")
        _ocr_reader = easyocr.Reader(["en"], gpu=False)
        logger.info("🔤 OCR engine ready.")
    return _ocr_reader


def extract_all_orders(pdf_path: str, progress_callback=None) -> list[dict]:
    """
    Extract dispatch label data from ALL pages of a GST invoice PDF.
    Each page is treated as a separate invoice/order.

    Args:
        pdf_path: Path to the PDF file
        progress_callback: Optional async callback(page_num, total_pages, status)

    Returns a list of dicts, each with:
        - order_id: str (e.g., "15125")
        - customer_name: str
        - address_line1: str
        - address_line2: str (City, State - Pincode)
        - phone: str (10-digit, +91 stripped)
    """
    # Get page-by-page text (either from text layer or OCR)
    page_texts = _extract_text_per_page(pdf_path)

    if not page_texts:
        raise ValueError(f"Could not extract any text from PDF: {pdf_path}")

    orders = []
    errors = []
    filename = os.path.basename(pdf_path)

    for page_num, page_text in enumerate(page_texts, start=1):
        if not page_text.strip():
            errors.append(f"Page {page_num}: Empty/unreadable")
            continue

        try:
            order_id = _extract_order_no(page_text)
            ship_to_data = _extract_ship_to(page_text)

            order = {
                "order_id": order_id,
                "customer_name": ship_to_data["name"],
                "address_line1": ship_to_data["address_line1"],
                "address_line2": ship_to_data["address_line2"],
                "phone": ship_to_data["phone"],
            }
            orders.append(order)
            logger.info(
                f"   ✅ Page {page_num}: Order #D{order_id} — {ship_to_data['name']}"
            )
        except Exception as e:
            error_msg = f"Page {page_num}: {str(e)}"
            errors.append(error_msg)
            logger.warning(f"   ⚠️ {filename} {error_msg}")

    if errors:
        logger.warning(
            f"   ⚠️ {filename}: {len(errors)} page(s) had issues: "
            + "; ".join(errors)
        )

    return orders


def _extract_text_per_page(pdf_path: str) -> list[str]:
    """
    Extract text from each page of the PDF.
    First tries pdfplumber (text layer), falls back to OCR per page.
    Returns a list of strings, one per page.
    """
    page_texts = []
    needs_ocr = False

    # Step 1: Try pdfplumber for text-based PDFs
    try:
        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            logger.info(f"   📄 PDF has {total_pages} page(s)")

            for page in pdf.pages:
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    page_texts.append(page_text)
                else:
                    page_texts.append("")  # Mark as empty for OCR fallback

            # Check if any pages got no text
            empty_count = sum(1 for t in page_texts if not t.strip())
            if empty_count == total_pages:
                needs_ocr = True
                page_texts = []  # Reset, will use OCR for all
            elif empty_count > 0:
                # Some pages need OCR — use OCR for those
                needs_ocr = True

    except Exception as e:
        logger.warning(f"   ⚠️ pdfplumber failed: {e}")
        needs_ocr = True

    # Step 2: Fall back to OCR for pages that had no text
    if needs_ocr:
        logger.info(
            f"   📷 Using OCR for: {os.path.basename(pdf_path)}"
        )
        ocr_texts = _extract_text_ocr_per_page(pdf_path)

        if not page_texts:
            # All pages need OCR
            page_texts = ocr_texts
        else:
            # Fill in empty pages with OCR results
            for i in range(len(page_texts)):
                if not page_texts[i].strip() and i < len(ocr_texts):
                    page_texts[i] = ocr_texts[i]

    return page_texts


def _extract_text_ocr_per_page(pdf_path: str) -> list[str]:
    """
    Extract text from each page of an image-based PDF using pypdfium2 + EasyOCR.
    Returns a list of strings, one per page.
    """
    reader = _get_ocr_reader()
    page_texts = []

    try:
        pdf = pdfium.PdfDocument(pdf_path)
        total_pages = len(pdf)

        for page_index in range(total_pages):
            page = pdf[page_index]
            logger.info(f"   🔍 OCR processing page {page_index + 1}/{total_pages}...")

            # Render at 300 DPI for good OCR quality
            bitmap = page.render(scale=300 / 72)
            pil_image = bitmap.to_pil()

            # Convert PIL image to numpy array (EasyOCR requires numpy)
            img_array = np.array(pil_image)

            # Run OCR on the image
            results = reader.readtext(
                img_array,
                detail=0,          # Return text only, no bounding boxes
                paragraph=False,   # Don't merge into paragraphs (keep structure)
            )

            page_text = "\n".join(results)
            page_texts.append(page_text)
            logger.info(
                f"   📝 Page {page_index + 1}: extracted {len(page_text)} chars"
            )

        pdf.close()
    except Exception as e:
        logger.error(f"   ❌ OCR extraction failed: {e}")
        raise ValueError(f"OCR extraction failed for {pdf_path}: {e}")

    return page_texts


def _extract_order_no(text: str) -> str:
    """Extract Order No from the invoice text."""
    # Try patterns like "Order No: 15125" or "Order No:15125" or "Order No 15125"
    patterns = [
        r"Order\s*No\s*[:\.]?\s*(\d+)",
        r"Order\s*Number\s*[:\.]?\s*(\d+)",
        r"Order\s*Id\s*[:\.]?\s*#?D?(\d+)",
        # OCR might produce slightly different formatting
        r"Order\s*No\s*[:\.\-]?\s*(\d{4,})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1).strip()

    raise ValueError("Could not find Order No in the PDF")


def _extract_ship_to(text: str) -> dict:
    """
    Extract the Ship To section from the invoice text.

    Returns dict with: name, address_line1, address_line2, phone
    """
    # Normalize line endings
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    lines = [line.strip() for line in lines if line.strip()]

    # Find the "Ship To" marker
    ship_to_start = None
    for i, line in enumerate(lines):
        if re.match(r"^Ship\s*To\s*$", line, re.IGNORECASE):
            ship_to_start = i
            break

    if ship_to_start is None:
        # Try alternate: "Ship To" might be part of a longer line
        for i, line in enumerate(lines):
            if re.search(r"Ship\s*To", line, re.IGNORECASE):
                ship_to_start = i
                break

    if ship_to_start is None:
        raise ValueError("Could not find 'Ship To' section in the PDF")

    # Collect Ship To lines until we hit a table header or known boundary
    ship_to_lines = []
    stop_keywords = [
        "Item", "HSN", "Qty", "Unit", "Gross", "Discount",
        "Taxable", "GST", "IGST", "Total", "Billed To",
        "Terms and Conditions", "Amount in words",
    ]

    for i in range(ship_to_start + 1, min(ship_to_start + 15, len(lines))):
        line = lines[i]
        # Check if we've hit a boundary
        if any(kw.lower() in line.lower() for kw in stop_keywords):
            break
        ship_to_lines.append(line)

    if len(ship_to_lines) < 2:
        raise ValueError(
            f"Ship To section has too few lines: {ship_to_lines}"
        )

    # Deduplicate side-by-side columns (e.g. "Roshini Vijay Roshini Vijay")
    cleaned_lines = []
    for line in ship_to_lines:
        clean = re.sub(r'\s+', ' ', line).strip()
        
        # Check word-based exact halves
        words = clean.split()
        if len(words) > 0 and len(words) % 2 == 0:
            half = len(words) // 2
            if words[:half] == words[half:]:
                clean = " ".join(words[:half])
                
        # Check comma-based exact halves (e.g. "Peta, Peta")
        parts = [p.strip() for p in clean.split(',') if p.strip()]
        if len(parts) > 0 and len(parts) % 2 == 0:
            half = len(parts) // 2
            if parts[:half] == parts[half:]:
                clean = ", ".join(parts[:half])
                
        cleaned_lines.append(clean)
        
    ship_to_lines = cleaned_lines

    # Parse the Ship To lines
    name = ""
    address_parts = []
    phone = ""
    city = ""
    state = ""
    pincode = ""

    for line in ship_to_lines:
        # Check for phone/tel line
        tel_match = re.match(
            r"^(?:Tel|Phone|Ph|Mobile)\s*[:\.]?\s*(.+)$",
            line, re.IGNORECASE
        )
        if tel_match:
            phone = _clean_phone(tel_match.group(1).strip())
            continue

        # Check for pin/pincode line (e.g., "Khammam, Pin: 507001, Telangana , India")
        pin_match = re.search(
            r"(?:Pin|Pincode|PIN)\s*[:\.]?\s*(\d{6})", line, re.IGNORECASE
        )
        if pin_match:
            pincode = pin_match.group(1)
            # Extract city and state from this line
            city, state = _parse_city_state_line(line, pincode)
            continue

        # Also check for standalone 6-digit pincode patterns like "500081" in address
        # after city and state (e.g., "Hyderabad, Telangana - 500081")
        pin_alt_match = re.search(
            r"[,\-\s]\s*(\d{6})\s*$", line
        )
        if pin_alt_match and not pincode:
            pincode = pin_alt_match.group(1)
            city, state = _parse_city_state_alt(line, pincode)
            continue

        # If no name yet, this is the customer name
        if not name:
            name = line
        else:
            # It's an address line
            address_parts.append(line)

    # Build address_line2: "City, State - Pincode"
    if city and state and pincode:
        address_line2 = f"{city}, {state} - {pincode}"
    elif city and pincode:
        address_line2 = f"{city} - {pincode}"
    elif pincode:
        address_line2 = f"{pincode}"
    else:
        address_line2 = ""

    # address_line1 is the street address
    address_line1 = ", ".join(address_parts) if address_parts else ""

    # Clean up: remove email addresses (e.g., "Email: xyz@gmail.com")
    address_line1 = re.sub(
        r",?\s*(?:Email|E-mail)\s*[:\.]?\s*\S+@\S+", "",
        address_line1, flags=re.IGNORECASE
    ).strip()

    # Clean up: remove ALL occurrences of "India" from address
    address_line1 = re.sub(
        r",?\s*India\b", "", address_line1, flags=re.IGNORECASE
    ).strip()

    # Clean up stray trailing/leading commas and extra spaces
    address_line1 = re.sub(r",\s*,", ",", address_line1)  # double commas
    address_line1 = re.sub(r",\s*$", "", address_line1).strip()  # trailing comma
    address_line1 = re.sub(r"^\s*,", "", address_line1).strip()  # leading comma

    return {
        "name": name,
        "address_line1": address_line1,
        "address_line2": address_line2,
        "phone": phone,
    }


def _clean_phone(phone_str: str) -> str:
    """
    Clean phone number: strip +91, spaces, dashes.
    Returns a clean 10-digit number.
    """
    # Remove all non-digit characters
    digits = re.sub(r"[^\d]", "", phone_str)

    # Strip country code +91 (if 12 digits starting with 91)
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    # Strip country code 0 prefix
    elif len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    return digits


def _parse_city_state_line(line: str, pincode: str) -> tuple:
    """
    Parse a line like "Khammam, Pin: 507001, Telangana , India"
    into (city, state).
    """
    # Remove the pin part and "India"
    cleaned = re.sub(
        r"(?:Pin|Pincode|PIN)\s*[:\.]?\s*\d{6}", "", line, flags=re.IGNORECASE
    )
    cleaned = re.sub(r",?\s*India\s*$", "", cleaned, flags=re.IGNORECASE)

    # Split by comma and clean
    parts = [p.strip().strip(",").strip() for p in cleaned.split(",")]
    parts = [p for p in parts if p]  # Remove empty parts

    if len(parts) >= 2:
        city = parts[0]
        state = parts[1]
    elif len(parts) == 1:
        city = parts[0]
        state = ""
    else:
        city = ""
        state = ""

    return city, state


def _parse_city_state_alt(line: str, pincode: str) -> tuple:
    """
    Parse a line like "Hyderabad, Telangana - 500081"
    into (city, state).
    """
    # Remove pincode and surrounding separators
    cleaned = re.sub(r"[\-,\s]*\d{6}\s*$", "", line).strip()

    # Split by comma or hyphen
    parts = re.split(r"[,\-]", cleaned)
    parts = [p.strip() for p in parts if p.strip()]

    if len(parts) >= 2:
        city = parts[0]
        state = parts[1]
    elif len(parts) == 1:
        city = parts[0]
        state = ""
    else:
        city = ""
        state = ""

    return city, state


if __name__ == "__main__":
    # Quick test with a local PDF
    import sys
    logging.basicConfig(level=logging.INFO)
    if len(sys.argv) > 1:
        results = extract_all_orders(sys.argv[1])
        print(f"\nExtracted {len(results)} order(s):\n")
        for i, order in enumerate(results, 1):
            print(f"--- Order {i} ---")
            for key, value in order.items():
                print(f"  {key}: {value}")
            print()
    else:
        print("Usage: python pdf_parser.py <path_to_pdf>")
