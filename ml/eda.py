"""Step 1: Data Cleaning & Exploratory Data Analysis (EDA) across data/extracted/ and data/created/."""
import os
import pandas as pd

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DATA_DIR = os.path.join(PROJECT_DIR, 'data')


def _find_file(data_dir, subfolder, filename):
    """Searches <data_dir>/<subfolder>/<filename>, <data_dir>/<filename>, and parent dir."""
    candidates = [
        os.path.join(data_dir, subfolder, filename),
        os.path.join(data_dir, filename),
        os.path.join(os.path.dirname(data_dir), subfolder, filename),
        os.path.join(os.path.dirname(data_dir), filename),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path
    raise FileNotFoundError(f"Could not find {filename}. Checked:\n  " + "\n  ".join(candidates))


def load_and_clean_all(data_dir=DEFAULT_DATA_DIR):
    """Loads and cleans all extracted and created CSVs into normalized DataFrames."""
    # --- Extracted tables ---
    offerings = pd.read_csv(_find_file(data_dir, 'extracted', 'course_offerings.csv'))
    rooms = pd.read_csv(_find_file(data_dir, 'extracted', 'rooms.csv'))
    sections = pd.read_csv(_find_file(data_dir, 'extracted', 'sections.csv'))
    teachers = pd.read_csv(_find_file(data_dir, 'extracted', 'teachers.csv'))
    selected_meetings = pd.read_csv(_find_file(data_dir, 'extracted', 'fall2024_selected_meetings.csv'))
    fixed_meetings = pd.read_csv(_find_file(data_dir, 'extracted', 'fall2024_other_batches_fixed.csv'))
    reservations = pd.read_csv(_find_file(data_dir, 'extracted', 'room_reservations.csv'))
    reserved_days = pd.read_csv(_find_file(data_dir, 'extracted', 'batch_reserved_days.csv'))

    # --- Created tables ---
    history = pd.read_csv(_find_file(data_dir, 'created', 'enrollment_history_synthetic.csv'))
    section_enroll = pd.read_csv(_find_file(data_dir, 'created', 'section_enrollment.csv'))
    room_assumptions = pd.read_csv(_find_file(data_dir, 'created', 'room_capacity_assumptions.csv'))
    faculty_constraints = pd.read_csv(_find_file(data_dir, 'created', 'faculty_constraints.csv'))
    section_days_off = pd.read_csv(_find_file(data_dir, 'created', 'section_days_off.csv'))
    special_rooms = pd.read_csv(_find_file(data_dir, 'created', 'special_room_requirements.csv'))

    # 1. Clean rooms using room_capacity_assumptions.csv
    assumption_map = dict(zip(room_assumptions['room'], room_assumptions['capacity']))
    rooms['capacity_was_missing'] = rooms['capacity'].isna()
    rooms['capacity'] = rooms.apply(
        lambda r: assumption_map.get(r['room'], 50) if pd.isna(r['capacity']) else r['capacity'],
        axis=1
    ).astype(int)

    # 2. Clean text nulls in faculty_constraints, reserved_days, and fixed_meetings
    faculty_constraints = faculty_constraints.fillna('')
    reserved_days['reserved_days'] = reserved_days['reserved_days'].fillna('')
    sections['reserved_days'] = sections['reserved_days'].fillna('')
    fixed_meetings['course'] = fixed_meetings['course'].fillna('UNKNOWN')

    # 3. Merge section_enrollment into sections
    sections = sections.merge(
        section_enroll[['section', 'estimated_enrollment', 'upper_bound_from_rooms']],
        on='section', how='left'
    )

    # 4. Feature engineering on offerings & enrollment history
    offerings['is_elective_flag'] = (offerings['is_elective'].str.lower() == 'yes').astype(int)
    offerings['total_weekly_slots'] = offerings['meetings_per_week'] * offerings['slots_per_meeting']
    offerings['num_sections'] = offerings['sections'].apply(
        lambda s: len([x for x in str(s).split(';') if x.strip()])
    )

    history['is_elective_flag'] = (history['elective'].str.lower() == 'yes').astype(int)
    history['section_size'] = (history['enrollment'] / history['sections_offered']).round(2)

    teachers['total_slots'] = teachers['selected_batch_slots'] + teachers['other_batch_slots']

    return {
        'offerings': offerings,
        'rooms': rooms,
        'sections': sections,
        'teachers': teachers,
        'selected_meetings': selected_meetings,
        'fixed_meetings': fixed_meetings,
        'reservations': reservations,
        'reserved_days': reserved_days,
        'history': history,
        'faculty_constraints': faculty_constraints,
        'section_days_off': section_days_off,
        'special_rooms': special_rooms,
    }


def summarize_eda(data):
    """Generates KPI metrics and summary DataFrames for EDA."""
    off = data['offerings']
    rooms = data['rooms']
    sections = data['sections']
    history = data['history']

    kpis = {
        'sections': len(sections),
        'offerings': len(off),
        'weekly_meetings': int(off['meetings_per_week'].sum()),
        'total_slot_hours': int(off['total_weekly_slots'].sum()),
        'rooms': len(rooms),
        'imputed_rooms': int(rooms['capacity_was_missing'].sum()),
        'teachers': len(data['teachers']),
        'history_records': len(history),
        'avg_section_enrollment_2024': round(sections['estimated_enrollment'].mean(), 1),
    }

    tables = {
        'term_enrollment_trend': history.groupby(['term_index', 'term'], as_index=False).agg(
            courses=('course', 'count'),
            total_enrollment=('enrollment', 'sum'),
            avg_course_enrollment=('enrollment', 'mean'),
            avg_section_size=('section_size', 'mean')
        ).round(2),
        'slots_by_program_type': pd.crosstab(
            off['program'], off['type'],
            values=off['total_weekly_slots'], aggfunc='sum', margins=True
        ).fillna(0).astype(int),
        'section_enrollment_by_program': sections.groupby(['program', 'semester']).agg(
            sections=('section', 'count'),
            avg_est_students=('estimated_enrollment', 'mean'),
            max_est_students=('estimated_enrollment', 'max'),
            avg_weekly_slots=('weekly_slots', 'mean')
        ).round(1),
        'room_capacity_summary': rooms.groupby('kind')['capacity'].agg(
            ['count', 'mean', 'median', 'min', 'max']
        ).round(1),
    }
    return kpis, tables


if __name__ == '__main__':
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    clean_data = load_and_clean_all()
    kpis, summary_tables = summarize_eda(clean_data)

    print("=" * 70)
    print("1. OVERALL EDA KPIs")
    print("=" * 70)
    for k, v in kpis.items():
        print(f"  {k:<32}: {v}")

    print("\n" + "=" * 70)
    print("2. SUMMARY STATISTICS TABLES")
    print("=" * 70)
    for name, table in summary_tables.items():
        print(f"\n--- {name.upper()} ---")
        print(table.to_string())

    print("\n" + "=" * 70)
    print("3. CLEANED DATASETS OVERVIEW (SHAPES, NULLS & SAMPLE ROWS)")
    print("=" * 70)
    for name, df in clean_data.items():
        null_count = int(df.isnull().sum().sum())
        print(f"\n--- {name.upper()} | Shape: {df.shape} | Remaining Nulls: {null_count} ---")
        print(df.head(5).to_string(index=False))