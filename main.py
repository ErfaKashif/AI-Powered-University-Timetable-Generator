"""University Timetable Generator - command line.

Examples:
    python main.py                       # generate the Semester 5 + 7 timetable with CSP
    python main.py --algorithm ga        # CSP first, then improve it with the genetic algorithm
    python main.py --semesters 7         # only Semester 7
    python main.py --extract             # rebuild data/extracted from data/raw
"""
import argparse
import os
import sys
import time

from ml.pipeline import apply_ml_to_problem, run_ml_pipeline
from algorithms.csp import CSPSolver
from utils.constraints import find_violations, soft_breakdown, soft_cost, room_utilization
from utils.export import export_timetable
from utils.loader import DataError, check_input, load_problem

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(PROJECT_DIR, 'data')
OUTPUT_DIR = os.path.join(PROJECT_DIR, 'output')


def generate(problem, attempts=5, time_limit=60, log=print):
    """Runs backtracking + MRV + forward checking. Each attempt uses a different seed.
    Returns (timetable or None, list of solver objects)."""
    solvers = []
    for seed in range(attempts):
        solver = CSPSolver(problem, time_limit=time_limit, seed=seed)
        timetable = solver.solve()
        solvers.append(solver)
        st = solver.stats()
        log(f'  attempt {seed + 1}: {st["status"]} in {st["time_s"]} s '
            f'(backtracks {st["backtracks"]}, restarts {st["restarts"]})')
        if timetable is not None:
            return timetable, solvers
    return None, solvers


def explain_failure(problem, solvers):
    """Lists the meetings the search could not place and what they need."""
    lines = ['No valid timetable was found. The meetings that failed most often were:']
    counts = {}
    for s in solvers:
        for mid, n in s.fail_count.items():
            counts[mid] = counts.get(mid, 0) + n
    for mid, n in sorted(counts.items(), key=lambda kv: -kv[1])[:8]:
        m = problem.meeting_by_id[mid]
        o = m.offering
        lines.append(f'  {mid}: teacher {o.teacher.name} (allowed days {sorted(o.teacher.allowed_days())}), '
                     f'sections {o.section_names} (days off {sorted(set().union(*[s.days_off for s in o.sections]))}), '
                     f'{len(problem.times_ok[mid])} possible times, {len(problem.rooms_ok[mid])} possible rooms')
    sections = {}
    for mid in list(counts)[:20]:
        for sec in problem.meeting_by_id[mid].offering.sections:
            sections[sec.name] = sec
    for sec in sections.values():
        load = sum(m.length for m in problem.meetings
                   if not m.offering.is_elective and sec in m.offering.sections)
        days = [d for d in problem.grid.day_slots if d not in sec.days_off]
        lines.append(f'  section {sec.name}: needs {load} slots on {len(days)} days {days}; '
                     f'with the 3-hour break rule a day holds at most 6 slots (8 on Friday)')
    lines.append('Relax one of these requirements (days off, fixed days, special rooms) and run again.')
    return '\n'.join(lines)


def print_summary(summary):
    print('\n' + '=' * 60)
    print(' TIMETABLE SUMMARY')
    print('=' * 60)
    for key, value in summary.items():
        print(f' {key:<38} {value}')
    print('=' * 60)


