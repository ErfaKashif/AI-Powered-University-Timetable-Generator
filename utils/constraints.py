"""Hard constraints (must never be broken) and soft constraints (penalties).

The validator here works only on the plain assignment {meeting_id: (day, slot, room)}.
It does not use the Timetable lookup tables, so it is an independent check of
whatever a solver produced.
"""
from collections import defaultdict

DEFAULT_WEIGHTS = {'gaps': 5, 'late': 3, 'overload': 2, 'pref_day': 4, 'pref_slot': 2,
                   'balance': 2, 'room_waste': 1, 'single_class_day': 2, 'same_day': 5, 'changes': 0}
HARD_WEIGHT = 1000


def build_index(problem, assignment):
    """Who is busy when. Used by every constraint so it is computed only once."""
    index = {'teacher': defaultdict(list), 'room': defaultdict(list), 'core': defaultdict(list),
             'elective_group': defaultdict(list), 'elective_key': defaultdict(list),
             'student_day': defaultdict(set), 'teacher_day': defaultdict(set)}
    for mid, (day, start, room) in assignment.items():
        m = problem.meeting_by_id[mid]
        o = m.offering
        for s in range(start, start + m.length):
            index['teacher'][(o.teacher.name, day, s)].append(mid)
            index['room'][(room, day, s)].append(mid)
            index['teacher_day'][(o.teacher.name, day)].add(s)
            if o.is_elective:
                index['elective_group'][(o.group, day, s)].append(mid)
                index['elective_key'][(o.elective_key, day, s)].append(mid)
            else:
                for sec in o.sections:
                    index['core'][(sec.name, day, s)].append(mid)
            for key in o.student_keys():
                index['student_day'][(key, day)].add(s)
    return index


class Constraint:
    name = 'constraint'

    def check(self, problem, assignment, index):
        """Returns a list of violation messages."""
        raise NotImplementedError


# ---------------- hard constraints ----------------

class TeacherClash(Constraint):
    name = 'Faculty clash'

    def check(self, problem, assignment, index):
        return [f'{t} teaches {ids} at {d} slot {s}' for (t, d, s), ids in index['teacher'].items() if len(ids) > 1]


class RoomClash(Constraint):
    name = 'Room clash'

    def check(self, problem, assignment, index):
        out = [f'{r} has {ids} at {d} slot {s}' for (r, d, s), ids in index['room'].items() if len(ids) > 1]
        for (r, d, s), ids in index['room'].items():
            if (r, d, s) in problem.room_blocked:
                out.append(f'{r} at {d} slot {s} is booked by another batch/reservation but used by {ids}')
        return out


class SectionClash(Constraint):
    name = 'Section clash'

    def check(self, problem, assignment, index):
        out = []
        for (sec, d, s), ids in index['core'].items():
            if len(ids) > 1:
                out.append(f'{sec} has {ids} at {d} slot {s}')
        for (group, d, s), ids in index['elective_group'].items():
            for sec in problem.groups[group]:
                if (sec.name, d, s) in index['core']:
                    out.append(f'elective {ids} overlaps core class of {sec.name} at {d} slot {s}')
        for (key, d, s), ids in index['elective_key'].items():
            if len(ids) > 1:
                out.append(f'elective section {key} has {ids} at {d} slot {s}')
        return out


class RoomCapacity(Constraint):
    name = 'Room capacity'

    def check(self, problem, assignment, index):
        out = []
        for mid, (d, s, room) in assignment.items():
            o = problem.meeting_by_id[mid].offering
            if problem.room_by_name[room].capacity < o.enrollment:
                out.append(f'{mid}: {o.enrollment} students in {room} ({problem.room_by_name[room].capacity})')
        return out


class FacultyAvailability(Constraint):
    name = 'Faculty availability'

    def check(self, problem, assignment, index):
        return [f'{t} is teaching another batch at {d} slot {s} but has {ids}'
                for (t, d, s), ids in index['teacher'].items() if (t, d, s) in problem.teacher_blocked]


