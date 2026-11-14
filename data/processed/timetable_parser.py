import csv
import re
import sys
from pathlib import Path

PROCESSED_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PROCESSED_DIR.parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.models.classmeeting_model import ClassMeeting
from src.models.course_model import Course
from src.models.room_model import Room
from src.models.teacher_model import Teacher

SLOT_ORDER = {
    "8:00-8:50": 0,
    "8:55-9:45": 1,
    "9:50:-10:40": 2,
    "10:45-11:35": 3,
    "11:40-12:30": 4,
    "12:35-1:25": 5,
    "1:30-2:20": 6,
    "2:25-3:15": 7,
    "3:20-4:10": 8,
}

# Strict 5-part pattern (requires trailing student count so course names never shift into teacher)
STRICT_5PART_RE = re.compile(
    r"^([A-Z]{2,4}\d{3,4})\s*,\s*([A-Z]{2,5}-\d{1,2}[A-Z0-9]*)\s*,\s*"
    r"([^,]+?)\s*,\s*([^,]+?)\s*,\s*(\d+)\s*st$"
)

# Standard 4-or-5-part pattern (student count optional)
SINGLE_ENTRY_RE = re.compile(
    r"^([A-Z]{2,4}\d{3,4})\s*,\s*([A-Z]{2,5}-\d{1,2}[A-Z0-9]*)\s*,\s*"
    r"([^,]+?)\s*,\s*([^,]+?)(?:\s*,\s*(\d+)\s*(?:st)?)?$"
)

MULTI_ENTRY_RE = re.compile(
    r"([A-Z]{2,4}\d{3,4})\s*,\s*([A-Z]{2,5}-\d{1,2}[A-Z0-9]*)\s*,\s*"
    r"([^,]+?)\s*,\s*([^,]+?)\s*,\s*(\d+)\s*st"
)

COURSE_KEYWORD_RE = re.compile(
    r"\b(lab|algebra|calculus|programming|structures|networks|security|"
    r"engineering|accounting|economics|psychology|english|studies|ethics|"
    r"quran|mgmt|management|writing|architecture|intelligence|systems|"
    r"cryptocurrency|blockchain|devops)\b",
    re.IGNORECASE,
)


def infer_meeting_type(course_id, course_name, room_id):
    if (
        "lab" in course_name.lower()
        or "lab" in room_id.lower()
        or (len(course_id) >= 2 and course_id[1] == "L")
    ):
        return "lab"
    return "lecture"


def make_teacher_id(name, existing_ids):
    slug = re.sub(r"[^A-Z0-9]+", "_", name.upper()).strip("_") or "UNASSIGNED"
    base_id = f"T_{slug}"
    teacher_id = base_id
    counter = 2
    while teacher_id in existing_ids:
        teacher_id = f"{base_id}_{counter}"
        counter += 1
    return teacher_id


def is_clean_person_name(name, known_courses):
    """Validate that a string is a real person's name and not a course, section, or PDF artifact."""
    if not name:
        return False
    name = re.sub(r"\s+", " ", name).strip()
    if name.lower() in ("no teacher assigned", "st", "tba", "n/a"):
        return False
    # Allow only letters, spaces, dots, hyphens, and apostrophes (no digits or slashes)
    if not re.match(r"^[A-Za-z.\s\-']+$", name):
        return False
    # Reject section codes like BCS-5A, BAI-3A
    if re.match(r"^[A-Z]{2,5}-\d+", name):
        return False
    # Reject known course titles or academic subject keywords
    if name.lower() in known_courses or COURSE_KEYWORD_RE.search(name):
        return False
    # Reject interleaved PDF bleed-through casing (e.g., 'SFuhnachtbioanza', 'MathemaStichsa')
    for word in name.split():
        clean_w = re.sub(r"[^A-Za-z]", "", word)
        if not clean_w:
            continue
        if re.match(r"^[A-Z]{2,}[a-z]", clean_w):
            return False
        if re.search(r"[a-z][A-Z]", clean_w):
            return False
        if len(clean_w) == 1 and clean_w.islower():
            return False
    return 2 <= len(name) <= 45


