"""
Compare extracted master timetable cells against section-wise timetable PDF.

Input:
1. timetable_cells_v#.csv produced by pdf_extractor.py
2. Sections_Timetables FALL 2026_compressed_version0.pdf

Install:
    pip install pdfplumber

Run:
    python validator.py timetable_cells_v#.csv "Sections_Timetables FALL 2026_compressed_version0.pdf"

Optional report path:
    python validator.py timetable_cells_v#.csv "Sections_Timetables FALL 2026_compressed_version0.pdf" validation_report.csv

Important:
- The master PDF is treated as the primary source for course code, section,
  room, time slot, teacher, and student count.
- The section-wise PDF usually has no course code or student count, so the
  comparison uses section + day + slot and then compares the available text.
- A mismatch is a review flag, not proof that one PDF is wrong. PDF table
  extraction can split words or room names across lines.
"""

import argparse
import csv
import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

import pdfplumber


DAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")
SECTION_PATTERN = re.compile(r"\b([A-Z]{2,5}-\d+[A-Z]?)\b", re.IGNORECASE)


def clean_text(value):
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def normalize(value):
    """Normalize text for approximate comparison."""
    value = clean_text(value).lower()
    value = value.replace("–", "-").replace("—", "-")
    value = re.sub(r"[^a-z0-9]+", " ", value)
    return " ".join(value.split())


def normalize_slot(value):
    """Normalize spacing/punctuation in a timetable column heading."""
    value = normalize(value)
    value = value.replace(" ", "")
    return value


def find_day(text):
    for day in DAYS:
        if re.search(r"\b" + day + r"\b", text or "", re.IGNORECASE):
            return day
    return None


def find_section(text):
    match = SECTION_PATTERN.search(text or "")
    return match.group(1).upper() if match else None


