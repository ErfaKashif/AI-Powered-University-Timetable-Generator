# Data used by the Timetable Generator

Source: FAST-NUCES Karachi, **Fall 2024** BS timetable (one CSV per weekday + reserved days + City Campus).

## Selected batches
| Semester | Batch | Programs | Sections |
|---|---|---|---|
| 5th | 2022 | BCS, BSE, BAI, BCY, BEE, BBA | 23 |
| 7th | 2021 | BCS, BSE, BAI, BCY, BEE | 16 |

BDS has no 5th/7th semester yet (first intake 2024). BFT only has 1st and 3rd semester.
These 39 sections have 209 course offerings: 536 weekly meetings, 493 lectures of one slot each and 43 three-slot labs, so 622 slot-hours in total.

## `raw/` — original files, renamed only, never edited

## `extracted/` — REAL data, produced by the extractor from `raw/`
| File | Content |
|---|---|
| fall2024_selected_meetings.csv | The real Fall 2024 schedule for the selected batches (used as a reference / baseline) |
| course_offerings.csv | What must be scheduled: section(s), course, teacher, lecture/lab, meetings per week, elective flag |
| fall2024_other_batches_fixed.csv | 1st/3rd semester classes. Kept fixed: they block their teacher and room |
| room_reservations.csv | Cells such as "Reserved for PROCOM" / "NU Fest". Room is blocked |
| rooms.csv | 62 rooms with capacity and classroom/lab type |
| sections.csv | 39 sections, weekly load, reserved (off) days |
| batch_reserved_days.csv | Reserved day per batch from the official sheet |
| teachers.csv | 99 teachers of the selected batches with their load |
| timeslots.csv | Mon–Thu 8 × 55 min slots; Friday 9 × 50 min slots with a Jumma break |

The elective flag is derived from the data. A course is core when it is offered to every section of its program and semester. Otherwise it is an elective, and electives may run in parallel with each other.

## `created/` — NOT in the university data; assumptions you can edit
| File | How it was created |
|---|---|
| faculty_constraints.csv | Day off = a weekday the teacher did not teach in Fall 2024. Preferred days = days taught. 6 teachers marked *visiting* (lectures only, ≤2 days, no other batches). 8 teachers (seed 42) given fixed days = their real days |
| special_room_requirements.csv | EE labs → EE labs (real pattern); BBA lectures → B-9; FSPM BSE-7A+B → S2 (real); CV labs → AI/ML LAB-9 (assumed HoD request) |
| room_capacity_assumptions.csv | 4 EE labs have no capacity printed. 50 is assumed |
| section_enrollment.csv | No enrollment figures exist. Estimate = smallest room the section fitted in, × 0.82–1.0 |
| enrollment_history_synthetic.csv | **Synthetic.** No past enrollment exists. It is used only to demonstrate the regression pipeline |

`teacher_aliases.csv` / `course_aliases.csv` merge spelling variants found in the sheet (e.g. "Zain Noreen" → "Zain Noureen").