def build_reference_catalogs(rows):
    """Pass 1: Build clean lookup maps strictly from uncorrupted 5-part rows."""
    course_catalog = {}   # course_id -> course_name
    section_catalog = {}  # (course_id, section) -> (course_name, teacher_name, students)
    known_courses = set()

    for row in rows:
        text = (row.get("cell_text") or "").strip()
        m = STRICT_5PART_RE.match(text)
        if not m:
            continue

        cid, sec, cname, tname, stud = m.groups()
        cname, tname = cname.strip(), tname.strip()
        stud_int = int(stud)

        course_catalog[cid] = cname
        known_courses.add(cname.lower())
        if (cid, sec) not in section_catalog:
            section_catalog[(cid, sec)] = (cname, tname, stud_int)
        else:
            prev_cname, prev_tname, prev_stud = section_catalog[(cid, sec)]
            section_catalog[(cid, sec)] = (
                prev_cname or cname,
                tname if prev_tname.lower() == "no teacher assigned" else prev_tname,
                prev_stud if prev_stud is not None else stud_int,
            )

    return course_catalog, section_catalog, known_courses


def extract_cell_records(text, course_catalog, section_catalog, known_courses):
    """Pass 2: Extract (course_id, section, course_name, teacher_name, students) tuples."""
    text = (text or "").strip().rstrip(",").strip()
    if not text or text.lower() == "st":
        return []

    # 1. Standard single entry
    m = SINGLE_ENTRY_RE.match(text)
    if m:
        cid, sec, cname, tname, stud = m.groups()
        cname, tname = cname.strip(), tname.strip()
        # If teacher is invalid/missing (e.g. truncated row), look up from section_catalog
        if not is_clean_person_name(tname, known_courses):
            if (cid, sec) in section_catalog:
                _, tname, cat_stud = section_catalog[(cid, sec)]
                if stud is None:
                    stud = cat_stud
            else:
                tname = ""
        return [(cid, sec, cname, tname, int(stud) if stud is not None else None)]

    # 2. Multiple clean entries inside one cell (e.g. shared Lab rooms)
    multi = list(MULTI_ENTRY_RE.finditer(text))
    if len(multi) >= 2:
        return [
            (mm.group(1), mm.group(2), mm.group(3).strip(), mm.group(4).strip(), int(mm.group(5)))
            for mm in multi
        ]

    # 3. Corrupted PDF bleed-through cell: recover course_id and section
    cids = re.findall(r"[A-Z]{2,4}\d{3,4}", text)
    if not cids:
        upper_prefix = re.sub(r"[^A-Z0-9]", "", text)[:25]
        for known_cid in course_catalog:
            it = iter(upper_prefix)
            if all(ch in it for ch in known_cid):
                cids.append(known_cid)
                break

    secs = re.findall(r"[A-Z]{2,5}-\d{1,2}[A-Z0-9]*", text)
    if not secs:
        sec_clean = re.sub(r"[^A-Z0-9\-]", "", text)
        secs = re.findall(r"[A-Z]{2,5}-\d{1,2}[A-Z0-9]*", sec_clean)

    results = []
    for i, cid in enumerate(cids):
        sec = secs[i] if i < len(secs) else (secs[0] if secs else None)
        if not sec:
            continue

        if (cid, sec) in section_catalog:
            cname, tname, stud = section_catalog[(cid, sec)]
            stud_m = re.search(r"(\d+)\s*st\s*$", text)
            if stud_m:
                stud = int(stud_m.group(1))
            results.append((cid, sec, cname, tname, stud))
        else:
            parts = [p.strip() for p in text.split(",")]
            cname = course_catalog.get(cid, parts[2] if len(parts) > 2 else "")
            raw_tname = parts[3] if len(parts) > 3 else ""
            tname = raw_tname if is_clean_person_name(raw_tname, known_courses) else ""
            stud_m = re.search(r"(\d+)\s*(?:st)?\s*$", text)
            stud = int(stud_m.group(1)) if stud_m else None
            results.append((cid, sec, cname, tname, stud))

    return results


