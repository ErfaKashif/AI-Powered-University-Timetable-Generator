"""Neighbour moves used by hill climbing, simulated annealing and GA mutation.
Every move keeps the timetable valid: it is only applied if can_place allows it."""


def move_meeting(tt, meeting, rng, tries=25):
    """Moves one meeting to another valid (day, slot, room). Returns an undo record or None."""
    problem = tt.problem
    old = tt.unassign(meeting)
    times = problem.times_ok[meeting.id]
    rooms = problem.rooms_ok[meeting.id]
    for _ in range(tries):
        day, slot = rng.choice(times)
        room = rng.choice(rooms) if rng.random() < 0.5 else old[2]
        value = (day, slot, room)
        if value != old and tt.can_place(meeting, value):
            tt.assign(meeting, value)
            return [(meeting, old, value)]
    tt.assign(meeting, old)
    return None


def swap_meetings(tt, rng, tries=10):
    """Swaps the (day, slot, room) of two meetings with the same length."""
    problem = tt.problem
    for _ in range(tries):
        a = rng.choice(problem.meetings)
        b = rng.choice(problem.meetings)
        if a is b or a.length != b.length:
            continue
        va, vb = tt.unassign(a), tt.unassign(b)
        if tt.can_place(a, vb):
            tt.assign(a, vb)
            if tt.can_place(b, va):
                tt.assign(b, va)
                return [(a, va, vb), (b, vb, va)]
            tt.unassign(a)
        tt.assign(a, va)
        tt.assign(b, vb)
    return None


def random_neighbour(tt, rng, swap_chance=0.3):
    if rng.random() < swap_chance:
        change = swap_meetings(tt, rng)
        if change:
            return change
    return move_meeting(tt, rng.choice(tt.problem.meetings), rng)


def undo(tt, change):
    for meeting, old, new in change:
        tt.unassign(meeting)
    for meeting, old, new in change:
        tt.assign(meeting, old)


def redo(tt, change):
    for meeting, old, new in change:
        tt.unassign(meeting)
    for meeting, old, new in change:
        tt.assign(meeting, new)


def move_delta(tt, change, tracker):
    """Soft cost change caused by an already applied move (the move stays applied)."""
    meetings = [c[0] for c in change]
    after = tracker.partial(tt, meetings)
    undo(tt, change)
    before = tracker.partial(tt, meetings)
    redo(tt, change)
    return after - before
