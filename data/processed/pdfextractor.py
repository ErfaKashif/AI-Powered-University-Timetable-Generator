"""
Extract the master university timetable PDF into a clean, cell-level CSV.

Install:
    pip install pdfplumber

Run from the project folder:
    python pdf_extractor.py "FAST-NUCES, Karachi Campus Timetable FALL 2026 Version 0.pdf"

Optional output path:
    python pdfextractor.py "input.pdf" "data/processed/timetable_cells.csv"
This script deliberately preserves each timetable cell as raw text.
A separate parser should later split the cell into course code, section,
course name, teacher, and student count. This avoids losing information
when names or course titles contain commas or line breaks.
"""

import argparse
import csv
import re
from pathlib import Path

import pdfplumber


DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def clean_text(value):
    """Convert a PDF cell to one readable line of text."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def find_day(page_text):
    """Find a weekday mentioned on the current page."""
    text = page_text or ""
    for day in DAYS:
        if re.search(r"\b" + day + r"\b", text, flags=re.IGNORECASE):
            return day
    return None


def find_header_row(table):
    """
    Find the row containing the room/venue heading.
    Returns (row_index, cleaned_header_cells), or (None, None).
    """
    for row_index, row in enumerate(table):
        cells = [clean_text(cell) for cell in row]
        first_cell = cells[0].lower() if cells else ""

        if first_cell in ("venue", "room", "rooms", "classroom"):
            return row_index, cells

    return None, None


def extract_timetable(input_pdf, output_csv):
    records = []
    current_day = None
    last_headers = None

    with pdfplumber.open(input_pdf) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""
            detected_day = find_day(page_text)

            if detected_day:
                current_day = detected_day

            tables = page.extract_tables() or []

            for table in tables:
                if not table:
                    continue

                header_index, headers = find_header_row(table)

                if headers is not None:
                    last_headers = headers
                    data_start = header_index + 1
                elif last_headers is not None:
                    # Some continuation pages may not repeat the header.
                    headers = last_headers
                    data_start = 0
                else:
                    # Ignore tables until a recognizable timetable header appears.
                    continue

                for row in table[data_start:]:
                    if not row:
                        continue

                    cells = [clean_text(cell) for cell in row]
                    if not any(cells):
                        continue

                    room = cells[0] if cells else ""

                    # Skip repeated headers and rows without a room/venue label.
                    if room.lower() in ("venue", "room", "rooms", "classroom"):
                        continue
                    if not room:
                        continue

                    for column_index in range(1, min(len(cells), len(headers))):
                        cell_text = cells[column_index]
                        if not cell_text:
                            continue

                        time_slot = headers[column_index]

                        records.append({
                            "page": page_number,
                            "day": current_day or "",
                            "room": room,
                            "time_slot": time_slot,
                            "cell_text": cell_text,
                        })

    output_path = Path(output_csv)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["page", "day", "room", "time_slot", "cell_text"]
    with output_path.open("w", newline="", encoding="utf-8-sig") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(records)

    print(f"PDF pages processed: {len(pdf.pages)}")
    print(f"Occupied timetable cells extracted: {len(records)}")
    print(f"CSV saved to: {output_path.resolve()}")

def main():
    parser = argparse.ArgumentParser(
        description="Extract raw timetable cells from the master timetable PDF."
    )
    parser.add_argument("input_pdf", help="Path to the master timetable PDF")
    parser.add_argument(
        "output_csv",
        nargs="?",
        default="timetable_cells_v0.csv",
        help="Output CSV path (default: timetable_cells_v0.csv)",
    )
    args = parser.parse_args()

    input_path = Path(args.input_pdf)
    if not input_path.is_file():
        raise FileNotFoundError(f"PDF file not found: {args.input_pdf}")

    # Extract the last character before .pdf
    in_stem = input_path.stem.strip()
    version = in_stem[-1] if in_stem else ""

    # Append _v<version> to whatever output filename is being used
    out_path = Path(args.output_csv)
    if version:
        out_path = out_path.with_name(f"{out_path.stem}_v{version}{out_path.suffix}")

    extract_timetable(args.input_pdf, out_path)

if __name__ == "__main__":
    main()
