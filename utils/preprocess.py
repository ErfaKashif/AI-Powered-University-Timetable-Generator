"""Reads the original FAST-NUCES Fall 2024 timetable CSVs (data/raw) and writes
clean tables for the selected batches into data/extracted.

Only real information from the timetable is written here. Anything that is
not in the timetable (preferences, enrollment ...) is made in assumptions.py.
"""
import csv
import os
import re
from collections import Counter, OrderedDict, defaultdict

DAYS = ['MONDAY', 'TUESDAY', 'WEDNESDAY', 'THURSDAY', 'FRIDAY']
SELECTED_SEMESTERS = {5, 7}

# program codes used in the sheet -> the code we use
PROGRAM_CODES = {'BCS': 'BCS', 'BSE': 'BSE', 'BAI': 'BAI', 'BCY': 'BCY', 'BDS': 'BDS',
                 'BSEE': 'BEE', 'BSEL': 'BEE', 'BSBA': 'BBA', 'BSFT': 'BFT'}
# names used on the "Reserved Days" sheet
RESERVED_PROGRAMS = {'CS': 'BCS', 'SE': 'BSE', 'AI': 'BAI', 'CY': 'BCY', 'DS': 'BDS',
                     'BA': 'BBA', 'FT': 'BFT', 'EE': 'BEE'}
# in Fall 2024 batch 2024 was in 1st semester, 2023 in 3rd, ...
BATCH_TO_SEMESTER = {'2024': 1, '2023': 3, '2022': 5, '2021': 7}

SECTION_PATTERN = re.compile(
    r'\b(BCS|BSE|BAI|BCY|BDS|BSEE|BSEL|BSBA|BSFT)\s*[- ]?\s*(\d)\s*([A-Z]{0,2})\b'
    r'((?:\s*(?:&|,)\s*\d?\s*[A-Z]\b)*)')
ROOM_NAME_FIXES = {'Academic Block II Electroni Academic Block I Lab': 'Academic Block II Electronics Lab'}


def clean(text):
    return re.sub(r'\s+', ' ', text).strip()


def read_csv(path):
    with open(path, encoding='utf-8', errors='replace') as f:
        return list(csv.reader(f))


def write_csv(path, rows, fields):
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f'  wrote {os.path.basename(path)} ({len(rows)} rows)')


def load_aliases(path):
    if not os.path.exists(path):
        return {}
    with open(path, encoding='utf-8') as f:
        return {row['alias']: row['canonical'] for row in csv.DictReader(f)}


def split_room_label(label):
    """'E-1 Academic Block I (50)' -> ('E-1 Academic Block I', 50)"""
    match = re.search(r'\((\d+)\)\s*$', label.strip())
    capacity = int(match.group(1)) if match else ''
    name = re.sub(r'\((\d+)\)\s*$', '', label)
    name = clean(re.sub(r'Academic Block', ' Academic Block', name))
    return ROOM_NAME_FIXES.get(name, name), capacity


def read_day_sheet(path, day):
    """Returns the time slots of the day and every non-empty cell."""
    rows = read_csv(path)
    times = [clean(t) for t in rows[2][1:]]
    column_to_slot = {}
    slots = []
    slot_no = 0
    for i, time in enumerate(times):
        if not time:
            continue
        if time.startswith('1:00-1:40'):          # Friday prayer break column
            slots.append({'day': day, 'slot': 'BREAK', 'time': time})
            continue
        slot_no += 1
        column_to_slot[i + 1] = slot_no
        slots.append({'day': day, 'slot': slot_no, 'time': time})

    cells = []
    room_kind = 'classroom'
    for row in rows[3:]:
        if not row or not row[0].strip():
            continue
        heading = row[0].strip().upper()
        if heading in ('CLASSROOMS', 'LABS'):
            room_kind = 'lab' if heading == 'LABS' else 'classroom'
            continue
        room, capacity = split_room_label(row[0])
        for col, value in enumerate(row[1:], start=1):
            text = clean(value.replace('\n', ' | '))
            if text.strip(' |') and col in column_to_slot:
                cells.append({'day': day, 'slot': column_to_slot[col], 'room': room,
                              'capacity': capacity, 'kind': room_kind, 'text': text})
    return slots, cells


