"""Creates the inputs that are NOT in the university timetable (data/created).

Every value is based on the real Fall 2024 timetable so that a valid
timetable is known to exist. All files can be edited by hand or from the app.
Running this again OVERWRITES data/created, so it is only run on request.
"""
import csv
import os
import random
from collections import defaultdict

DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI']
EE_LAB_WORDS = ('Electronics', 'PHYSICS', 'MPI', 'Project')


def read(path):
    with open(path, encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write(path, rows, fields):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    print(f'  wrote {os.path.basename(path)} ({len(rows)} rows)')


def make_faculty_constraints(selected, others, rng):
    sel_days, sel_slots, other_days, all_days, kinds = (defaultdict(set) for _ in range(5))
    for m in selected:
        day = m['day'][:3]
        sel_days[m['teacher']].add(day)
        all_days[m['teacher']].add(day)
        kinds[m['teacher']].add(m['type'])
        for k in range(int(m['duration'])):
            sel_slots[m['teacher']].add(int(m['slot']) + k)
    for m in others:
        other_days[m['teacher']].add(m['day'][:3])
        all_days[m['teacher']].add(m['day'][:3])

    teachers = sorted(sel_days)
    # visiting = only teaches these batches, only lectures, at most two days a week
    visiting = [t for t in teachers if len(all_days[t]) <= 2 and kinds[t] == {'lecture'} and not other_days[t]]
    lecturers = [t for t in teachers if t not in visiting and 'lecture' in kinds[t]]
    fixed = set(rng.sample(lecturers, 8))

    rows = []
    for t in teachers:
        order = ['FRI', 'MON', 'THU', 'TUE', 'WED']
        free_days = [d for d in order if d not in all_days[t]] or [d for d in order if d not in other_days[t]]
        day_off = free_days[0] if free_days else ''
        low, high = min(sel_slots[t]), max(sel_slots[t])
        average = sum(sel_slots[t]) / len(sel_slots[t])
        preferred_slots = '1-4' if average <= 3.5 else ('5-8' if average >= 5 else '')
        row = {'teacher': t, 'faculty_type': 'permanent', 'available_days': '', 'available_slots': '',
               'fixed_days': '', 'day_off': day_off,
               'preferred_days': ';'.join(d for d in DAYS if d in sel_days[t] and d != day_off),
               'preferred_slots': preferred_slots, 'note': ''}
        if t in visiting:
            row.update(faculty_type='visiting', day_off='',
                       available_days=';'.join(d for d in DAYS if d in sel_days[t]),
                       available_slots=f'{max(1, low - 1)}-{min(8, high + 1)}',
                       note='assumed visiting: only teaches these batches, lectures only, <=2 days')
        if t in fixed:
            row['fixed_days'] = ';'.join(d for d in DAYS if d in sel_days[t] and d != day_off)
            row['note'] = 'assumed fixed teaching days (= days taught in Fall 2024)'
        if len(all_days[t]) == 5:
            row['note'] = 'taught all 5 days in Fall 2024; day off picked where no fixed 1st/3rd sem class'
        rows.append(row)
    return rows


def make_room_requirements(offerings, rooms):
    ee_labs = [r['room'] for r in rooms if any(w in r['room'] for w in EE_LAB_WORDS)]
    rows = []
    for o in offerings:
        used = o['rooms_used_fall2024'].split(';')
        if o['program'] == 'BEE' and o['type'] == 'lab' and all(r in ee_labs for r in used):
            rows.append({'offering_id': o['offering_id'], 'required_rooms': ';'.join(ee_labs),
                         'source': 'real: this EE lab only used EE labs in Fall 2024',
                         'reason': 'Electrical equipment'})
        elif o['program'] == 'BBA' and o['type'] == 'lecture':
            rows.append({'offering_id': o['offering_id'],
                         'required_rooms': 'B-9 Academic Block II;B-10 Academic Block II;B-11 Academic Block II',
                         'source': 'assumed (BBA-5A lectures were in block B in Fall 2024)',
                         'reason': 'FSM department rooms'})
        elif o['course'] == 'CV' and o['type'] == 'lab':
            rows.append({'offering_id': o['offering_id'],
                         'required_rooms': 'Academic Block II AI/ML LAB-9;Academic Block II LAB-11',
                         'source': 'assumed HoD request (the two labs CV used in Fall 2024)',
                         'reason': 'GPU machines for computer vision'})
        elif o['course'] == 'FSPM' and '+' in o['sections']:
            rows.append({'offering_id': o['offering_id'], 'required_rooms': 'S2 Academic Block I',
                         'source': 'real: combined BSE-7A+B always used S2', 'reason': 'Combined section'})
    return rows


def make_enrollment(selected, rooms, sections, rng):
    capacity = {r['room']: int(r['capacity'] or 50) for r in rooms}
    upper = defaultdict(lambda: 999)
    for m in selected:
        letters = m['sections'].split('+')
        for letter in letters:
            name = f"{m['program']}-{m['semester']}{letter}"
            upper[name] = min(upper[name], capacity[m['room']] // len(letters))
    rows = []
    for s in sections:
        bound = upper[s['section']]
        rows.append({'section': s['section'], 'estimated_enrollment': max(10, int(bound * rng.uniform(0.82, 1.0))),
                     'upper_bound_from_rooms': bound,
                     'source': 'estimated: smallest room the section fitted in during Fall 2024'})
    return rows


def make_history(offerings, enrollment, rng):
    """SYNTHETIC enrollment history. No real history was provided."""
    terms = ['Fall 2021', 'Spring 2022', 'Fall 2022', 'Spring 2023', 'Fall 2023', 'Spring 2024', 'Fall 2024']
    growth = {'BCS': 1.06, 'BAI': 1.15, 'BCY': 1.10, 'BSE': 1.03, 'BEE': 0.97, 'BBA': 1.02}
    size = {e['section']: int(e['estimated_enrollment']) for e in enrollment}
    letters = defaultdict(set)
    for o in offerings:
        letters[(o['program'], o['semester'], o['course'])] |= set(o['sections'].split('+'))
    rows, done = [], set()
    for o in offerings:
        key = (o['program'], o['semester'], o['course'])
        if o['type'] != 'lecture' or key in done:
            continue
        done.add(key)
        now = sum(size[f"{o['program']}-{o['semester']}{x}"] for x in letters[key])
        rate = growth.get(o['program'], 1.0) ** 0.5
        for i, term in enumerate(terms):
            back = len(terms) - 1 - i
            value = now / (rate ** back) * rng.gauss(1.0, 0.06)
            rows.append({'term': term, 'term_index': i, 'program': o['program'], 'semester': o['semester'],
                         'course': o['course'], 'elective': o['is_elective'], 'credit_hours': 3,
                         'sections_offered': max(1, round(value / 48)),
                         'enrollment': round(value) if back else now,
                         'source': 'SYNTHETIC' if back else 'estimated (Fall 2024)'})
    return rows


def run(project_dir, seed=42):
    rng = random.Random(seed)
    ex = os.path.join(project_dir, 'data', 'extracted')
    out = os.path.join(project_dir, 'data', 'created')
    selected = read(os.path.join(ex, 'fall2024_selected_meetings.csv'))
    others = read(os.path.join(ex, 'fall2024_other_batches_fixed.csv'))
    offerings = read(os.path.join(ex, 'course_offerings.csv'))
    rooms = read(os.path.join(ex, 'rooms.csv'))
    sections = read(os.path.join(ex, 'sections.csv'))

    faculty = make_faculty_constraints(selected, others, rng)
    write(os.path.join(out, 'faculty_constraints.csv'), faculty, list(faculty[0].keys()))

    missing = [{'room': r['room'], 'capacity': 50, 'note': 'capacity not printed in the timetable; assumed 50'}
               for r in rooms if r['capacity'] == '']
    write(os.path.join(out, 'room_capacity_assumptions.csv'), missing, ['room', 'capacity', 'note'])

    requirements = make_room_requirements(offerings, rooms)
    write(os.path.join(out, 'special_room_requirements.csv'), requirements,
          ['offering_id', 'required_rooms', 'source', 'reason'])

    days_off = [{'section': s['section'], 'days_off': s['reserved_days'],
                 'source': 'real: Fall 2024 reserved days sheet'} for s in sections]
    write(os.path.join(out, 'section_days_off.csv'), days_off, ['section', 'days_off', 'source'])

    enrollment = make_enrollment(selected, rooms, sections, rng)
    write(os.path.join(out, 'section_enrollment.csv'), enrollment, list(enrollment[0].keys()))

    history = make_history(offerings, enrollment, rng)
    write(os.path.join(out, 'enrollment_history_synthetic.csv'), history, list(history[0].keys()))