class VisitingFaculty(Constraint):
    name = 'Visiting faculty hours'

    def check(self, problem, assignment, index):
        out = []
        for mid, (d, start, room) in assignment.items():
            m = problem.meeting_by_id[mid]
            t = m.teacher
            if not t.is_visiting():
                continue
            if t.available_days and d not in t.available_days:
                out.append(f'{mid}: visiting {t.name} not available on {d}')
            for s in range(start, start + m.length):
                if t.available_slots and s not in t.available_slots:
                    out.append(f'{mid}: visiting {t.name} not available at {d} slot {s}')
        return out


class FixedDays(Constraint):
    name = 'Fixed faculty days'

    def check(self, problem, assignment, index):
        return [f'{mid}: {problem.meeting_by_id[mid].teacher.name} only works on {sorted(problem.meeting_by_id[mid].teacher.fixed_days)}'
                for mid, (d, s, r) in assignment.items()
                if problem.meeting_by_id[mid].teacher.fixed_days and d not in problem.meeting_by_id[mid].teacher.fixed_days]


class FacultyDayOff(Constraint):
    name = 'Faculty day off'

    def check(self, problem, assignment, index):
        return [f'{mid}: {problem.meeting_by_id[mid].teacher.name} is off on {d}'
                for mid, (d, s, r) in assignment.items() if problem.meeting_by_id[mid].teacher.day_off == d]


class BatchDayOff(Constraint):
    name = 'Batch day off'

    def check(self, problem, assignment, index):
        out = []
        for mid, (d, s, r) in assignment.items():
            for sec in problem.meeting_by_id[mid].offering.sections:
                if d in sec.days_off:
                    out.append(f'{mid}: {sec.name} is off on {d}')
        return out


class StudentBreak(Constraint):
    name = 'Break after 3 hours'

    def check(self, problem, assignment, index):
        out = []
        limit = problem.grid.max_continuous
        for (key, d), slots in index['student_day'].items():
            run = problem.grid.longest_run(d, slots)
            if run > limit:
                out.append(f'{key} has {run} minutes of continuous classes on {d}')
        return out


class SpecialRoom(Constraint):
    name = 'Special room requirement'

    def check(self, problem, assignment, index):
        out = []
        for mid, (d, s, room) in assignment.items():
            o = problem.meeting_by_id[mid].offering
            if o.required_rooms and room not in o.required_rooms:
                out.append(f'{mid} must be in {sorted(o.required_rooms)} but is in {room}')
        return out


class CourseHours(Constraint):
    name = 'Missing course hours'

    def check(self, problem, assignment, index):
        return [f'{m.id} ({m.offering.course} {m.offering.section_names}) is not scheduled'
                for m in problem.meetings if m.id not in assignment]


class RoomType(Constraint):
    name = 'Lab / room type'

    def check(self, problem, assignment, index):
        out = []
        for mid, (d, s, room) in assignment.items():
            o = problem.meeting_by_id[mid].offering
            r = problem.room_by_name[room]
            if o.kind == 'lab' and r.kind != 'lab':
                out.append(f'{mid}: lab placed in classroom {room}')
            if o.kind == 'lecture' and r.kind != 'classroom':
                out.append(f'{mid}: lecture placed in lab {room}')
            if r.is_ee_lab and not o.required_rooms:
                out.append(f'{mid}: {room} is reserved for electrical engineering labs')
        return out


class ValidTime(Constraint):
    name = 'Invalid time'

    def check(self, problem, assignment, index):
        out = []
        for mid, (d, s, room) in assignment.items():
            m = problem.meeting_by_id[mid]
            if d not in problem.grid.day_slots or not problem.grid.is_valid_block(d, s, m.length):
                out.append(f'{mid}: {d} slot {s} (length {m.length}) is outside operating hours or crosses a break')
        return out


