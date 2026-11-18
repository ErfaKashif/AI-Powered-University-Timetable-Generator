"""Streamlit interface of the University Timetable Generator.

Run with:   streamlit run app.py
"""
import os
import time

import pandas as pd
import streamlit as st

from main import DATA_DIR, OUTPUT_DIR, explain_failure, generate
from models.entities import DAYS
from utils.constraints import (DEFAULT_WEIGHTS, find_violations, room_utilization, soft_breakdown, soft_cost)
from utils.export import export_timetable, grid_for, master_rows, slot_times_frame
from utils.loader import DataError, check_input, load_problem

CREATED = os.path.join(DATA_DIR, 'created')
EXTRACTED = os.path.join(DATA_DIR, 'extracted')
FACULTY_FILE = os.path.join(CREATED, 'faculty_constraints.csv')
DAYS_OFF_FILE = os.path.join(CREATED, 'section_days_off.csv')
ROOMS_REQ_FILE = os.path.join(CREATED, 'special_room_requirements.csv')
FULL_DAY = {'MON': 'MONDAY', 'TUE': 'TUESDAY', 'WED': 'WEDNESDAY', 'THU': 'THURSDAY', 'FRI': 'FRIDAY'}

st.set_page_config(page_title='Timetable Generator', page_icon='📅', layout='wide')


# ---------------- helpers ----------------
def read_csv(path):
    return pd.read_csv(path, dtype=str).fillna('')


def save_csv(frame, path):
    frame.to_csv(path, index=False)
    st.success(f'Saved {os.path.basename(path)}. Generate the timetable again to use the change.')


def days_list(text):
    return [d.strip()[:3].upper() for d in str(text).split(';') if d.strip()]


def load(semesters):
    try:
        return load_problem(DATA_DIR, semesters=semesters), None
    except DataError as error:
        return None, str(error)


def result():
    return st.session_state.get('result')


# ---------------- pages ----------------
def page_data():
    st.header('University data')
    st.caption('FAST-NUCES Karachi, Fall 2024 timetable. Selected batches: Semester 5 (batch 2022) '
               'and Semester 7 (batch 2021), all programs.')
    problem, error = load([5, 7])
    if error:
        st.error(error)
        return
    c = st.columns(5)
    c[0].metric('Sections', len(problem.sections))
    c[1].metric('Course offerings', len(problem.offerings))
    c[2].metric('Weekly classes', len(problem.meetings))
    c[3].metric('Faculty', len(problem.teachers))
    c[4].metric('Rooms', len(problem.rooms))

    issues = check_input(problem)
    if issues:
        st.error('Input problems that make a timetable impossible:')
        for i in issues:
            st.write('-', i)
    else:
        st.success('Input check passed: every class has at least one allowed time and room.')

    tabs = st.tabs(['Faculty', 'Rooms', 'Sections', 'Courses'])
    with tabs[0]:
        st.dataframe(read_csv(FACULTY_FILE), use_container_width=True, hide_index=True)
    with tabs[1]:
        rooms = pd.DataFrame([{'room': r.name, 'capacity': r.capacity, 'kind': r.kind,
                               'electrical lab': 'yes' if r.is_ee_lab else ''} for r in problem.rooms])
        st.dataframe(rooms, use_container_width=True, hide_index=True)
    with tabs[2]:
        st.dataframe(pd.DataFrame([{'section': s.name, 'program': s.program, 'semester': s.semester,
                                    'days off': ', '.join(sorted(s.days_off)), 'students': s.enrollment}
                                   for s in problem.sections]), use_container_width=True, hide_index=True)
    with tabs[3]:
        st.dataframe(read_csv(os.path.join(EXTRACTED, 'course_offerings.csv')), use_container_width=True,
                     hide_index=True)


