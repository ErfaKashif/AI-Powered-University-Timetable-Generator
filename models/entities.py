"""Domain classes of the timetable problem."""
import math
import re

DAYS = ['MON', 'TUE', 'WED', 'THU', 'FRI']
EE_LAB_WORDS = ('Electronics', 'PHYSICS', 'MPI', 'Project')


class Room:
    def __init__(self, name, capacity, kind):
        self.name = name
        self.capacity = capacity
        self.kind = kind                      # 'classroom' or 'lab'
        self.is_ee_lab = kind == 'lab' and any(w in name for w in EE_LAB_WORDS)

    def __repr__(self):
        return f'Room({self.name}, {self.capacity})'


class Teacher:
    def __init__(self, name, faculty_type='permanent', available_days=None, available_slots=None,
                 fixed_days=None, day_off='', preferred_days=None, preferred_slots=None):
        self.name = name
        self.faculty_type = faculty_type
        self.available_days = set(available_days or [])     # only used for visiting faculty
        self.available_slots = set(available_slots or [])   # empty = whole day
        self.fixed_days = set(fixed_days or [])
        self.day_off = day_off
        self.preferred_days = set(preferred_days or [])
        self.preferred_slots = set(preferred_slots or [])

    def is_visiting(self):
        return self.faculty_type == 'visiting'

    def allowed_days(self):
        days = set(DAYS)
        if self.day_off:
            days.discard(self.day_off)
        if self.fixed_days:
            days &= self.fixed_days
        if self.is_visiting() and self.available_days:
            days &= self.available_days
        return days

    def can_teach_slot(self, slot):
        if self.is_visiting() and self.available_slots:
            return slot in self.available_slots
        return True

    def __repr__(self):
        return f'Teacher({self.name})'


class Section:
    def __init__(self, name, program, semester, days_off=None, enrollment=45):
        self.name = name
        self.program = program
        self.semester = semester
        self.days_off = set(days_off or [])
        self.enrollment = enrollment

    @property
    def group(self):
        return f'{self.program}-{self.semester}'

    def __repr__(self):
        return f'Section({self.name})'


class Offering:
    """One course given to one (or a combined set of) section(s) by one teacher."""

    def __init__(self, offering_id, course, kind, teacher, sections, meetings_per_week,
                 length=1, is_elective=False, required_rooms=None):
        self.id = offering_id
        self.course = course
        self.kind = kind                      # 'lecture' or 'lab'
        self.teacher = teacher
        self.sections = sections              # list of Section
        self.meetings_per_week = meetings_per_week
        self.length = length                  # slots per meeting (labs = 3)
        self.is_elective = is_elective
        self.required_rooms = set(required_rooms or [])
        self.max_per_day = 2        # hard cap; more than one a day is also penalised as soft

    @property
    def group(self):
        return self.sections[0].group

    @property
    def enrollment(self):
        return sum(s.enrollment for s in self.sections)

    @property
    def section_names(self):
        return '+'.join(s.name for s in self.sections)

    @property
    def elective_key(self):
        """Students of one elective section (its lecture and its lab share the key)."""
        letters = ''.join(s.name[-1] for s in self.sections)
        return f'{self.group}{letters}:{self.course}'

    def student_keys(self):
        """Keys used for the break rule and day load: core sections, or the elective group."""
        if self.is_elective:
            return [self.elective_key]
        return [s.name for s in self.sections]


class Meeting:
    """One weekly class meeting. This is a CSP variable."""

    def __init__(self, offering, number):
        self.offering = offering
        self.number = number
        self.id = f'{offering.id}#{number}'

    @property
    def teacher(self):
        return self.offering.teacher

    @property
    def length(self):
        return self.offering.length

    def __repr__(self):
        return f'Meeting({self.id})'


def parse_minutes(text):
    """'08:00-8:55' -> (480, 535). Afternoon hours are written without 12h prefix."""
    parts = re.findall(r'(\d{1,2}):(\d{2})', text)
    minutes = []
    for h, m in parts[:2]:
        h = int(h)
        if h < 8:
            h += 12
        minutes.append(h * 60 + int(m))
    return minutes[0], minutes[1]


