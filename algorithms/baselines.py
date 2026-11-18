"""Baseline schedulers used to show why the AI methods are needed."""
import random
import time

from models.entities import Timetable


class RandomScheduler:
    """Puts every meeting at a random (day, slot, room) from its domain. Clashes are ignored."""
    name = 'Random'

    def __init__(self, problem, seed=None):
        self.problem = problem
        self.rng = random.Random(seed)

    def solve(self):
        started = time.time()
        assignment = {}
        for m in self.problem.meetings:
            day, slot = self.rng.choice(self.problem.times_ok[m.id])
            room = self.rng.choice(self.problem.rooms_ok[m.id])
            assignment[m.id] = (day, slot, room)
        self.run_time = time.time() - started
        return assignment


class GreedyScheduler:
    """First-fit: most constrained meetings first, each takes the first valid value.
    Never backtracks, so some meetings may stay unscheduled."""
    name = 'Greedy first-fit'

    def __init__(self, problem):
        self.problem = problem

    def solve(self):
        started = time.time()
        tt = Timetable(self.problem)
        order = sorted(self.problem.meetings, key=lambda m: (len(self.problem.times_ok[m.id]) *
                                                             len(self.problem.rooms_ok[m.id]), m.id))
        self.unscheduled = []
        for m in order:
            for value in self.problem.domain_values(m):
                if tt.can_place(m, value):
                    tt.assign(m, value)
                    break
            else:
                self.unscheduled.append(m.id)
        self.run_time = time.time() - started
        return tt.assignment