def page_faculty():
    st.header('Faculty availability and preferences')
    frame = read_csv(FACULTY_FILE)
    teacher = st.selectbox('Teacher', frame['teacher'].tolist())
    row = frame[frame['teacher'] == teacher].iloc[0]
    with st.form('teacher_form'):
        kind = st.radio('Faculty type', ['permanent', 'visiting'], horizontal=True,
                        index=1 if row['faculty_type'] == 'visiting' else 0)
        col1, col2 = st.columns(2)
        preferred = col1.multiselect('Preferred days (soft)', DAYS, days_list(row['preferred_days']))
        fixed = col1.multiselect('Fixed working days (hard, empty = any day)', DAYS, days_list(row['fixed_days']))
        day_off = col1.selectbox('Day off (hard)', [''] + DAYS,
                                 index=([''] + DAYS).index(row['day_off']) if row['day_off'] in DAYS else 0)
        available = col2.multiselect('Visiting faculty: available days (hard)', DAYS,
                                     days_list(row['available_days']))
        slots = col2.text_input('Visiting faculty: available slots (hard), e.g. 1-4', row['available_slots'])
        pref_slots = col2.text_input('Preferred slots (soft), e.g. 1-4 or 5-8', row['preferred_slots'])
        if st.form_submit_button('Save teacher'):
            if day_off and day_off in fixed:
                st.error('The day off cannot also be a fixed working day.')
            else:
                i = frame.index[frame['teacher'] == teacher][0]
                frame.loc[i, ['faculty_type', 'preferred_days', 'fixed_days', 'day_off', 'available_days',
                              'available_slots', 'preferred_slots']] = [
                    kind, ';'.join(preferred), ';'.join(fixed), day_off, ';'.join(available), slots, pref_slots]
                save_csv(frame, FACULTY_FILE)
    st.subheader('All faculty (you can also edit the table directly)')
    edited = st.data_editor(frame, use_container_width=True, hide_index=True, key='faculty_table')
    if st.button('Save table'):
        save_csv(edited, FACULTY_FILE)


def page_batches_rooms():
    st.header('Batch days off and special room requirements')
    st.subheader('Section days off (hard)')
    st.caption('Write full day names separated by ";" e.g. MONDAY;FRIDAY')
    days_off = st.data_editor(read_csv(DAYS_OFF_FILE), use_container_width=True, hide_index=True, key='days_off')
    if st.button('Save days off'):
        save_csv(days_off, DAYS_OFF_FILE)

    st.subheader('Special room requirements (hard)')
    st.caption('offering_id from the Courses table; required_rooms separated by ";". Add rows at the bottom.')
    rooms = st.data_editor(read_csv(ROOMS_REQ_FILE), use_container_width=True, hide_index=True,
                           num_rows='dynamic', key='room_req')
    if st.button('Save room requirements'):
        save_csv(rooms, ROOMS_REQ_FILE)


def page_generate():
    st.header('Generate timetable')
    col1, col2, col3 = st.columns(3)
    semesters = col1.multiselect('Semesters', [5, 7], [5, 7])
    algorithm = col2.selectbox('Algorithm', ['CSP (backtracking + MRV + forward checking)',
                                             'CSP + Genetic algorithm', 'CSP + Hill climbing',
                                             'CSP + Simulated annealing'])
    attempts = col3.number_input('CSP attempts', 1, 10, 5)
    time_limit = col3.number_input('Seconds per attempt', 20, 300, 60)
    if 'Genetic' in algorithm:
        g1, g2 = st.columns(2)
        generations = g1.slider('Generations', 10, 200, 40)
        population = g2.slider('Population size', 6, 60, 20)
    if not semesters:
        st.warning('Select at least one semester.')
        return
    if not st.button('Generate', type='primary'):
        show_summary()
        return

    problem, error = load(semesters)
    if error:
        st.error(error)
        return
    issues = check_input(problem)
    if issues:
        st.error('The input makes a valid timetable impossible:')
        for i in issues:
            st.write('-', i)
        return
    started = time.time()
    with st.status('Running CSP ...', expanded=True) as status:
        timetable, solvers = generate(problem, attempts=int(attempts), time_limit=int(time_limit), log=st.write)
        if timetable is None:
            status.update(label='No valid timetable found', state='error')
            st.error(explain_failure(problem, solvers))
            return
        csp_cost = soft_cost(problem, timetable.assignment)
        method = 'CSP: ' + solvers[-1].status
        if 'Genetic' in algorithm:
            from algorithms.genetic import GeneticAlgorithm
            st.write('Genetic algorithm ...')
            ga = GeneticAlgorithm(timetable, population_size=population, generations=generations, seed=1)
            timetable = ga.run()
            method += f' + GA ({ga.generations_run} generations)'
            st.session_state['curve'] = ga.history
        elif 'Hill' in algorithm:
            from algorithms.local_search import HillClimbing
            st.write('Hill climbing ...')
            hc = HillClimbing(timetable, seed=1)
            timetable = hc.run()
            method += ' + hill climbing'
            st.session_state['curve'] = hc.history
        elif 'Simulated' in algorithm:
            from algorithms.local_search import SimulatedAnnealing
            st.write('Simulated annealing ...')
            sa = SimulatedAnnealing(timetable, seed=1)
            timetable = sa.run()
            method += ' + simulated annealing'
            st.session_state['curve'] = sa.history
        else:
            st.session_state['curve'] = None
        status.update(label='Done', state='complete')

    assignment = timetable.assignment
    hard = sum(len(v) for v in find_violations(problem, assignment).values())
    if hard:
        st.error(f'{hard} hard constraint violations - the timetable is not accepted.')
        return
    summary = {'Instance': problem.name, 'Method': method,
               'Total classes required': len(problem.meetings), 'Classes scheduled': len(assignment),
               'Unscheduled classes': len(problem.meetings) - len(assignment),
               'Hard constraint violations': hard, 'Soft cost (CSP)': csp_cost,
               'Soft cost (final)': soft_cost(problem, assignment),
               'Average seat utilization (%)': round(room_utilization(problem, assignment), 1),
               'Execution time (s)': round(time.time() - started, 1)}
    prefix = 'timetable_sem' + '_'.join(str(s) for s in sorted(semesters))
    xlsx, csv_path, _ = export_timetable(problem, assignment, OUTPUT_DIR, summary, prefix)
    st.session_state['result'] = {'problem': problem, 'assignment': assignment, 'summary': summary,
                                  'xlsx': xlsx, 'csv': csv_path, 'timetable': timetable,
                                  'csp_seconds': solvers[-1].run_time}
    show_summary()