class TimeGrid:
    """Teaching slots of every day with their start and end time (in minutes)."""

    def __init__(self, day_slots, max_continuous=180, max_gap_for_continuous=10):
        self.day_slots = day_slots            # {'MON': {1: (480, 535), ...}, ...}
        self.max_continuous = max_continuous
        self.max_gap = max_gap_for_continuous

    def slots(self, day):
        return sorted(self.day_slots[day])

    def all_times(self):
        return [(d, s) for d in DAYS for s in self.slots(d)]

    def covered(self, day, start, length):
        return list(range(start, start + length))

    def is_valid_block(self, day, start, length):
        """A meeting must fit inside the day and must not cross a break (e.g. Jumma)."""
        slots = self.day_slots[day]
        for s in range(start, start + length):
            if s not in slots:
                return False
            if s > start and slots[s][0] - slots[s - 1][1] > self.max_gap:
                return False
        return True

    def longest_run(self, day, busy_slots):
        """Longest continuous teaching time (minutes) for a set of busy slots."""
        slots = self.day_slots[day]
        longest, run_start, last_end = 0, None, None
        for s in sorted(busy_slots):
            start, end = slots[s]
            if run_start is None or start - last_end > self.max_gap:
                run_start = start
            last_end = end
            longest = max(longest, end - run_start)
        return longest

    def time_label(self, day, slot):
        start, end = self.day_slots[day][slot]
        return f'{start // 60:02d}:{start % 60:02d}-{end // 60:02d}:{end % 60:02d}'

    def is_late(self, day, slot):
        return self.day_slots[day][slot][0] >= 15 * 60


class Problem:
    """Everything the solvers need: data, fixed bookings and the unary-filtered domains."""

    def __init__(self, rooms, teachers, sections, offerings, grid,
                 teacher_blocked=None, room_blocked=None, name='problem'):
        self.name = name
        self.rooms = rooms
        self.teachers = teachers
        self.sections = sections
        self.offerings = offerings
        self.grid = grid
        self.teacher_blocked = set(teacher_blocked or [])   # (teacher, day, slot) used by other batches
        self.room_blocked = set(room_blocked or [])         # (room, day, slot) used by other batches
        self.meetings = [Meeting(o, i + 1) for o in offerings for i in range(o.meetings_per_week)]
        self.meeting_by_id = {m.id: m for m in self.meetings}
        self.room_by_name = {r.name: r for r in rooms}
        self.groups = {}
        for s in sections:
            self.groups.setdefault(s.group, []).append(s)
        self.times_ok = {}
        self.rooms_ok = {}
        self.time_set = {}
        self.room_set = {}
        self.prepare()

    def suitable_rooms(self, offering):
        result = []
        for room in self.rooms:
            if offering.required_rooms and room.name not in offering.required_rooms:
                continue
            if room.capacity < offering.enrollment:
                continue
            if offering.kind == 'lab' and room.kind != 'lab':
                continue
            if offering.kind == 'lecture' and room.kind != 'classroom':
                continue
            if room.is_ee_lab and not offering.required_rooms:
                continue
            result.append(room.name)
        return result

    def allowed_times(self, offering):
        teacher = offering.teacher
        days = teacher.allowed_days()
        for s in offering.sections:
            days -= s.days_off
        times = []
        for day in DAYS:
            if day not in days:
                continue
            for slot in self.grid.slots(day):
                if not self.grid.is_valid_block(day, slot, offering.length):
                    continue
                covered = self.grid.covered(day, slot, offering.length)
                if not all(teacher.can_teach_slot(s) for s in covered):
                    continue
                if any((teacher.name, day, s) in self.teacher_blocked for s in covered):
                    continue
                times.append((day, slot))
        return times

    def prepare(self):
        """Unary constraints are applied once here, so the search never sees those values."""
        for o in self.offerings:
            times = self.allowed_times(o)
            rooms = self.suitable_rooms(o)
            n_days = len({d for d, _ in times}) or 1
            o.max_per_day = max(2, math.ceil(o.meetings_per_week / n_days))
            for i in range(o.meetings_per_week):
                mid = f'{o.id}#{i + 1}'
                self.times_ok[mid] = times
                self.rooms_ok[mid] = rooms
                self.time_set[mid] = set(times)
                self.room_set[mid] = set(rooms)

    def room_free_of_fixed(self, room, day, start, length):
        return all((room, day, s) not in self.room_blocked for s in range(start, start + length))

    def domain_values(self, meeting):
        values = []
        for day, slot in self.times_ok[meeting.id]:
            for room in self.rooms_ok[meeting.id]:
                if self.room_free_of_fixed(room, day, slot, meeting.length):
                    values.append((day, slot, room))
        return values


