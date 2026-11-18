"""Exports a timetable to CSV and Excel (master list + section, faculty and room grids)."""
import os
import re

import pandas as pd

from models.entities import DAYS
from utils.constraints import validation_rows


def master_rows(problem, assignment):
    rows = []
    order = {d: i for i, d in enumerate(DAYS)}
    for mid, (day, start, room) in assignment.items():
        m = problem.meeting_by_id[mid]
        o = m.offering
        end = start + m.length - 1
        time = problem.grid.time_label(day, start).split('-')[0] + '-' + problem.grid.time_label(day, end).split('-')[1]
        rows.append({'day': day, 'start_slot': start, 'end_slot': end, 'time': time,
                     'course': o.course, 'type': o.kind, 'sections': o.section_names,
                     'elective': 'yes' if o.is_elective else 'no', 'teacher': o.teacher.name,
                     'room': room, 'room_capacity': problem.room_by_name[room].capacity,
                     'enrollment': o.enrollment, 'meeting_id': mid})
    rows.sort(key=lambda r: (order[r['day']], r['start_slot'], r['sections']))
    return rows


def short_room(name):
    """'E-6 Academic Block I' -> 'E-6', 'Academic Block I LAB-3' -> 'LAB-3'"""
    short = re.sub(r'\s*Academic Block (I{1,3})\s*', ' ', name).strip()
    return short or name


def cell_text(problem, mid, room, show):
    o = problem.meeting_by_id[mid].offering
    parts = [o.course + (' LAB' if o.kind == 'lab' else '')]
    if 'section' in show:
        parts.append(o.section_names)
    if 'teacher' in show:
        parts.append(o.teacher.name)
    if 'room' in show:
        parts.append(short_room(room))
    return ' | '.join(parts)


def grid_for(problem, assignment, kind, name):
    """Day x slot table for one section, teacher or room."""
    max_slot = max(max(problem.grid.slots(d)) for d in DAYS)
    table = {d: {s: '' for s in range(1, max_slot + 1)} for d in DAYS}
    for mid, (day, start, room) in assignment.items():
        m = problem.meeting_by_id[mid]
        o = m.offering
        if kind == 'section':
            match = not o.is_elective and name in [s.name for s in o.sections]   # electives: own sheet
            show = ('teacher', 'room')
        elif kind == 'teacher':
            match = o.teacher.name == name
            show = ('section', 'room')
        else:
            match = room == name
            show = ('section', 'teacher')
        if match:
            for s in range(start, start + m.length):
                text = cell_text(problem, mid, room, show)
                table[day][s] = (table[day][s] + ' / ' + text) if table[day][s] else text
    frame = pd.DataFrame(table).T
    frame.columns = [f'Slot {s}' for s in frame.columns]
    for d in DAYS:
        if max_slot not in problem.grid.day_slots[d]:
            frame.loc[d, f'Slot {max_slot}'] = '-'
    return frame


def slot_times_frame(problem):
    rows = []
    for d in DAYS:
        rows.append({'day': d, **{f'Slot {s}': problem.grid.time_label(d, s) for s in problem.grid.slots(d)}})
    return pd.DataFrame(rows).fillna('-')


def write_grids(writer, sheet, problem, assignment, kind, names):
    row = 0
    slot_times_frame(problem).to_excel(writer, sheet_name=sheet, startrow=row, index=False)
    row += len(DAYS) + 3
    for name in names:
        pd.DataFrame([[f'{kind.upper()}: {name}']]).to_excel(writer, sheet_name=sheet, startrow=row,
                                                             index=False, header=False)
        frame = grid_for(problem, assignment, kind, name)
        frame.to_excel(writer, sheet_name=sheet, startrow=row + 1)
        row += len(frame) + 4


def export_timetable(problem, assignment, out_dir, summary=None, prefix='timetable'):
    os.makedirs(out_dir, exist_ok=True)
    master = pd.DataFrame(master_rows(problem, assignment))
    validation = pd.DataFrame(validation_rows(problem, assignment))
    csv_path = os.path.join(out_dir, f'{prefix}_master.csv')
    master.to_csv(csv_path, index=False)
    validation.to_csv(os.path.join(out_dir, f'{prefix}_validation.csv'), index=False)

    sections = sorted(s.name for s in problem.sections)
    electives = sorted({problem.meeting_by_id[mid].offering.elective_key for mid in assignment
                        if problem.meeting_by_id[mid].offering.is_elective})
    teachers = sorted(t.name for t in problem.teachers)
    rooms = sorted({room for (d, s, room) in assignment.values()})

    xlsx_path = os.path.join(out_dir, f'{prefix}.xlsx')
    with pd.ExcelWriter(xlsx_path, engine='openpyxl') as writer:
        if summary:
            pd.DataFrame(list(summary.items()), columns=['item', 'value']).to_excel(
                writer, sheet_name='Summary', index=False)
        master.to_excel(writer, sheet_name='Master timetable', index=False)
        write_grids(writer, 'Section timetables', problem, assignment, 'section', sections)
        elective_rows = master[master['elective'] == 'yes']
        elective_rows.to_excel(writer, sheet_name='Electives', index=False)
        write_grids(writer, 'Faculty timetables', problem, assignment, 'teacher', teachers)
        write_grids(writer, 'Room timetables', problem, assignment, 'room', rooms)
        validation.to_excel(writer, sheet_name='Validation report', index=False)
        for ws in writer.book.worksheets:
            for col in ws.columns:
                ws.column_dimensions[col[0].column_letter].width = 24 if col[0].column > 1 else 18
    return xlsx_path, csv_path, len(electives)