def run_generate(args):
    started = time.time()
    print(f'Loading data for semester(s) {args.semesters} ...')
    problem = load_problem(DATA_DIR, semesters=args.semesters)
    ml_out = run_ml_pipeline(DATA_DIR)
    adjusted = apply_ml_to_problem(problem, ml_out)
    print(f'  ML pipeline applied: tightened room capacities on {adjusted} meetings using Regression/DT & K-Means')
    print(f'  {len(problem.sections)} sections, {len(problem.offerings)} course offerings, '
          f'{len(problem.meetings)} weekly meetings, {len(problem.teachers)} teachers, {len(problem.rooms)} rooms')
    issues = check_input(problem)
    if issues:
        print('The input makes a valid timetable impossible:')
        for issue in issues:
            print('  -', issue)
        return 1

    print('Running CSP (backtracking + MRV + forward checking) ...')
    timetable, solvers = generate(problem, attempts=args.attempts, time_limit=args.time_limit)
    if timetable is None:
        print(explain_failure(problem, solvers))
        return 1
    csp_cost = soft_cost(problem, timetable.assignment)
    method = 'CSP: ' + solvers[-1].status

    if args.algorithm == 'ga':
        from algorithms.genetic import GeneticAlgorithm
        print('Improving soft constraints with the genetic algorithm ...')
        ga = GeneticAlgorithm(timetable, population_size=args.population, generations=args.generations, seed=1)
        timetable = ga.run()
        method += f' + genetic algorithm ({ga.generations_run} generations)'

    assignment = timetable.assignment
    violations = find_violations(problem, assignment)
    hard = sum(len(v) for v in violations.values())
    soft = soft_breakdown(problem, assignment)
    unscheduled = [m.id for m in problem.meetings if m.id not in assignment]
    summary = {
        'Instance': problem.name,
        'Method': method,
        'Total classes required (meetings)': len(problem.meetings),
        'Classes scheduled': len(assignment),
        'Unscheduled classes': len(unscheduled),
        'Teaching slots scheduled': sum(problem.meeting_by_id[m].length for m in assignment),
        'Hard constraint violations': hard,
        'Soft cost (CSP solution)': csp_cost,
        'Soft cost (final)': soft_cost(problem, assignment),
        'Soft violations: long gaps (slots)': soft['gaps'],
        'Soft violations: late classes': soft['late'],
        'Soft violations: overloaded days': soft['overload'],
        'Soft violations: not on preferred day': soft['pref_day'],
        'Soft violations: not in preferred slots': soft['pref_slot'],
        'Soft violations: unbalanced days': soft['balance'],
        'Soft violations: room waste (per 5 seats)': soft['room_waste'],
        'Soft violations: single-class days': soft['single_class_day'],
        'Soft violations: course twice a day': soft['same_day'],
        'Average seat utilization (%)': round(room_utilization(problem, assignment), 1),
        'Execution time (s)': round(time.time() - started, 1),
    }
    if hard:
        print('ERROR: the timetable breaks hard constraints - it is NOT saved as final.')
        for name, msgs in violations.items():
            for msg in msgs[:5]:
                print(f'  [{name}] {msg}')
        return 1
    prefix = 'timetable_sem' + '_'.join(str(s) for s in args.semesters)
    xlsx, csv_path, _ = export_timetable(problem, assignment, OUTPUT_DIR, summary, prefix)
    summary['Excel file'] = os.path.relpath(xlsx, PROJECT_DIR)
    summary['CSV file'] = os.path.relpath(csv_path, PROJECT_DIR)
    print_summary(summary)
    return 0


def main():
    parser = argparse.ArgumentParser(description='University Timetable Generator (CSP + Genetic Algorithm)')
    parser.add_argument('--semesters', type=int, nargs='+', default=[5, 7])
    parser.add_argument('--algorithm', choices=['csp', 'ga'], default='csp')
    parser.add_argument('--attempts', type=int, default=5, help='CSP attempts with different seeds')
    parser.add_argument('--time-limit', type=int, default=60, help='seconds per CSP attempt')
    parser.add_argument('--population', type=int, default=30)
    parser.add_argument('--generations', type=int, default=100)
    parser.add_argument('--extract', action='store_true', help='rebuild data/extracted from data/raw')
    parser.add_argument('--make-assumptions', action='store_true',
                        help='recreate data/created (OVERWRITES your edits)')
    args = parser.parse_args()
    try:
        if args.extract:
            from utils import preprocess
            preprocess.run(PROJECT_DIR)
            return 0
        if args.make_assumptions:
            from utils import assumptions
            assumptions.run(PROJECT_DIR)
            return 0
        return run_generate(args)
    except DataError as error:
        print('Data error:', error)
        return 1


if __name__ == '__main__':
    sys.exit(main())