def show_summary():
    res = result()
    if not res:
        st.info('No timetable generated yet. Press Generate.')
        return
    s = res['summary']
    st.subheader('Result')
    c = st.columns(5)
    c[0].metric('Classes scheduled', f"{s['Classes scheduled']} / {s['Total classes required']}")
    c[1].metric('Unscheduled', s['Unscheduled classes'])
    c[2].metric('Hard violations', s['Hard constraint violations'])
    c[3].metric('Soft cost', s['Soft cost (final)'], s['Soft cost (final)'] - s['Soft cost (CSP)'],
                delta_color='inverse')
    c[4].metric('Time (s)', s['Execution time (s)'])
    st.caption(s['Method'])
    if st.session_state.get('curve'):
        st.line_chart(pd.DataFrame({'soft cost': st.session_state['curve']}))
    download_buttons()


def download_buttons():
    res = result()
    c = st.columns(2)
    with open(res['xlsx'], 'rb') as f:
        c[0].download_button('Download Excel', f.read(), os.path.basename(res['xlsx']))
    with open(res['csv'], 'rb') as f:
        c[1].download_button('Download CSV', f.read(), os.path.basename(res['csv']))


def page_view():
    st.header('View timetable')
    res = result()
    if not res:
        st.info('Generate a timetable first.')
        return
    problem, assignment = res['problem'], res['assignment']
    view = st.radio('View by', ['Section', 'Faculty', 'Room', 'Electives', 'Master list'], horizontal=True)
    with st.expander('Slot times (Friday has 50-minute slots and a Jumma break 1:00-1:40)'):
        st.dataframe(slot_times_frame(problem), hide_index=True, use_container_width=True)
    master = pd.DataFrame(master_rows(problem, assignment))
    if view == 'Section':
        name = st.selectbox('Section', sorted(s.name for s in problem.sections))
        st.dataframe(grid_for(problem, assignment, 'section', name), use_container_width=True)
        group = name[:name.rindex('-') + 2]
        electives = master[(master['elective'] == 'yes') & master['sections'].str.startswith(group)]
        if len(electives):
            st.caption(f'Electives offered to {group} students (shown separately)')
            st.dataframe(electives[['day', 'time', 'course', 'sections', 'teacher', 'room']], hide_index=True)
    elif view == 'Faculty':
        name = st.selectbox('Teacher', sorted(t.name for t in problem.teachers))
        st.dataframe(grid_for(problem, assignment, 'teacher', name), use_container_width=True)
    elif view == 'Room':
        name = st.selectbox('Room', sorted({v[2] for v in assignment.values()}))
        st.dataframe(grid_for(problem, assignment, 'room', name), use_container_width=True)
    elif view == 'Electives':
        st.dataframe(master[master['elective'] == 'yes'], hide_index=True, use_container_width=True)
    else:
        day = st.selectbox('Day', ['All'] + DAYS)
        st.dataframe(master if day == 'All' else master[master['day'] == day], hide_index=True,
                     use_container_width=True)
    download_buttons()