class SpreadDays(Constraint):
    name = 'Same course too often in a day'

    def check(self, problem, assignment, index):
        count = defaultdict(int)
        for mid, (d, s, r) in assignment.items():
            count[(problem.meeting_by_id[mid].offering, d)] += 1
        return [f'{o.id} meets {n} times on {d}' for (o, d), n in count.items() if n > o.max_per_day]


HARD_CONSTRAINTS = [TeacherClash(), RoomClash(), SectionClash(), RoomCapacity(), FacultyAvailability(),
                    VisitingFaculty(), FixedDays(), FacultyDayOff(), BatchDayOff(), StudentBreak(),
                    SpecialRoom(), CourseHours(), RoomType(), ValidTime(), SpreadDays()]


def find_violations(problem, assignment):
    """{constraint name: [messages]} for every hard constraint."""
    index = build_index(problem, assignment)
    return {c.name: c.check(problem, assignment, index) for c in HARD_CONSTRAINTS}


def count_hard(problem, assignment):
    return sum(len(v) for v in find_violations(problem, assignment).values())


# ---------------- soft constraints ----------------

def gaps_in(slots):
    """Idle slots between classes. One free slot is a normal break, so only longer gaps count."""
    slots = sorted(slots)
    return sum(max(0, b - a - 2) for a, b in zip(slots, slots[1:]))


class SoftConstraint:
    key = ''

    def penalty(self, problem, assignment, index):
        raise NotImplementedError


class GapPenalty(SoftConstraint):
    key = 'gaps'

    def penalty(self, problem, assignment, index):
        total = sum(gaps_in(s) for (k, d), s in index['student_day'].items() if ':' not in k)
        return total + sum(gaps_in(s) for s in index['teacher_day'].values())


class LateSlotPenalty(SoftConstraint):
    key = 'late'

    def penalty(self, problem, assignment, index):
        total = 0
        for mid, (d, start, r) in assignment.items():
            last = start + problem.meeting_by_id[mid].length - 1
            total += problem.grid.is_late(d, last)
        return total


class OverloadedDay(SoftConstraint):
    key = 'overload'

    def penalty(self, problem, assignment, index):
        total = sum(max(0, len(s) - 5) for (k, d), s in index['student_day'].items() if ':' not in k)
        return total + sum(max(0, len(s) - 4) for s in index['teacher_day'].values())


class TeacherPreferredDays(SoftConstraint):
    key = 'pref_day'

    def penalty(self, problem, assignment, index):
        total = 0
        for mid, (d, s, r) in assignment.items():
            t = problem.meeting_by_id[mid].teacher
            if t.preferred_days and d not in t.preferred_days:
                total += 1
        return total


class TeacherPreferredSlots(SoftConstraint):
    key = 'pref_slot'

    def penalty(self, problem, assignment, index):
        total = 0
        for mid, (d, s, r) in assignment.items():
            t = problem.meeting_by_id[mid].teacher
            if t.preferred_slots and s not in t.preferred_slots:
                total += 1
        return total


class BalancedDays(SoftConstraint):
    """Difference between the busiest and the lightest teaching day of a section and a teacher."""
    key = 'balance'

    def penalty(self, problem, assignment, index):
        total = 0
        for sec in problem.sections:
            days = [d for d in problem.grid.day_slots if d not in sec.days_off]
            loads = [len(index['student_day'].get((sec.name, d), ())) for d in days]
            if loads:
                total += max(loads) - min(loads)
        for t in problem.teachers:
            loads = [len(index['teacher_day'].get((t.name, d), ())) for d in t.allowed_days()]
            if loads and sum(loads) >= len(loads):
                total += max(0, max(loads) - min(loads) - 1)
        return total


