# University Timetable Generator
**CSP (backtracking + MRV + forward checking) and a Genetic Algorithm for conflict-free weekly scheduling**
AI-2002 Artificial Intelligence project. Data: FAST-NUCES Karachi, Fall 2024 timetable, **Semester 5 and Semester 7** (all programs: BCS, BSE, BAI, BCY, BEE, BBA).

---

## How to run after downloading the ZIP (Windows)

### Step 1 – Install Python (only once)
Download Python 3.10+ from https://www.python.org/downloads/ and, during setup, **tick "Add python.exe to PATH"**.

### Step 2 – Unzip
Right-click the ZIP and choose **Extract All…**. Open the extracted `university_timetable_generator` folder (the one containing `app.py`).

### Step 3 – Start the app (EASIEST)
**Double-click `run_app.bat`.**
- The first time, it installs the libraries (a few minutes).
- Your browser then opens at **http://localhost:8501** with the user interface.
- Keep the black window open while using the app. Closing it stops the app.

Using the app:
1. **4. Generate timetable**: press **Generate** (about 10–60 s).
2. **5. View timetable**: section-, faculty- and room-wise timetables.
3. **6. Conflicts & validation**: every hard constraint with its violation count (should be 0).
4. **7. Compare algorithms**: CSP vs GA vs hill climbing vs simulated annealing vs random/greedy.
5. **2. Faculty settings / 3. Batch days off & rooms**: change preferred days, fixed days, day off, visiting hours, section days off and special rooms. Then generate again.
6. Press **Download Excel / Download CSV** to export.

Double-click **`run_generator.bat`** instead to generate without the UI. It opens the Excel result when done.

### Same thing from the VS Code terminal
Open the folder in VS Code (**File → Open Folder**), then **Terminal → New Terminal**:
```
pip install -r requirements.txt
streamlit run app.py
```
or, for the command line only:
```
python main.py
```
If `pip`/`streamlit` is "not recognized", use `python -m pip install -r requirements.txt` and `python -m streamlit run app.py`
(or replace `python` with `py`). **A virtual environment is NOT required.**

Optional virtual environment:
- PowerShell: `python -m venv venv`, then `.\venv\Scripts\Activate.ps1`
  (if blocked: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`)
- Command Prompt: `venv\Scripts\activate.bat`

### Output
Everything is saved in the `output` folder:
| File | Content |
|---|---|
| `timetable_sem5_7.xlsx` | Sheets: Summary, Master timetable, Section timetables, Electives, Faculty timetables, Room timetables, Validation report |
| `timetable_sem5_7_master.csv` | Every class: day, time, course, sections, teacher, room |
| `timetable_sem5_7_validation.csv` | Result of every hard and soft constraint check |
| `algorithm_comparison.csv` | Written by the "Compare algorithms" page |

Close the Excel file before generating again, otherwise Windows cannot overwrite it.

---

## Other commands
| Command | What it does |
|---|---|
| `python main.py --algorithm ga` | CSP first, then the genetic algorithm improves soft constraints |
| `python main.py --algorithm ga --generations 50 --population 20` | Shorter or longer GA run |
| `python main.py --semesters 7` | Only Semester 7 |
| `python main.py --semesters 5` | Only Semester 5 |
| `python main.py --attempts 8 --time-limit 90` | More / longer CSP attempts |
| `python main.py --extract` | Rebuild `data/extracted` from the original CSVs in `data/raw` |
| `python main.py --make-assumptions` | Recreate `data/created` (**overwrites your edits**) |

## Changing constraints
Edit the CSV files in `data/created/` (Excel or any text editor), then run `python main.py` again.
| File | Columns |
|---|---|
| `faculty_constraints.csv` | `faculty_type` (permanent/visiting), `available_days`, `available_slots` (e.g. `1-4`), `fixed_days`, `day_off`, `preferred_days`, `preferred_slots`. Days are written like `MON;TUE;WED` |
| `section_days_off.csv` | Day(s) off per section, e.g. `FRIDAY` or `MONDAY;FRIDAY` |
| `special_room_requirements.csv` | `offering_id` → `required_rooms` (separated by `;`) |
| `section_enrollment.csv` | Estimated students per section (used for room capacity) |

If the constraints make a timetable impossible, the program does **not** produce a fake result. It prints the meetings and sections that cannot be placed, and why.

## Hard constraints (never broken in the output)
Faculty clash, room clash, section clash (electives may not overlap core classes of their batch), room capacity, faculty availability (classes of other batches stay fixed), visiting faculty days/hours, fixed faculty days, faculty day off, batch day off, break after 3 continuous hours (measured in minutes; the Friday Jumma break counts as a break), special rooms, all weekly meetings scheduled, labs in labs (3 consecutive slots), lectures in classrooms, valid time slots, at most 2 meetings of a course per day.

## Soft constraints (penalty, minimized)
Long gaps, late classes, overloaded days, teacher preferred days and slots, unbalanced week, wasted room seats, single-class days, the same course twice in a day.

## Project structure
```
app.py                    Streamlit user interface (run_app.bat starts it)
main.py                   command-line program (run_generator.bat runs it)
experiments.py            algorithm comparison
models/entities.py        Room, Teacher, Section, Offering, Meeting, TimeGrid, Problem, Timetable
algorithms/csp.py         backtracking + MRV + degree tie-break + forward checking (+ restarts)
algorithms/repair.py      min-conflicts repair (finishes a stuck search, repairs GA children)
algorithms/genetic.py     genetic algorithm (tournament selection, crossover, mutation, elitism)
algorithms/local_search.py  hill climbing, simulated annealing
algorithms/baselines.py   random and greedy schedulers
algorithms/moves.py       valid moves/swaps used by the optimizers
utils/preprocess.py       reads the original timetable CSVs -> data/extracted
utils/assumptions.py      creates the editable inputs in data/created
utils/loader.py           loads data, checks the input
utils/constraints.py      hard-constraint validator + soft cost
utils/export.py           Excel / CSV export
data/raw                  original university files (never modified)
data/extracted            real data taken from the timetable
data/created              assumptions (see data/DATA_README.md)
output/                   generated timetables
```

## Status
Working: data extraction, CSP generation, GA / hill climbing / simulated annealing, validation,
Excel/CSV export, Streamlit interface, algorithm comparison, basic data-analysis charts.
Still to be added: enrollment prediction (regression), k-means clustering, unit tests.

## Troubleshooting
| Problem | Fix |
|---|---|
| `'python' is not recognized` | Reinstall Python with "Add to PATH", or use `py main.py` |
| `ModuleNotFoundError` | Run `python -m pip install -r requirements.txt` |
| `venv\Scripts\activate` does nothing / is blocked | You do not need it. Skip it, or see "Optional virtual environment" above |
| Browser does not open | Open http://localhost:8501 yourself |
| `PermissionError` on the .xlsx | Close the Excel file and run again |
| Run says "time limit reached" | Run again, or use `--attempts 8 --time-limit 90` |