class Timetable:
    """A (partial or complete) assignment meeting -> (day, slot, room) with fast lookups."""

    def __init__(self, problem):
        self.problem = problem
        self.assignment = {}
        self.teacher_at = {}
        self.room_at = {}
        self.core_at = {}           # (section, day, slot) -> meeting id
        self.elective_count = {}    # (group, day, slot) -> number of elective meetings
        self.elective_at = {}       # (elective key, day, slot) -> meeting id
        self.offering_days = {}     # (offering id, day) -> number of meetings

    def copy(self):
        new = Timetable.__new__(Timetable)
        new.problem = self.problem
        new.assignment = dict(self.assignment)
        new.teacher_at = dict(self.teacher_at)
        new.room_at = dict(self.room_at)
        new.core_at = dict(self.core_at)
        new.elective_count = dict(self.elective_count)
        new.elective_at = dict(self.elective_at)
        new.offering_days = dict(self.offering_days)
        return new

    def is_complete(self):
        return len(self.assignment) == len(self.problem.meetings)

    def assign(self, meeting, value):
        day, start, room = value
        o = meeting.offering
        self.assignment[meeting.id] = value
        for s in range(start, start + meeting.length):
            self.teacher_at[(o.teacher.name, day, s)] = meeting.id
            self.room_at[(room, day, s)] = meeting.id
            if o.is_elective:
                key = (o.group, day, s)
                self.elective_count[key] = self.elective_count.get(key, 0) + 1
                self.elective_at[(o.elective_key, day, s)] = meeting.id
            else:
                for sec in o.sections:
                    self.core_at[(sec.name, day, s)] = meeting.id
        key = (o.id, day)
        self.offering_days[key] = self.offering_days.get(key, 0) + 1

    def unassign(self, meeting):
        day, start, room = self.assignment.pop(meeting.id)
        o = meeting.offering
        for s in range(start, start + meeting.length):
            del self.teacher_at[(o.teacher.name, day, s)]
            del self.room_at[(room, day, s)]
            if o.is_elective:
                key = (o.group, day, s)
                self.elective_count[key] -= 1
                if self.elective_count[key] == 0:
                    del self.elective_count[key]
                del self.elective_at[(o.elective_key, day, s)]
            else:
                for sec in o.sections:
                    del self.core_at[(sec.name, day, s)]
        self.offering_days[(o.id, day)] -= 1
        return (day, start, room)

    def busy_slots(self, student_key, day):
        """Slots in which a core section (or an elective group) has class on a day."""
        table = self.elective_at if ':' in student_key else self.core_at
        return {s for s in self.problem.grid.slots(day) if (student_key, day, s) in table}

    def can_place(self, meeting, value):
        """True if the meeting can take this value without breaking any hard constraint.
        The meeting itself must not be assigned at the moment."""
        day, start, room = value
        o = meeting.offering
        problem = self.problem
        if (day, start) not in problem.time_set[meeting.id] or room not in problem.room_set[meeting.id]:
            return False
        if not problem.room_free_of_fixed(room, day, start, meeting.length):
            return False
        if self.offering_days.get((o.id, day), 0) >= o.max_per_day:
            return False
        covered = range(start, start + meeting.length)
        for s in covered:
            if (o.teacher.name, day, s) in self.teacher_at or (room, day, s) in self.room_at:
                return False
            if o.is_elective:
                if (o.elective_key, day, s) in self.elective_at:
                    return False
                if any((sec.name, day, s) in self.core_at for sec in problem.groups[o.group]):
                    return False
            else:
                if self.elective_count.get((o.group, day, s), 0) > 0:
                    return False
                if any((sec.name, day, s) in self.core_at for sec in o.sections):
                    return False
        for key in o.student_keys():
            busy = self.busy_slots(key, day) | set(covered)
            if problem.grid.longest_run(day, busy) > problem.grid.max_continuous:
                return False
        return True
