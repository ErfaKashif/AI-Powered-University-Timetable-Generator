"""CSP timetable solver: backtracking search with MRV, degree tie-break and forward checking.

Variables : class meetings
Domains   : (day, start slot, room) values left after the unary constraints
Constraints: checked by Timetable.can_place (teacher/room/section clashes, breaks, ...)
"""
import random
import sys
import time

from algorithms.repair import complete_with_repair
from models.entities import Timetable


class SearchTimeout(Exception):
    pass


class RestartSearch(Exception):
    pass


def conflict_lists(problem):
    """For every meeting, the meetings that can never be at the same time with it."""
    by_teacher, by_section, by_group_core, by_group_elective, by_key = {}, {}, {}, {}, {}
    for m in problem.meetings:
        o = m.offering
        by_teacher.setdefault(o.teacher.name, []).append(m.id)
        if o.is_elective:
            by_group_elective.setdefault(o.group, []).append(m.id)
            by_key.setdefault(o.elective_key, []).append(m.id)
        else:
            by_group_core.setdefault(o.group, []).append(m.id)
            for sec in o.sections:
                by_section.setdefault(sec.name, []).append(m.id)
    conflicts = {}
    for m in problem.meetings:
        o = m.offering
        others = set(by_teacher[o.teacher.name])
        if o.is_elective:
            others |= set(by_key[o.elective_key])
            others |= set(by_group_core.get(o.group, []))
        else:
            for sec in o.sections:
                others |= set(by_section[sec.name])
            others |= set(by_group_elective.get(o.group, []))
        others.discard(m.id)
        conflicts[m.id] = others
    return conflicts


