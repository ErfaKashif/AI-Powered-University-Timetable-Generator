"""Runs several scheduling algorithms on the same problem and compares them."""
import time

from algorithms.baselines import GreedyScheduler, RandomScheduler
from algorithms.genetic import GeneticAlgorithm
from algorithms.local_search import HillClimbing, SimulatedAnnealing
from utils.constraints import count_hard, room_utilization, soft_cost


def result_row(problem, name, assignment, seconds, note=''):
    hard = count_hard(problem, assignment)
    return {'algorithm': name,
            'scheduled': len(assignment),
            'unscheduled': len(problem.meetings) - len(assignment),
            'hard_violations': hard,
            'soft_cost': soft_cost(problem, assignment),
            'valid': 'yes' if hard == 0 else 'no',
            'time_s': round(seconds, 2),
            'seat_utilization_%': round(room_utilization(problem, assignment), 1),
            'note': note}


def compare_algorithms(problem, csp_timetable, csp_seconds, seed=1, ga_generations=40, ga_population=20,
                       iterations=20000, log=print):
    """csp_timetable is a valid CSP solution. HC, SA and GA start from it."""
    rows, curves = [], {}

    log('Random baseline ...')
    rnd = RandomScheduler(problem, seed)
    rows.append(result_row(problem, 'Random', rnd.solve(), rnd.run_time, 'random value for every class'))

    log('Greedy baseline ...')
    greedy = GreedyScheduler(problem)
    assignment = greedy.solve()
    rows.append(result_row(problem, 'Greedy first-fit', assignment, greedy.run_time, 'no backtracking'))

    rows.append(result_row(problem, 'CSP (MRV + FC)', csp_timetable.assignment, csp_seconds,
                           'backtracking + MRV + forward checking'))

    log('Hill climbing ...')
    hc = HillClimbing(csp_timetable, max_iterations=iterations, seed=seed)
    tt = hc.run()
    rows.append(result_row(problem, 'CSP + Hill climbing', tt.assignment, csp_seconds + hc.run_time,
                           f'{hc.iterations} iterations'))
    curves['Hill climbing'] = hc.history

    log('Simulated annealing ...')
    sa = SimulatedAnnealing(csp_timetable, max_iterations=iterations, seed=seed)
    tt = sa.run()
    rows.append(result_row(problem, 'CSP + Simulated annealing', tt.assignment, csp_seconds + sa.run_time,
                           f'{sa.iterations} iterations'))
    curves['Simulated annealing'] = sa.history

    log('Genetic algorithm ...')
    started = time.time()
    ga = GeneticAlgorithm(csp_timetable, population_size=ga_population, generations=ga_generations, seed=seed)
    tt = ga.run()
    rows.append(result_row(problem, 'CSP + Genetic algorithm', tt.assignment, csp_seconds + time.time() - started,
                           f'{ga.generations_run} generations, population {ga_population}'))
    curves['Genetic algorithm (per generation)'] = ga.history
    return rows, curves