def parse_timetable_csv(csv_path):
    with Path(csv_path).open("r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    course_catalog, section_catalog, known_courses = build_reference_catalogs(rows)

    teachers_by_name = {}   # normalized_name -> Teacher
    courses_by_id = {}      # course_id -> Course
    rooms_by_id = {}        # room_id -> Room
    meetings = []           # list[ClassMeeting]
    unparsed_rows = []

    rows.sort(
        key=lambda r: (
            r.get("day", ""),
            r.get("room", ""),
            SLOT_ORDER.get(r.get("time_slot", ""), 99),
        )
    )

    for row in rows:
        day = (row.get("day") or "").strip()
        room_id = (row.get("room") or "").strip()
        slot = (row.get("time_slot") or "").strip()
        cell_text = row.get("cell_text") or ""

        extracted = extract_cell_records(
            cell_text, course_catalog, section_catalog, known_courses
        )
        if not extracted:
            unparsed_rows.append(row)
            continue

        for cid, sec, cname, tname, students in extracted:
            m_type = infer_meeting_type(cid, cname, room_id)

            # 1. Maintain Course lookup
            if cid not in courses_by_id:
                courses_by_id[cid] = Course(
                    course_id=cid,
                    name=cname,
                    credit_hours=1 if m_type == "lab" else 3,
                    course_type=m_type,
                )
            course_obj = courses_by_id[cid]

            # 2. Maintain Room lookup
            if room_id not in rooms_by_id:
                rooms_by_id[room_id] = Room(
                    room_id=room_id,
                    room_type="lab" if "lab" in room_id.lower() else "lecture",
                )
            room_obj = rooms_by_id[room_id]

            # 3. Maintain Teacher table/lookup (strictly validated)
            teacher_obj = None
            if is_clean_person_name(tname, known_courses):
                norm_tname = re.sub(r"\s+", " ", tname).strip()
                t_key = norm_tname.lower()
                if t_key not in teachers_by_name:
                    existing_ids = {t.teacher_id for t in teachers_by_name.values()}
                    tid = make_teacher_id(norm_tname, existing_ids)
                    teachers_by_name[t_key] = Teacher(teacher_id=tid, name=norm_tname)
                teacher_obj = teachers_by_name[t_key]

            # 4. Merge consecutive slots for the same meeting
            if meetings:
                prev = meetings[-1]
                prev_idx = SLOT_ORDER.get(prev.slot, -99)
                curr_idx = SLOT_ORDER.get(slot, -99)
                if (
                    prev.day == day
                    and getattr(prev.room, "room_id", prev.room) == room_id
                    and getattr(prev.course, "course_id", prev.course) == cid
                    and prev.section == sec
                    and curr_idx == prev_idx + 1
                ):
                    prev.duration += 1
                    continue

            # 5. Create new ClassMeeting instance
            meeting_id = f"M{len(meetings) + 1:04d}"
            meetings.append(
                ClassMeeting(
                    meeting_id=meeting_id,
                    course=course_obj,
                    section=sec,
                    teacher=teacher_obj,
                    duration=3 if m_type == "lab" else 1,
                    meeting_type=m_type,
                    students=students,
                    day=day,
                    slot=slot,
                    room=room_obj,
                )
            )

    teachers = sorted(teachers_by_name.values(), key=lambda t: t.name)
    return teachers, courses_by_id, rooms_by_id, meetings, unparsed_rows


def export_tables(teachers, meetings, out_dir=PROCESSED_DIR):
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)

    # Export Teacher table
    teacher_csv = out_path / "teachers.csv"
    with teacher_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=["teacher_id", "name"])
        writer.writeheader()
        for t in teachers:
            writer.writerow({"teacher_id": t.teacher_id, "name": t.name})

    # Export ClassMeeting table
    meetings_csv = out_path / "class_meetings.csv"
    fieldnames = [
        "meeting_id",
        "course_id",
        "course_name",
        "section",
        "teacher_id",
        "teacher_name",
        "duration",
        "meeting_type",
        "students",
        "day",
        "slot",
        "room_id",
    ]
    with meetings_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for m in meetings:
            writer.writerow({
                "meeting_id": m.meeting_id,
                "course_id": m.course.course_id if m.course else "",
                "course_name": m.course.name if m.course else "",
                "section": m.section,
                "teacher_id": m.teacher.teacher_id if m.teacher else "",
                "teacher_name": m.teacher.name if m.teacher else "No Teacher Assigned",
                "duration": m.duration,
                "meeting_type": m.meeting_type,
                "students": m.students if m.students is not None else "",
                "day": m.day or "",
                "slot": m.slot or "",
                "room_id": m.room.room_id if m.room else "",
            })

    print(f"Saved {len(teachers)} teachers -> {teacher_csv.resolve()}")
    print(f"Saved {len(meetings)} class meetings -> {meetings_csv.resolve()}")


if __name__ == "__main__":
    input_csv = PROCESSED_DIR / "timetable_cells_v0.csv"
    teachers, courses, rooms, meetings, unparsed = parse_timetable_csv(input_csv)
    print(f"Parsed {len(teachers)} unique teachers, {len(courses)} courses, {len(rooms)} rooms, {len(meetings)} meetings.")
    print(f"Unparsed overflow fragments skipped: {len(unparsed)}")
    export_tables(teachers, meetings, out_dir=PROCESSED_DIR)