class CSPSolver:
    name = 'CSP (MRV + FC)'

    def __init__(self, problem, use_mrv=True, use_forward_checking=True, time_limit=120,
                 seed=None, randomness=0.0, use_repair=True):
        self.problem = problem
        self.use_repair = use_repair and use_mrv and use_forward_checking
        self.use_mrv = use_mrv
        self.use_fc = use_forward_checking
        self.time_limit = time_limit
        self.rng = random.Random(seed)
        self.randomness = randomness
        self.conflicts = conflict_lists(problem)
        self.room_users = {r.name: set() for r in problem.rooms}
        for m in problem.meetings:
            for r in problem.rooms_ok[m.id]:
                self.room_users[r].add(m.id)
        self.key_members = {}
        for m in problem.meetings:
            for key in m.offering.student_keys():
                self.key_members.setdefault(key, set()).add(m.id)
        self.backtracks = 0
        self.checks = 0
        self.nodes = 0
        self.status = 'not run'
        self.run_time = 0.0
        self.best_partial = {}
        self.fail_count = {}

    # ---------- domains ----------
    def initial_domains(self):
        domains = {}
        for m in self.problem.meetings:
            dom = {}
            for day, slot, room in self.problem.domain_values(m):
                dom.setdefault((day, slot), set()).add(room)
            domains[m.id] = dom
        return domains

    def domain_size(self, mid):
        return sum(len(rooms) for rooms in self.domains[mid].values())

    # ---------- variable and value ordering ----------
    def select_variable(self):
        if not self.use_mrv:
            for m in self.problem.meetings:
                if m.id in self.unassigned:
                    return self.problem.meeting_by_id[m.id]
        clash_risk = getattr(self.problem, 'ml_clash_risk', {})
        # MRV: fewest values left -> highest K-Means clash risk -> highest conflict degree
        best = min(
            self.unassigned,
            key=lambda mid: (
                self.sizes[mid] / (1 + self.fail_count.get(mid, 0)),
                -clash_risk.get(mid, 0.0),
                -len(self.conflicts[mid]),
                mid
            )
        )
        return self.problem.meeting_by_id[best]
    def time_score(self, meeting, day, slot):
        """Lower is better. Uses the soft constraints so the first solution is already decent."""
        o = meeting.offering
        t = o.teacher
        grid = self.problem.grid
        score = 0.0
        if t.preferred_days and day not in t.preferred_days:
            score += 4
        if t.preferred_slots and slot not in t.preferred_slots:
            score += 2
        if grid.is_late(day, slot + meeting.length - 1):
            score += 3
        for key in o.student_keys():
            score += 0.5 * len(self.timetable.busy_slots(key, day))
        if o.is_elective and self.timetable.elective_count.get((o.group, day, slot), 0) > 0:
            score -= 3          # keep electives together in shared elective slots
        if self.timetable.offering_days.get((o.id, day), 0):
            score += 5          # same course already on this day
        if self.randomness:
            score += self.rng.random() * self.randomness
        return score

    def ordered_values(self, meeting):
        if self.use_fc:
            dom = self.domains[meeting.id]
        else:
            dom = {}
            for day, slot, room in self.problem.domain_values(meeting):
                dom.setdefault((day, slot), set()).add(room)
        rooms = self.problem.room_by_name
        times = sorted(dom, key=lambda ds: self.time_score(meeting, ds[0], ds[1]))
        for day, slot in times:
            for room in sorted(dom[(day, slot)], key=lambda r: (rooms[r].capacity, r)):
                yield (day, slot, room)

    # ---------- forward checking ----------
    def forward_check(self, meeting, value):
        """Removes values of unassigned meetings that clash with the new assignment."""
        day, start, room = value
        end = start + meeting.length - 1
        offering = meeting.offering
        day_full = self.timetable.offering_days.get((offering.id, day), 0) >= offering.max_per_day
        trail = []
        affected = (self.conflicts[meeting.id] | self.room_users[room]) & self.unassigned
        for mid in affected:
            other = self.problem.meeting_by_id[mid]
            dom = self.domains[mid]
            length = other.length
            time_clash = mid in self.conflicts[meeting.id]
            same_offering = other.offering is offering
            removed = 0
            for ds in [ds for ds in dom if ds[0] == day]:
                s = ds[1]
                overlaps = s <= end and s + length - 1 >= start
                if (same_offering and day_full) or (overlaps and time_clash):
                    rooms = dom.pop(ds)
                    trail.append((mid, ds, rooms))
                    removed += len(rooms)
                elif overlaps and room in dom[ds]:
                    dom[ds].discard(room)
                    trail.append((mid, ds, {room}))
                    removed += 1
                    if not dom[ds]:
                        del dom[ds]
            if removed:
                self.sizes[mid] -= removed
                if self.sizes[mid] == 0:
                    return trail, False
        return self.check_breaks(offering, day, trail)

    def check_breaks(self, offering, day, trail):
        """Forward checking for the break rule: remove times on this day that would give the
        same students more than 3 hours of continuous classes."""
        grid = self.problem.grid
        for key in offering.student_keys():
            busy = self.timetable.busy_slots(key, day)
            for mid in self.key_members[key] & self.unassigned:
                dom = self.domains[mid]
                length = self.problem.meeting_by_id[mid].length
                for ds in [ds for ds in dom if ds[0] == day]:
                    covered = set(range(ds[1], ds[1] + length))
                    if covered & busy or grid.longest_run(day, busy | covered) > grid.max_continuous:
                        rooms = dom.pop(ds)
                        trail.append((mid, ds, rooms))
                        self.sizes[mid] -= len(rooms)
                if self.sizes[mid] == 0:
                    return trail, False
        return trail, True

    def restore(self, trail):
        for mid, ds, rooms in reversed(trail):
            self.domains[mid].setdefault(ds, set()).update(rooms)
            self.sizes[mid] += len(rooms)

    # ---------- search ----------
    def backtrack(self):
        if not self.unassigned:
            return True
        if time.time() - self.start_time > self.time_limit:
            raise SearchTimeout()
        if self.restart_limit and self.backtracks - self.restart_start > self.restart_limit:
            raise RestartSearch()
        meeting = self.select_variable()
        for value in self.ordered_values(meeting):
            self.checks += 1
            if not self.timetable.can_place(meeting, value):
                continue
            self.nodes += 1
            self.timetable.assign(meeting, value)
            self.unassigned.discard(meeting.id)
            if len(self.timetable.assignment) > len(self.best_partial):
                self.best_partial = dict(self.timetable.assignment)
            trail, ok = self.forward_check(meeting, value) if self.use_fc else ([], True)
            if ok and self.backtrack():
                return True
            self.restore(trail)
            self.timetable.unassign(meeting)
            self.unassigned.add(meeting.id)
        self.backtracks += 1
        self.fail_count[meeting.id] = self.fail_count.get(meeting.id, 0) + 1
        return False

    def reset(self):
        self.timetable = Timetable(self.problem)
        self.unassigned = {m.id for m in self.problem.meetings}
        self.domains = self.initial_domains() if self.use_fc else {}
        if self.use_fc:
            self.sizes = {mid: self.domain_size(mid) for mid in self.domains}
        else:
            self.sizes = {m.id: len(self.problem.times_ok[m.id]) for m in self.problem.meetings}

    def solve(self):
        """Backtracking search. The MRV+FC solver restarts when one search runs too long:
        meetings that failed get priority next time (they are the real bottleneck).
        If use_repair is on, the best partial timetable is finished with min-conflicts repair."""
        sys.setrecursionlimit(max(10000, 4 * len(self.problem.meetings)))
        self.start_time = time.time()
        self.restart_limit = 300 if self.use_mrv and self.use_fc else 0
        self.restarts = 0
        self.repaired = 0
        found = False
        while not found:
            self.reset()
            if self.use_fc and any(size == 0 for size in self.sizes.values()):
                self.status = 'no solution (a meeting has an empty domain)'
                break
            self.restart_start = self.backtracks
            try:
                found = self.backtrack()
                self.status = 'solved' if found else 'no solution'
                break
            except SearchTimeout:
                self.status = 'time limit reached'
                found = self.use_repair and self.try_repair(30)
                break
            except RestartSearch:
                self.restarts += 1
                self.restart_limit = int(self.restart_limit * 1.3)
                self.randomness = max(self.randomness, 4.0)   # try a different part of the search space
                if self.use_repair:
                    left = self.time_limit - (time.time() - self.start_time)
                    found = self.try_repair(min(20, max(5, left)))
        self.run_time = time.time() - self.start_time
        return self.timetable if found else None

    def try_repair(self, seconds):
        tt, ok = complete_with_repair(self.problem, self.best_partial, time_limit=seconds,
                                      seed=self.rng.randrange(10 ** 6))
        if ok:
            self.timetable = tt
            self.repaired = len(self.problem.meetings) - len(self.best_partial)
            self.status = 'solved (backtracking + min-conflicts repair)'
        return ok

    def hardest_meetings(self, n=5):
        """Meetings that most often had no valid value. Used to explain a failure."""
        worst = sorted(self.fail_count.items(), key=lambda kv: -kv[1])[:n]
        return [f'{mid} failed {count} times' for mid, count in worst]

    def stats(self):
        return {'status': self.status, 'backtracks': self.backtracks, 'restarts': getattr(self, 'restarts', 0),
                'constraint_checks': self.checks,
                'nodes': self.nodes, 'time_s': round(self.run_time, 2),
                'repaired_meetings': getattr(self, 'repaired', 0),
                'assigned': len(self.problem.meetings) if self.status.startswith('solved') else len(self.best_partial)}


def plain_backtracking(problem, time_limit=60):
    """Baseline: same search without MRV and without forward checking."""
    solver = CSPSolver(problem, use_mrv=False, use_forward_checking=False, time_limit=time_limit)
    solver.name = 'Plain backtracking'
    return solver
