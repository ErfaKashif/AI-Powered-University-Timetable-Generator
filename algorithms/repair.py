"""Min-conflicts repair.

Takes a valid but incomplete timetable and places the missing meetings. For a
missing meeting it picks the value that blocks the fewest already placed
meetings, removes those blockers and puts them back on the waiting list.
The timetable never contains a hard violation: every placement goes through
Timetable.can_place.

Used to:
  * finish a CSP search that got stuck,
  * repair genetic algorithm children,
  * repair a timetable after a change (e.g. a teacher becomes unavailable).
"""
import random
import time

from models.entities import Timetable


def time_blockers(tt, meeting, day, start):
    """Placed meetings that stop `meeting` from using this time (any room)."""
    problem = tt.problem
    o = meeting.offering
    blockers = set()
    for s in range(start, start + meeting.length):
        blockers.add(tt.teacher_at.get((o.teacher.name, day, s)))
        if o.is_elective:
            blockers.add(tt.elective_at.get((o.elective_key, day, s)))
            for sec in problem.groups[o.group]:
                blockers.add(tt.core_at.get((sec.name, day, s)))
        else:
            for sec in o.sections:
                blockers.add(tt.core_at.get((sec.name, day, s)))
            if tt.elective_count.get((o.group, day, s), 0):
                for key in problem.elective_keys.get(o.group, []):
                    blockers.add(tt.elective_at.get((key, day, s)))
    if tt.offering_days.get((o.id, day), 0) >= o.max_per_day:
        for mid, value in tt.assignment.items():
            if value[0] == day and problem.meeting_by_id[mid].offering is o:
                blockers.add(mid)
    blockers.discard(None)
    return blockers


def break_blockers(tt, meeting, day, start):
    """Meetings next to this block that would make the students sit more than 3 hours."""
    out = set()
    lo, hi = start - 3, start + meeting.length + 3
    for key in meeting.offering.student_keys():
        table = tt.elective_at if ':' in key else tt.core_at
        for s in range(lo, hi):
            mid = table.get((key, day, s))
            if mid:
                out.add(mid)
    return out


def try_value(tt, meeting, value, blockers):
    """Remove blockers, try to place. Returns the removed meetings or None (nothing changed)."""
    problem = tt.problem
    removed = {}
    for mid in blockers:
        if mid in tt.assignment:
            removed[mid] = tt.unassign(problem.meeting_by_id[mid])
    if tt.can_place(meeting, value):
        tt.assign(meeting, value)
        return removed
    for mid, old in removed.items():
        tt.assign(problem.meeting_by_id[mid], old)
    return None


def min_conflicts_repair(tt, missing, max_steps=4000, time_limit=30, seed=None, tabu_size=10):
    """Places every meeting in `missing` into the (valid) timetable tt. Returns True on success."""
    rng = random.Random(seed)
    problem = tt.problem
    if not hasattr(problem, 'elective_keys'):
        problem.elective_keys = {}
        for o in problem.offerings:
            if o.is_elective and o.elective_key not in problem.elective_keys.setdefault(o.group, []):
                problem.elective_keys[o.group].append(o.elective_key)
    waiting = list(missing)
    recent = []
    started = time.time()
    steps = 0
    while waiting and steps < max_steps and time.time() - started < time_limit:
        steps += 1
        meeting = problem.meeting_by_id[waiting.pop(rng.randrange(len(waiting)))]
        rooms = sorted(problem.rooms_ok[meeting.id], key=lambda r: problem.room_by_name[r].capacity)
        candidates = []
        for day, start in problem.times_ok[meeting.id]:
            blockers = time_blockers(tt, meeting, day, start)
            best_room, best_room_blockers = None, None
            for room in rooms:
                if not problem.room_free_of_fixed(room, day, start, meeting.length):
                    continue
                in_room = {tt.room_at.get((room, day, s)) for s in range(start, start + meeting.length)}
                in_room.discard(None)
                if best_room is None or len(in_room - blockers) < len(best_room_blockers):
                    best_room, best_room_blockers = room, in_room - blockers
                    if not best_room_blockers:
                        break
            if best_room is None:
                continue
            all_blockers = blockers | best_room_blockers
            penalty = len(all_blockers) + 3 * len(all_blockers & set(recent)) + rng.random()
            candidates.append((penalty, (day, start, best_room), all_blockers))
        candidates.sort(key=lambda c: c[0])
        placed = False
        for penalty, value, blockers in candidates[:15]:
            removed = try_value(tt, meeting, value, blockers)
            if removed is None:
                removed = try_value(tt, meeting, value, blockers | break_blockers(tt, meeting, value[0], value[1]))
            if removed is not None:
                waiting.extend(removed)
                recent = (recent + [meeting.id])[-tabu_size:]
                placed = True
                break
        if not placed:
            waiting.append(meeting.id)
    return not waiting


def complete_with_repair(problem, partial, **kwargs):
    """Builds a Timetable from a valid partial assignment and repairs the rest."""
    tt = Timetable(problem)
    for mid, value in partial.items():
        tt.assign(problem.meeting_by_id[mid], value)
    missing = [m.id for m in problem.meetings if m.id not in tt.assignment]
    ok = min_conflicts_repair(tt, missing, **kwargs)
    return tt, ok


def repair_after_change(problem, old_assignment, **kwargs):
    """Keeps every meeting of an old timetable that is still valid for the (changed) problem
    and re-places only the others. This keeps timetable changes to a minimum."""
    tt = Timetable(problem)
    kept, moved = 0, []
    for m in problem.meetings:
        value = old_assignment.get(m.id)
        if value and tt.can_place(m, value):
            tt.assign(m, value)
            kept += 1
        else:
            moved.append(m.id)
    ok = min_conflicts_repair(tt, moved, **kwargs)
    return tt, ok, kept, moved