def parse_cell(cell, teacher_alias, course_alias):
    """'DB Lab BCS-5A | Syeda Mahnoor Javed' -> meeting dict, or None if it is not a class."""
    text = cell['text']
    match = SECTION_PATTERN.search(text)
    if not match:
        return None
    program = PROGRAM_CODES[match.group(1)]
    semester = int(match.group(2))
    letters = match.group(3) or 'A'
    letters = list(letters) if len(letters) == 2 else [letters[0]]   # BSEE-5AB = A and B
    letters += re.findall(r'[A-Z]', match.group(4) or '')            # "7A & 7B"

    is_lab = bool(re.search(r'lab\b', text, re.I)) and 'Lecture' not in text
    course = clean(re.sub(r'(?i)lab\b', '', text[:match.start()]).replace('|', ' ')).strip(' -')
    course = course_alias.get(course, course)

    rest = re.sub(r'^\s*\([A-Z,\s]+\)', '', text[match.end():]).replace('|', ' ')
    rest = re.sub(r'\bLecture\b', '', rest)
    teacher = clean(re.sub(r'\s*-\s*B9$|\s*C1 Lab 11.*$', '', clean(rest))).strip(' -')
    teacher = teacher_alias.get(teacher, teacher) or 'UNKNOWN'

    return {'day': cell['day'], 'slot': cell['slot'], 'duration': 3 if is_lab else 1,
            'room': cell['room'], 'program': program, 'semester': semester,
            'sections': '+'.join(sorted(set(letters))), 'course': course,
            'teacher': teacher, 'type': 'lab' if is_lab else 'lecture'}


def read_reserved_days(path):
    rows = read_csv(path)
    header = next(r for r in rows if 'Monday' in r)
    reserved = {}
    for row in rows:
        match = re.search(r'Batch (\d{4})\s*\((\w+)\)', ' '.join(row))
        if not match or match.group(1) not in BATCH_TO_SEMESTER:
            continue
        days = [header[i].upper() for i, value in enumerate(row) if 'Reserved' in value]
        reserved[(RESERVED_PROGRAMS[match.group(2)], BATCH_TO_SEMESTER[match.group(1)])] = days
    return reserved


def build_offerings(meetings):
    """Group the real meetings into course offerings (what has to be scheduled)."""
    groups = OrderedDict()
    for m in meetings:
        key = (m['program'], m['semester'], m['sections'], m['course'], m['type'], m['teacher'])
        group = groups.setdefault(key, {'count': 0, 'rooms': Counter()})
        group['count'] += 1
        group['rooms'][m['room']] += 1

    offerings = []
    for (program, semester, sections, course, kind, teacher), group in groups.items():
        offering_id = f'{program}-{semester}{sections}-{course}-{kind[:3].upper()}'.replace(' ', '')
        offerings.append({'offering_id': offering_id, 'program': program, 'semester': semester,
                          'sections': sections, 'course': course, 'type': kind, 'teacher': teacher,
                          'meetings_per_week': group['count'],
                          'slots_per_meeting': 3 if kind == 'lab' else 1,
                          'rooms_used_fall2024': ';'.join(group['rooms'])})

    # a course is core if every section of its program/semester takes it, otherwise elective
    all_letters = defaultdict(set)
    course_letters = defaultdict(set)
    for o in offerings:
        letters = set(o['sections'].split('+'))
        all_letters[(o['program'], o['semester'])] |= letters
        course_letters[(o['program'], o['semester'], o['course'])] |= letters
    for o in offerings:
        covers_all = course_letters[(o['program'], o['semester'], o['course'])] >= all_letters[(o['program'], o['semester'])]
        o['is_elective'] = 'no' if covers_all else 'yes'

    offerings.sort(key=lambda o: (o['program'], o['semester'], o['sections'], o['course'], o['type']))
    return offerings


def build_sections(offerings, reserved):
    load = OrderedDict()
    for o in offerings:
        for letter in o['sections'].split('+'):
            key = (o['program'], o['semester'], letter)
            load[key] = load.get(key, 0) + o['meetings_per_week'] * o['slots_per_meeting']
    rows = []
    for (program, semester, letter), slots in sorted(load.items()):
        rows.append({'section': f'{program}-{semester}{letter}', 'program': program, 'semester': semester,
                     'batch': 2024 - (semester - 1) // 2, 'weekly_slots': slots,
                     'reserved_days': ';'.join(reserved.get((program, semester), []))})
    return rows