def page_conflicts():
    st.header('Constraint check and conflicts')
    res = result()
    if not res:
        st.info('Generate a timetable first.')
        return
    problem, assignment = res['problem'], res['assignment']
    violations = find_violations(problem, assignment)
    rows = [{'hard constraint': k, 'violations': len(v), 'status': 'OK' if not v else 'VIOLATED'}
            for k, v in violations.items()]
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    total = sum(len(v) for v in violations.values())
    if total == 0:
        st.success('No hard constraint is violated.')
    for name, messages in violations.items():
        for m in messages[:20]:
            st.error(f'{name}: {m}')
    st.subheader('Soft constraints')
    soft = soft_breakdown(problem, assignment)
    st.dataframe(pd.DataFrame([{'soft constraint': k, 'count': v, 'weight': DEFAULT_WEIGHTS.get(k, 0),
                                'penalty': v * DEFAULT_WEIGHTS.get(k, 0)} for k, v in soft.items()]),
                 hide_index=True, use_container_width=True)


def page_compare():
    st.header('Compare algorithms')
    res = result()
    if not res:
        st.info('Generate a timetable with CSP first. HC, SA and GA start from that CSP solution.')
        return
    c1, c2, c3 = st.columns(3)
    generations = c1.slider('GA generations', 10, 150, 40)
    population = c2.slider('GA population', 6, 40, 20)
    iterations = c3.slider('HC / SA iterations', 2000, 40000, 20000, step=2000)
    if st.button('Run comparison (takes about 1-3 minutes)', type='primary'):
        from experiments import compare_algorithms
        base = res['timetable']
        with st.status('Running algorithms ...', expanded=True):
            rows, curves = compare_algorithms(res['problem'], base, res['csp_seconds'], ga_generations=generations,
                                              ga_population=population, iterations=iterations, log=st.write)
        st.session_state['comparison'] = (rows, curves)
        pd.DataFrame(rows).to_csv(os.path.join(OUTPUT_DIR, 'algorithm_comparison.csv'), index=False)
    if 'comparison' in st.session_state:
        rows, curves = st.session_state['comparison']
        table = pd.DataFrame(rows)
        st.dataframe(table, hide_index=True, use_container_width=True)
        c = st.columns(3)
        c[0].caption('Hard violations')
        c[0].bar_chart(table.set_index('algorithm')['hard_violations'])
        c[1].caption('Soft cost (lower is better)')
        c[1].bar_chart(table.set_index('algorithm')['soft_cost'])
        c[2].caption('Time (s)')
        c[2].bar_chart(table.set_index('algorithm')['time_s'])
        st.caption('Convergence (best soft cost)')
        for name, values in curves.items():
            st.write(name)
            st.line_chart(pd.DataFrame({'soft cost': values}))


def page_eda():
    st.header('Data analysis')
    problem, error = load([5, 7])
    if error:
        st.error(error)
        return
    offerings = pd.DataFrame([{'program': o.sections[0].program, 'semester': o.sections[0].semester,
                               'course': o.course, 'type': o.kind, 'teacher': o.teacher.name,
                               'slots': o.meetings_per_week * o.length, 'elective': o.is_elective}
                              for o in problem.offerings])
    c = st.columns(2)
    c[0].caption('Weekly teaching slots per program')
    c[0].bar_chart(offerings.groupby('program')['slots'].sum())
    c[1].caption('Sections per program')
    c[1].bar_chart(pd.Series([s.program for s in problem.sections]).value_counts())
    c = st.columns(2)
    c[0].caption('Faculty workload (weekly slots, top 25)')
    c[0].bar_chart(offerings.groupby('teacher')['slots'].sum().sort_values(ascending=False).head(25))
    c[1].caption('Room capacities')
    c[1].bar_chart(pd.Series([r.capacity for r in problem.rooms]).value_counts().sort_index())
    c = st.columns(2)
    c[0].caption('Estimated students per section')
    c[0].bar_chart(pd.Series({s.name: s.enrollment for s in problem.sections}))
    c[1].caption('Faculty day off (availability pattern)')
    c[1].bar_chart(pd.Series([t.day_off or 'none' for t in problem.teachers]).value_counts())
    st.caption('Lectures vs labs')
    st.bar_chart(offerings.groupby(['program', 'type'])['slots'].sum().unstack().fillna(0))


PAGES = {'1. University data': page_data, '2. Faculty settings': page_faculty,
         '3. Batch days off & rooms': page_batches_rooms, '4. Generate timetable': page_generate,
         '5. View timetable': page_view, '6. Conflicts & validation': page_conflicts,
         '7. Compare algorithms': page_compare, '8. Data analysis': page_eda}

st.sidebar.title('Timetable Generator')
st.sidebar.caption('CSP + Genetic Algorithm\nFAST-NUCES Fall 2024, Semester 5 & 7')
choice = st.sidebar.radio('Go to', list(PAGES))
PAGES[choice]()