class RoomWaste(SoftConstraint):
    """Seats wasted compared with the smallest suitable room (per 5 seats)."""
    key = 'room_waste'

    def penalty(self, problem, assignment, index):
        total = 0
        for mid, (d, s, room) in assignment.items():
            smallest = min(problem.room_by_name[r].capacity for r in problem.rooms_ok[mid])
            total += (problem.room_by_name[room].capacity - smallest) // 5
        return total


class SingleClassDay(SoftConstraint):
    """Coming to campus for one class only (fragmented schedule)."""
    key = 'single_class_day'

    def penalty(self, problem, assignment, index):
        total = sum(1 for (k, d), s in index['student_day'].items() if ':' not in k and len(s) == 1)
        return total + sum(1 for s in index['teacher_day'].values() if len(s) == 1)


class SameDayRepeat(SoftConstraint):
    """A course should meet on different days (proposal). Each extra meeting on a day costs."""
    key = 'same_day'

    def penalty(self, problem, assignment, index):
        count = defaultdict(int)
        for mid, (d, s, r) in assignment.items():
            count[(problem.meeting_by_id[mid].offering.id, d)] += 1
        return sum(n - 1 for n in count.values() if n > 1)


class ChangesFromReference(SoftConstraint):
    """Meetings moved away from the previous timetable (only if a reference is given)."""
    key = 'changes'

    def __init__(self):
        self.reference = {}

    def penalty(self, problem, assignment, index):
        if not self.reference:
            return 0
        return sum(1 for mid, (d, s, r) in assignment.items()
                   if mid in self.reference and self.reference[mid][:2] != (d, s))


SOFT_CONSTRAINTS = [GapPenalty(), LateSlotPenalty(), OverloadedDay(), TeacherPreferredDays(),
                    TeacherPreferredSlots(), BalancedDays(), RoomWaste(), SingleClassDay(), SameDayRepeat(),
                    ChangesFromReference()]


def set_reference(reference):
    for c in SOFT_CONSTRAINTS:
        if isinstance(c, ChangesFromReference):
            c.reference = reference or {}


def soft_breakdown(problem, assignment, weights=None, index=None):
    weights = weights or DEFAULT_WEIGHTS
    index = index or build_index(problem, assignment)
    result = {}
    for c in SOFT_CONSTRAINTS:
        if weights.get(c.key, 0) == 0:
            result[c.key] = 0
        else:
            result[c.key] = c.penalty(problem, assignment, index)
    return result


def soft_cost(problem, assignment, weights=None):
    weights = weights or DEFAULT_WEIGHTS
    breakdown = soft_breakdown(problem, assignment, weights)
    return sum(weights.get(k, 0) * v for k, v in breakdown.items())


def total_cost(problem, assignment, weights=None):
    """Cost from the proposal: 1000 x hard violations + weighted soft penalties."""
    return HARD_WEIGHT * count_hard(problem, assignment) + soft_cost(problem, assignment, weights)


def fitness(cost):
    return 1.0 / (1.0 + cost)


def room_utilization(problem, assignment):
    """Average share of seats used (enrollment / room capacity) in %."""
    if not assignment:
        return 0.0
    used = [problem.meeting_by_id[mid].offering.enrollment / problem.room_by_name[room].capacity
            for mid, (d, s, room) in assignment.items()]
    return 100.0 * sum(used) / len(used)


def validation_rows(problem, assignment):
    """Table rows for the constraint validation report."""
    rows = []
    for name, messages in find_violations(problem, assignment).items():
        rows.append({'constraint': name, 'type': 'hard', 'violations': len(messages),
                     'status': 'OK' if not messages else 'VIOLATED',
                     'examples': ' || '.join(messages[:3])})
    for key, value in soft_breakdown(problem, assignment).items():
        rows.append({'constraint': key, 'type': 'soft', 'violations': value,
                     'status': f'penalty {value * DEFAULT_WEIGHTS.get(key, 0)}', 'examples': ''})
    return rows