def build_teachers(selected, others):
    info = defaultdict(lambda: {'selected': 0, 'other': 0, 'days': set(), 'programs': set()})
    for part, meetings in (('selected', selected), ('other', others)):
        for m in meetings:
            row = info[m['teacher']]
            row[part] += m['duration']
            row['days'].add(m['day'][:3])
            if part == 'selected':
                row['programs'].add(m['program'])
    rows = []
    for name, row in sorted(info.items()):
        if row['selected'] == 0:
            continue
        days = [d for d in ['MON', 'TUE', 'WED', 'THU', 'FRI'] if d in row['days']]
        rows.append({'teacher': name, 'programs_taught': ';'.join(sorted(row['programs'])),
                     'selected_batch_slots': row['selected'], 'other_batch_slots': row['other'],
                     'days_teaching_fall2024': ';'.join(days)})
    return rows


def run(project_dir):
    raw_dir = os.path.join(project_dir, 'data', 'raw')
    out_dir = os.path.join(project_dir, 'data', 'extracted')
    os.makedirs(out_dir, exist_ok=True)
    teacher_alias = load_aliases(os.path.join(project_dir, 'data', 'teacher_aliases.csv'))
    course_alias = load_aliases(os.path.join(project_dir, 'data', 'course_aliases.csv'))

    timeslots, cells = [], []
    for day in DAYS:
        path = os.path.join(raw_dir, f'fall2024_{day.lower()}.csv')
        if not os.path.exists(path):
            raise FileNotFoundError(f'Missing timetable sheet: {path}')
        day_slots, day_cells = read_day_sheet(path, day)
        timeslots += day_slots
        cells += day_cells

    rooms, meetings, reservations = {}, [], []
    for cell in cells:
        rooms.setdefault(cell['room'], (cell['capacity'], cell['kind']))
        meeting = parse_cell(cell, teacher_alias, course_alias)
        if meeting:
            meetings.append(meeting)
        elif 'JUMMA' not in cell['text'].upper():
            reservations.append({'day': cell['day'], 'slot': cell['slot'], 'room': cell['room'],
                                 'reason': cell['text']})

    selected = [m for m in meetings if m['semester'] in SELECTED_SEMESTERS]
    others = [m for m in meetings if m['semester'] not in SELECTED_SEMESTERS]
    reserved = read_reserved_days(os.path.join(raw_dir, 'fall2024_reserved_days.csv'))
    offerings = build_offerings(selected)

    meeting_fields = ['day', 'slot', 'duration', 'room', 'program', 'semester', 'sections',
                      'course', 'teacher', 'type']
    write_csv(os.path.join(out_dir, 'fall2024_selected_meetings.csv'), selected, meeting_fields)
    write_csv(os.path.join(out_dir, 'fall2024_other_batches_fixed.csv'), others, meeting_fields)
    write_csv(os.path.join(out_dir, 'room_reservations.csv'), reservations, ['day', 'slot', 'room', 'reason'])
    write_csv(os.path.join(out_dir, 'timeslots.csv'), timeslots, ['day', 'slot', 'time'])
    room_rows = [{'room': name, 'capacity': cap, 'kind': kind,
                  'capacity_source': 'timetable' if cap != '' else 'missing'}
                 for name, (cap, kind) in rooms.items()]
    write_csv(os.path.join(out_dir, 'rooms.csv'), room_rows, ['room', 'capacity', 'kind', 'capacity_source'])
    write_csv(os.path.join(out_dir, 'course_offerings.csv'), offerings, list(offerings[0].keys()))
    sections = build_sections(offerings, reserved)
    write_csv(os.path.join(out_dir, 'sections.csv'), sections, list(sections[0].keys()))
    teachers = build_teachers(selected, others)
    write_csv(os.path.join(out_dir, 'teachers.csv'), teachers, list(teachers[0].keys()))
    reserved_rows = [{'program': p, 'semester': s, 'batch': 2024 - (s - 1) // 2, 'reserved_days': ';'.join(d)}
                     for (p, s), d in sorted(reserved.items())]
    write_csv(os.path.join(out_dir, 'batch_reserved_days.csv'), reserved_rows, list(reserved_rows[0].keys()))