def read_master_csv(csv_path):
    """Read raw occupied cells and identify the section code in each cell."""
    records = []

    with open(csv_path, "r", newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)

        required = {"day", "room", "time_slot", "cell_text"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError(
                "Master CSV is missing columns: " + ", ".join(sorted(missing))
            )

        for row_number, row in enumerate(reader, start=2):
            cell_text = clean_text(row.get("cell_text"))
            section = find_section(cell_text)

            if not cell_text:
                continue

            records.append({
                "source": "master",
                "source_row": row_number,
                "page": clean_text(row.get("page")),
                "section": section,
                "day": clean_text(row.get("day")),
                "slot": clean_text(row.get("time_slot")),
                "room": clean_text(row.get("room")),
                "cell_text": cell_text,
            })

    return records


def find_day_header(table):
    """Find the header row whose first cell is Day."""
    for index, row in enumerate(table):
        first = clean_text(row[0]).lower() if row else ""
        if first == "day":
            return index, [clean_text(cell) for cell in row]
    return None, None


def read_section_pdf(pdf_path):
    """
    Extract section timetable cells.
    Each page normally represents one section; day rows are read from the
    first column and time slots from the table header.
    """
    records = []
    current_section = None
    current_day = None
    previous_headers = None

    with pdfplumber.open(pdf_path) as pdf:
        for page_number, page in enumerate(pdf.pages, start=1):
            page_text = page.extract_text() or ""

            section_on_page = find_section(page_text)
            if section_on_page:
                current_section = section_on_page

            tables = page.extract_tables() or []

            for table in tables:
                if not table:
                    continue

                header_index, headers = find_day_header(table)

                if headers is not None:
                    previous_headers = headers
                    data_start = header_index + 1
                elif previous_headers is not None:
                    headers = previous_headers
                    data_start = 0
                else:
                    continue

                for row in table[data_start:]:
                    if not row:
                        continue

                    cells = [clean_text(cell) for cell in row]
                    if not any(cells):
                        continue

                    first_cell = cells[0] if cells else ""
                    row_day = find_day(first_cell)

                    if row_day:
                        current_day = row_day

                    # Ignore rows that do not have a known day context.
                    if not current_day:
                        continue

                    for column_index in range(1, min(len(cells), len(headers))):
                        cell_text = cells[column_index]
                        if not cell_text:
                            continue

                        records.append({
                            "source": "section",
                            "page": page_number,
                            "section": current_section,
                            "day": current_day,
                            "slot": headers[column_index],
                            "room": "",
                            "cell_text": cell_text,
                        })

    return records


def text_similarity(left, right):
    """Return a similarity score between 0 and 1."""
    a = normalize(left)
    b = normalize(right)

    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    return SequenceMatcher(None, a, b).ratio()


def make_key(record):
    return (
        (record.get("section") or "").upper(),
        (record.get("day") or "").lower(),
        normalize_slot(record.get("slot") or ""),
    )


def compare_records(master_records, section_records, similarity_threshold=0.30):
    """
    Match records by section/day/slot.
    A section cell may be formatted differently from the master cell, so text
    comparison is approximate and uses a deliberately review-friendly threshold.
    """
    master_by_key = defaultdict(list)
    section_by_key = defaultdict(list)

    for record in master_records:
        if record["section"] and record["day"] and record["slot"]:
            master_by_key[make_key(record)].append(record)

    for record in section_records:
        if record["section"] and record["day"] and record["slot"]:
            section_by_key[make_key(record)].append(record)

    all_keys = sorted(set(master_by_key) | set(section_by_key))
    results = []

    for key in all_keys:
        master_items = master_by_key.get(key, [])
        section_items = section_by_key.get(key, [])

        section_used = set()

        for master in master_items:
            best_index = None
            best_score = 0.0

            for index, section in enumerate(section_items):
                if index in section_used:
                    continue
                score = text_similarity(master["cell_text"], section["cell_text"])
                if score > best_score:
                    best_score = score
                    best_index = index

            if best_index is not None and best_score >= similarity_threshold:
                section_used.add(best_index)
                status = "MATCH"
                section_text = section_items[best_index]["cell_text"]
            elif section_items:
                status = "TEXT_REVIEW"
                section_text = " | ".join(item["cell_text"] for item in section_items)
            else:
                status = "MISSING_IN_SECTION_PDF"
                section_text = ""

            results.append({
                "section": key[0],
                "day": master["day"],
                "time_slot": master["slot"],
                "status": status,
                "master_room": master["room"],
                "master_cell": master["cell_text"],
                "section_cell": section_text,
                "similarity": round(best_score, 3),
                "master_page": master["page"],
            })

        for index, section in enumerate(section_items):
            if index not in section_used and not master_items:
                results.append({
                    "section": key[0],
                    "day": section["day"],
                    "time_slot": section["slot"],
                    "status": "MISSING_IN_MASTER_PDF",
                    "master_room": "",
                    "master_cell": "",
                    "section_cell": section["cell_text"],
                    "similarity": 0.0,
                    "master_page": "",
                })

    # Records without a section code cannot be reliably cross-checked.
    for record in master_records:
        if not record["section"]:
            results.append({
                "section": "",
                "day": record["day"],
                "time_slot": record["slot"],
                "status": "MASTER_SECTION_NOT_PARSED",
                "master_room": record["room"],
                "master_cell": record["cell_text"],
                "section_cell": "",
                "similarity": 0.0,
                "master_page": record["page"],
            })

    for record in section_records:
        if not record["section"]:
            results.append({
                "section": "",
                "day": record["day"],
                "time_slot": record["slot"],
                "status": "SECTION_NAME_NOT_PARSED",
                "master_room": "",
                "master_cell": "",
                "section_cell": record["cell_text"],
                "similarity": 0.0,
                "master_page": "",
            })

    return results


def save_report(results, output_path):
    fieldnames = [
        "section", "day", "time_slot", "status", "similarity",
        "master_room", "master_cell", "section_cell", "master_page",
    ]

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


def print_summary(master_records, section_records, results):
    counts = defaultdict(int)
    for result in results:
        counts[result["status"]] += 1

    print("\nVALIDATION SUMMARY")
    print("------------------")
    print(f"Master PDF occupied cells:  {len(master_records)}")
    print(f"Section PDF occupied cells:{len(section_records):>6}")
    print(f"Comparison rows:            {len(results)}")

    for status in sorted(counts):
        print(f"{status:28} {counts[status]}")

    print("\nNote: TEXT_REVIEW and missing statuses should be checked against the PDFs.")
    print("The validator does not automatically alter or delete extracted records.")


def main():
    parser = argparse.ArgumentParser(
        description="Validate master timetable extraction against section-wise PDF."
    )
    parser.add_argument("master_csv", help="CSV created by pdf_extractor.py")
    parser.add_argument("section_pdf", help="Section-wise timetable PDF")
    parser.add_argument(
        "output_csv",
        nargs="?",
        default="data/processed/validation_report.csv",
        help="Where to save the validation report",
    )
    args = parser.parse_args()

    if not Path(args.master_csv).is_file():
        raise FileNotFoundError(f"Master CSV not found: {args.master_csv}")
    if not Path(args.section_pdf).is_file():
        raise FileNotFoundError(f"Section-wise PDF not found: {args.section_pdf}")

    master_records = read_master_csv(args.master_csv)
    section_records = read_section_pdf(args.section_pdf)
    results = compare_records(master_records, section_records)

    save_report(results, args.output_csv)
    print_summary(master_records, section_records, results)
    print(f"\nValidation report saved to: {Path(args.output_csv).resolve()}")


if __name__ == "__main__":
    main()