class SoftCostTracker:
    """Same soft cost as soft_cost(), but computed per section / teacher / course using the
    Timetable lookup tables. After a move only the touched parts are recomputed, which makes
    hill climbing, simulated annealing and GA mutation many times faster."""

    def __init__(self, problem, weights=None):
        self.problem = problem
        self.w = weights or DEFAULT_WEIGHTS
        self.smallest_room = {m.id: min(problem.room_by_name[r].capacity for r in problem.rooms_ok[m.id])
                              for m in problem.meetings}
        self.reference = next((c.reference for c in SOFT_CONSTRAINTS if isinstance(c, ChangesFromReference)), {})

    def meeting_cost(self, tt, mid):
        day, start, room = tt.assignment[mid]
        m = self.problem.meeting_by_id[mid]
        t = m.teacher
        w = self.w
        cost = w.get('late', 0) * self.problem.grid.is_late(day, start + m.length - 1)
        cost += w.get('pref_day', 0) * bool(t.preferred_days and day not in t.preferred_days)
        cost += w.get('pref_slot', 0) * bool(t.preferred_slots and start not in t.preferred_slots)
        cost += w.get('room_waste', 0) * ((self.problem.room_by_name[room].capacity - self.smallest_room[mid]) // 5)
        if self.reference and mid in self.reference and self.reference[mid][:2] != (day, start):
            cost += w.get('changes', 0)
        return cost

    def day_cost(self, slots, overload_limit):
        if not slots:
            return 0
        w = self.w
        return (w.get('gaps', 0) * gaps_in(slots) + w.get('overload', 0) * max(0, len(slots) - overload_limit)
                + w.get('single_class_day', 0) * (len(slots) == 1))

    def section_cost(self, tt, section):
        loads = []
        cost = 0
        for day in self.problem.grid.day_slots:
            slots = tt.busy_slots(section.name, day)
            cost += self.day_cost(slots, 5)
            if day not in section.days_off:
                loads.append(len(slots))
        if loads:
            cost += self.w.get('balance', 0) * (max(loads) - min(loads))
        return cost

    def teacher_cost(self, tt, teacher):
        cost = 0
        loads = {}
        for day in self.problem.grid.day_slots:
            slots = {s for s in self.problem.grid.slots(day) if (teacher.name, day, s) in tt.teacher_at}
            cost += self.day_cost(slots, 4)
            loads[day] = len(slots)
        allowed = [loads[d] for d in teacher.allowed_days()]
        if allowed and sum(allowed) >= len(allowed):
            cost += self.w.get('balance', 0) * max(0, max(allowed) - min(allowed) - 1)
        return cost

    def offering_cost(self, tt, offering):
        repeats = sum(max(0, tt.offering_days.get((offering.id, d), 0) - 1) for d in self.problem.grid.day_slots)
        return self.w.get('same_day', 0) * repeats

    def total(self, tt):
        cost = sum(self.meeting_cost(tt, mid) for mid in tt.assignment)
        cost += sum(self.section_cost(tt, s) for s in self.problem.sections)
        cost += sum(self.teacher_cost(tt, t) for t in self.problem.teachers)
        cost += sum(self.offering_cost(tt, o) for o in self.problem.offerings)
        return cost

    def partial(self, tt, meetings):
        """Cost of everything that the given meetings can influence."""
        sections, teachers, offerings = {}, {}, {}
        for m in meetings:
            o = m.offering
            offerings[o.id] = o
            teachers[o.teacher.name] = o.teacher
            if not o.is_elective:
                for s in o.sections:
                    sections[s.name] = s
        cost = sum(self.meeting_cost(tt, m.id) for m in meetings if m.id in tt.assignment)
        cost += sum(self.section_cost(tt, s) for s in sections.values())
        cost += sum(self.teacher_cost(tt, t) for t in teachers.values())
        cost += sum(self.offering_cost(tt, o) for o in offerings.values())
        return cost
