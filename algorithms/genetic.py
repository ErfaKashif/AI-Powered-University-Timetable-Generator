"""Genetic algorithm that improves valid timetables.

Chromosome : a complete timetable, one gene (day, slot, room) per meeting
Fitness    : 1 / (1 + soft cost)   (hard violations are never allowed in the population)
Selection  : tournament (size 3)
Crossover  : the child takes whole program-semesters (e.g. BCS-5) from the second parent;
             clashes caused by that are fixed with min-conflicts repair, else the child is rejected
Mutation   : each gene moves to another valid value with probability mutation_rate
Elitism    : the best timetables are copied unchanged to the next generation
"""
import random
import time

from algorithms.csp import CSPSolver
from algorithms.moves import move_delta, move_meeting, undo
from algorithms.repair import min_conflicts_repair
from utils.constraints import SoftCostTracker, count_hard, fitness


class Chromosome:
    def __init__(self, timetable, tracker):
        self.timetable = timetable
        self.cost = tracker.total(timetable)

    @property
    def fitness(self):
        return fitness(self.cost)


class GeneticAlgorithm:
    name = 'Genetic algorithm'

    def __init__(self, start, population_size=30, generations=100, mutation_rate=0.02,
                 tournament_size=3, elitism=2, patience=30, csp_starts=0, seed=None, weights=None,
                 time_limit=300):
        self.start = start
        self.problem = start.problem
        self.population_size = population_size
        self.generations = generations
        self.mutation_rate = mutation_rate
        self.tournament_size = tournament_size
        self.elitism = elitism
        self.patience = patience
        self.csp_starts = csp_starts
        self.rng = random.Random(seed)
        self.tracker = SoftCostTracker(self.problem, weights)
        self.time_limit = time_limit
        self.history = []
        self.average_history = []
        self.rejected_children = 0
        self.repaired_children = 0

    # ---------- initial population ----------
    def initial_population(self):
        population = [Chromosome(self.start.copy(), self.tracker)]
        for i in range(self.csp_starts):           # extra random CSP solutions
            solver = CSPSolver(self.problem, time_limit=60, seed=self.rng.randrange(10 ** 6), randomness=6.0)
            tt = solver.solve()
            if tt is not None:
                population.append(Chromosome(tt, self.tracker))
        while len(population) < self.population_size:
            base = self.rng.choice(population[:max(1, 1 + self.csp_starts)]).timetable.copy()
            for _ in range(len(self.problem.meetings) // 8):      # random valid moves = a new individual
                move_meeting(base, self.rng.choice(self.problem.meetings), self.rng, tries=5)
            population.append(Chromosome(base, self.tracker))
        return population

    # ---------- operators ----------
    def select(self, population):
        contestants = self.rng.sample(population, self.tournament_size)
        return max(contestants, key=lambda c: c.fitness)

    def crossover(self, parent1, parent2):
        child = parent1.timetable.copy()
        groups = sorted(self.problem.groups)
        chosen = set(self.rng.sample(groups, max(1, len(groups) // 2)))
        taken = [m for m in self.problem.meetings if m.offering.group in chosen]
        for m in taken:
            child.unassign(m)
        missing = []
        for m in self.rng.sample(taken, len(taken)):
            value = parent2.timetable.assignment[m.id]
            if child.can_place(m, value):
                child.assign(m, value)
            else:
                missing.append(m.id)
        if missing:
            if not min_conflicts_repair(child, missing, max_steps=300, time_limit=2,
                                        seed=self.rng.randrange(10 ** 6)):
                self.rejected_children += 1
                return parent1.timetable.copy()
            self.repaired_children += 1
        return child

    def mutate(self, timetable):
        """Each gene is moved with probability mutation_rate. A move that makes the timetable
        worse is undone most of the time (guided mutation), a few are kept for diversity."""
        for m in self.problem.meetings:
            if self.rng.random() < self.mutation_rate:
                change = move_meeting(timetable, m, self.rng, tries=10)
                if change and move_delta(timetable, change, self.tracker) > 0 and self.rng.random() > 0.1:
                    undo(timetable, change)
        return timetable

    # ---------- main loop ----------
    def run(self):
        started = time.time()
        population = self.initial_population()
        best = min(population, key=lambda c: c.cost)
        best = Chromosome(best.timetable.copy(), self.tracker)
        no_improvement = 0
        generation = 0
        for generation in range(1, self.generations + 1):
            population.sort(key=lambda c: c.cost)
            next_population = [Chromosome(c.timetable.copy(), self.tracker) for c in population[:self.elitism]]
            while len(next_population) < self.population_size:
                p1, p2 = self.select(population), self.select(population)
                child = self.crossover(p1, p2) if self.rng.random() < 0.9 else p1.timetable.copy()
                child = self.mutate(child)
                next_population.append(Chromosome(child, self.tracker))
            population = next_population
            leader = min(population, key=lambda c: c.cost)
            if leader.cost < best.cost:
                best = Chromosome(leader.timetable.copy(), self.tracker)
                no_improvement = 0
            else:
                no_improvement += 1
            self.history.append(best.cost)
            self.average_history.append(sum(c.cost for c in population) / len(population))
            if no_improvement >= self.patience or time.time() - started > self.time_limit:
                break
        self.generations_run = generation
        self.run_time = time.time() - started
        # the final answer must be valid; operators guarantee it, this is a last safety check
        if count_hard(self.problem, best.timetable.assignment) > 0:
            raise RuntimeError('Genetic algorithm produced an invalid timetable')
        return best.timetable
