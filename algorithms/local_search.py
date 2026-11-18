"""Hill climbing and simulated annealing. Both start from a valid timetable
(normally the CSP solution) and only make valid moves, so the result is always valid."""
import math
import random
import time

from algorithms.moves import move_delta, random_neighbour, undo
from utils.constraints import SoftCostTracker


class HillClimbing:
    """Takes a random valid neighbour; keeps it only if the soft cost does not get worse."""
    name = 'Hill climbing'

    def __init__(self, start, max_iterations=20000, patience=4000, seed=None, weights=None, time_limit=120):
        self.start = start
        self.max_iterations = max_iterations
        self.patience = patience
        self.rng = random.Random(seed)
        self.tracker = SoftCostTracker(start.problem, weights)
        self.time_limit = time_limit
        self.history = []

    def run(self):
        tt = self.start.copy()
        current = self.tracker.total(tt)
        no_improvement = 0
        started = time.time()
        it = 0
        while it < self.max_iterations and no_improvement < self.patience:
            if time.time() - started > self.time_limit:
                break
            it += 1
            change = random_neighbour(tt, self.rng)
            if change is None:
                no_improvement += 1
                continue
            delta = move_delta(tt, change, self.tracker)
            if delta < 0:
                current += delta
                no_improvement = 0
            elif delta == 0:
                no_improvement += 1          # sideways move is kept (helps on plateaus)
            else:
                undo(tt, change)
                no_improvement += 1
            self.history.append(current)
        self.iterations = it
        self.run_time = time.time() - started
        return tt


class SimulatedAnnealing:
    """Like hill climbing, but a worse neighbour is accepted with probability exp(-delta / T).
    T starts high (many bad moves accepted) and is multiplied by `cooling` every iteration."""
    name = 'Simulated annealing'

    def __init__(self, start, initial_temperature=20.0, cooling=0.9997, min_temperature=0.05,
                 max_iterations=20000, seed=None, weights=None, time_limit=120):
        self.start = start
        self.t0 = initial_temperature
        self.cooling = cooling
        self.t_min = min_temperature
        self.max_iterations = max_iterations
        self.rng = random.Random(seed)
        self.tracker = SoftCostTracker(start.problem, weights)
        self.time_limit = time_limit
        self.history = []

    def run(self):
        tt = self.start.copy()
        current = self.tracker.total(tt)
        best, best_cost = tt.copy(), current
        temperature = self.t0
        started = time.time()
        it = 0
        while temperature > self.t_min and it < self.max_iterations and time.time() - started < self.time_limit:
            it += 1
            change = random_neighbour(tt, self.rng)
            if change is not None:
                delta = move_delta(tt, change, self.tracker)
                if delta <= 0 or self.rng.random() < math.exp(-delta / temperature):
                    current += delta
                    if current < best_cost:
                        best, best_cost = tt.copy(), current
                else:
                    undo(tt, change)
            temperature *= self.cooling
            self.history.append(best_cost)
        self.iterations = it
        self.final_temperature = temperature
        self.run_time = time.time() - started
        return best
