"""Loads the CSV files in data/ into a Problem object and checks the input."""
import csv
import os
from collections import defaultdict

from models.entities import DAYS, Offering, Problem, Room, Section, Teacher, TimeGrid, parse_minutes

DAY_SHORT = {'MONDAY': 'MON', 'TUESDAY': 'TUE', 'WEDNESDAY': 'WED', 'THURSDAY': 'THU', 'FRIDAY': 'FRI'}

REQUIRED_FILES = {
    'extracted': ['course_offerings.csv', 'rooms.csv', 'sections.csv', 'timeslots.csv',
                  'fall2024_other_batches_fixed.csv', 'room_reservations.csv'],
    'created': ['faculty_constraints.csv', 'section_enrollment.csv', 'special_room_requirements.csv',
                'room_capacity_assumptions.csv', 'section_days_off.csv'],
}


class DataError(Exception):
    pass


def read_rows(path):
    if not os.path.exists(path):
        raise DataError(f'Missing input file: {path}')
    with open(path, encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    return rows


def split_list(text):
    return [x.strip().upper()[:3] for x in (text or '').replace(',', ';').split(';') if x.strip()]


def parse_slot_range(text):
    """'1-4' -> {1, 2, 3, 4}; '2;5;6' -> {2, 5, 6}; '' -> empty set"""
    text = (text or '').strip()
    if not text:
        return set()
    slots = set()
    for part in text.replace(',', ';').split(';'):
        if '-' in part:
            a, b = part.split('-')
            slots |= set(range(int(a), int(b) + 1))
        elif part.strip():
            slots.add(int(part))
    return slots


def load_grid(data_dir):
    day_slots = {d: {} for d in DAYS}
    for row in read_rows(os.path.join(data_dir, 'extracted', 'timeslots.csv')):
        if row['slot'] == 'BREAK':
            continue
        day_slots[DAY_SHORT[row['day']]][int(row['slot'])] = parse_minutes(row['time'])
    return TimeGrid(day_slots)


def load_rooms(data_dir):
    assumed = {r['room']: int(r['capacity'])
               for r in read_rows(os.path.join(data_dir, 'created', 'room_capacity_assumptions.csv'))}
    rooms = []
    for row in read_rows(os.path.join(data_dir, 'extracted', 'rooms.csv')):
        capacity = row['capacity'] or assumed.get(row['room'])
        if capacity in (None, ''):
            raise DataError(f"Room {row['room']} has no capacity. Add it to room_capacity_assumptions.csv")
        rooms.append(Room(row['room'], int(capacity), row['kind']))
    return rooms


def load_teachers(data_dir):
    teachers = {}
    for row in read_rows(os.path.join(data_dir, 'created', 'faculty_constraints.csv')):
        teachers[row['teacher']] = Teacher(
            row['teacher'], row.get('faculty_type') or 'permanent',
            available_days=split_list(row.get('available_days')),
            available_slots=parse_slot_range(row.get('available_slots')),
            fixed_days=split_list(row.get('fixed_days')),
            day_off=(split_list(row.get('day_off')) or [''])[0],
            preferred_days=split_list(row.get('preferred_days')),
            preferred_slots=parse_slot_range(row.get('preferred_slots')))
    return teachers


def load_sections(data_dir):
    enrollment = {r['section']: int(r['estimated_enrollment'])
                  for r in read_rows(os.path.join(data_dir, 'created', 'section_enrollment.csv'))}
    days_off = {r['section']: split_list(r['days_off'])
                for r in read_rows(os.path.join(data_dir, 'created', 'section_days_off.csv'))}
    sections = {}
    for row in read_rows(os.path.join(data_dir, 'extracted', 'sections.csv')):
        name = row['section']
        sections[name] = Section(name, row['program'], int(row['semester']),
                                 days_off.get(name, split_list(row['reserved_days'])),
                                 enrollment.get(name, 45))
    return sections


def load_fixed_bookings(data_dir, keep_semesters):
    """Classes that are not being scheduled (other batches) block their teacher and room."""
    teacher_blocked, room_blocked = set(), set()
    files = ['fall2024_other_batches_fixed.csv', 'fall2024_selected_meetings.csv']
    for name in files:
        path = os.path.join(data_dir, 'extracted', name)
        for row in read_rows(path):
            if name == 'fall2024_selected_meetings.csv' and int(row['semester']) in keep_semesters:
                continue
            day = DAY_SHORT[row['day']]
            for s in range(int(row['slot']), int(row['slot']) + int(row['duration'])):
                teacher_blocked.add((row['teacher'], day, s))
                room_blocked.add((row['room'], day, s))
    for row in read_rows(os.path.join(data_dir, 'extracted', 'room_reservations.csv')):
        room_blocked.add((row['room'], DAY_SHORT[row['day']], int(row['slot'])))
    return teacher_blocked, room_blocked


def load_problem(data_dir='data', semesters=(5, 7), programs=None):
    """Builds the scheduling problem for the given semesters (and optionally programs)."""
    for folder, files in REQUIRED_FILES.items():
        for f in files:
            if not os.path.exists(os.path.join(data_dir, folder, f)):
                raise DataError(f'Missing input file: {os.path.join(data_dir, folder, f)}')
    semesters = set(int(s) for s in semesters)
    grid = load_grid(data_dir)
    rooms = load_rooms(data_dir)
    teachers = load_teachers(data_dir)
    sections = load_sections(data_dir)
    required = defaultdict(set)
    for row in read_rows(os.path.join(data_dir, 'created', 'special_room_requirements.csv')):
        required[row['offering_id']] |= {r.strip() for r in row['required_rooms'].split(';') if r.strip()}

    offerings, used_sections = [], {}
    for i, row in enumerate(read_rows(os.path.join(data_dir, 'extracted', 'course_offerings.csv')), start=2):
        try:
            semester = int(row['semester'])
            meetings = int(row['meetings_per_week'])
            length = int(row['slots_per_meeting'])
        except (KeyError, ValueError):
            raise DataError(f'course_offerings.csv line {i}: bad number in row {row}')
        if semester not in semesters or (programs and row['program'] not in programs):
            continue
        names = [f"{row['program']}-{semester}{letter}" for letter in row['sections'].split('+')]
        missing = [n for n in names if n not in sections]
        if missing:
            raise DataError(f'course_offerings.csv line {i}: unknown section(s) {missing}')
        teacher = teachers.get(row['teacher'])
        if teacher is None:
            teacher = Teacher(row['teacher'])       # no constraints entered for this teacher yet
            teachers[row['teacher']] = teacher
        offering = Offering(row['offering_id'], row['course'], row['type'], teacher,
                            [sections[n] for n in names], meetings, length,
                            row.get('is_elective') == 'yes', required.get(row['offering_id']))
        offerings.append(offering)
        for n in names:
            used_sections[n] = sections[n]
    if not offerings:
        raise DataError('No course offerings found for the selected semesters/programs.')

    teacher_blocked, room_blocked = load_fixed_bookings(data_dir, semesters)
    used_teachers = sorted({o.teacher.name for o in offerings})
    name = 'sem ' + '+'.join(str(s) for s in sorted(semesters))
    if programs:
        name += ' ' + ','.join(programs)
    return Problem(rooms, [teachers[t] for t in used_teachers], list(used_sections.values()), offerings,
                   grid, teacher_blocked, room_blocked, name=name)


def check_input(problem):
    """Finds input problems that make a valid timetable impossible, with the reason."""
    issues = []
    for t in problem.teachers:
        if t.day_off and t.day_off in t.fixed_days:
            issues.append(f'{t.name}: day off {t.day_off} is also one of the fixed days')
        if t.is_visiting() and not t.available_days:
            issues.append(f'{t.name}: visiting faculty without available days')
    teacher_load = defaultdict(int)
    for o in problem.offerings:
        teacher_load[o.teacher.name] += o.meetings_per_week * o.length
        first = f'{o.id}#1'
        if not problem.rooms_ok[first]:
            issues.append(f'{o.id}: no room is suitable (needs {o.kind}, {o.enrollment} seats'
                          + (f', required rooms {sorted(o.required_rooms)}' if o.required_rooms else '') + ')')
        if not problem.times_ok[first]:
            issues.append(f'{o.id}: no allowed time. ' + explain_times(problem, o))
        elif len({d for d, _ in problem.times_ok[first]}) * o.max_per_day < o.meetings_per_week:
            issues.append(f'{o.id}: needs {o.meetings_per_week} meetings but only '
                          f'{len({d for d, _ in problem.times_ok[first]})} days are allowed')
    for t in problem.teachers:
        free = sum(1 for d in t.allowed_days() for s in problem.grid.slots(d)
                   if t.can_teach_slot(s) and (t.name, d, s) not in problem.teacher_blocked)
        if teacher_load[t.name] > free:
            issues.append(f'{t.name}: needs {teacher_load[t.name]} slots but is only free for {free}')
    return issues


def explain_times(problem, offering):
    t = offering.teacher
    reasons = [f'teacher allowed days = {sorted(t.allowed_days())}']
    for s in offering.sections:
        if s.days_off:
            reasons.append(f'{s.name} days off = {sorted(s.days_off)}')
    if t.is_visiting():
        reasons.append(f'visiting slots = {sorted(t.available_slots)}')
    return '; '.join(reasons)


def load_real_timetable(problem, data_dir='data'):
    """The actual Fall 2024 placement of the meetings in the problem (for comparison)."""
    from models.entities import Timetable
    rows = read_rows(os.path.join(data_dir, 'extracted', 'fall2024_selected_meetings.csv'))
    by_offering = defaultdict(list)
    for row in rows:
        oid = f"{row['program']}-{row['semester']}{row['sections']}-{row['course']}-{row['type'][:3].upper()}"
        by_offering[oid.replace(' ', '')].append((DAY_SHORT[row['day']], int(row['slot']), row['room']))
    timetable = Timetable(problem)
    raw = {}
    for o in problem.offerings:
        for i, value in enumerate(by_offering.get(o.id, [])[:o.meetings_per_week]):
            raw[f'{o.id}#{i + 1}'] = value
    return raw
