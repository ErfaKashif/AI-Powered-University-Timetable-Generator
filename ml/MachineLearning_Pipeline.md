# Machine Learning Pipeline Documentation (`ML.README.md`)

**Project:** Automated University Timetable Generator (FAST-NUCES Karachi — Fall 2024, Semesters 5 & 7)  
**Scope:** 536 Weekly Class Meetings | 209 Course Offerings | 99 Faculty Members | 62 Classrooms & Labs

---

## 1. Overview & Purpose

Generating a conflict-free university timetable requires matching hundreds of lectures and 3-hour labs to specific teachers, student sections, time slots, and physical rooms without double-booking anyone or overcrowding a classroom.

To make the timetable generator smarter and more realistic, we built a **four-stage Machine Learning (ML) pipeline** (`ml/pipeline.py`) that learns from historical enrollment records (Fall 2021 – Fall 2024) and current course structures before the timetable solver starts scheduling classes.

### What the ML Pipeline Does in Plain Terms
1. **Cleans & Repairs Raw University Data (`ml/eda.py`):** Fixes formatting inconsistencies and fills in missing room capacities so the scheduler does not crash or ignore usable rooms.
2. **Forecasts Student Headcount (`ml/regression.py` & `ml/decision_tree.py`):** Predicts how many students will actually sit in each class section next semester, helping the scheduler pick rooms with enough seats.
3. **Identifies Scheduling Bottlenecks (`ml/clustering.py`):** Groups courses that share the same student batches and flags high-contention courses so the scheduler places the hardest classes first.
4. **Protects Physical Room Supply (`ml/pipeline.py`):** Combines predictions safely so standard classrooms and computer labs are not over-filtered, ensuring 100% of classes can still be scheduled.

---

## 2. How the Project Behaved *Before* the ML Pipeline

Before adding Machine Learning, the timetable solver relied strictly on **static rules and fixed assumptions**:

* **Fixed Headcount Assumptions:** Every section was treated as having a static, unchanging enrollment number. If a course grew from 42 students to 54 students over two years, the solver had no way to anticipate the growth and could place 54 students into a 50-seat classroom.
* **Blind Scheduling Order:** The solver treated all courses with similar schedules as equally easy or hard to place. It did not know which courses shared large overlapping student groups (such as core Semester 5 Computer Science courses or cross-program electives), often leading to late dead-ends during search.
* **Unrepaired Missing Room Data:** Several rooms and labs in the raw CSV files had missing seating capacities, requiring manual intervention or risking inaccurate room assignments.
* **No Predictive Analytics on the Website:** The web dashboard (`app.py`) could only show raw counts of current teachers, rooms, and schedules—it could not forecast future demand, warn about large-room shortages, or highlight clash-prone course groups.

---

## 3. Step-by-Step Breakdown of the ML Components

### Stage 1: Data Cleaning & Exploratory Data Analysis (`ml/eda.py`)
* **Purpose:** Prepare all 12 university data files (`extracted/` and `created/`) so every model and solver receives accurate, uniform data.
* **What It Does:**
  * Standardizes text formatting (removing extra spaces and inconsistent capitalization).
  * Fills in missing room seating capacities using institutional room assumptions (imputing capacities for 4 specialized rooms/labs).
  * Summarizes university workload: **34 student sections**, **209 course offerings**, **724 weekly slot-hours**, and **62 total rooms**.

---

### Stage 2: Enrollment Trend Forecasting — Linear Regression (`ml/regression.py`)
* **Purpose:** Capture steady, multi-year growth in student enrollment across departments and semesters.
* **How It Works:**
  * Trains on historical enrollment data from **Fall 2021 through Spring 2024** (Terms 0–5) and tests its accuracy on **Fall 2024** (Term 6, 58 courses) to simulate real-world forecasting without peeking at future answers.
  * Looks at the degree program (`BCS`, `BAI`, `BSE`, `BCY`, `BEE`, `BBA`), semester (`5` or `7`), course name, number of sections offered, and semester progression.
  * Predicts total course enrollment first, then divides by the number of sections to estimate per-section class size.

---

### Stage 3: Non-Linear Section Size & Large-Room Flagging — Decision Trees (`ml/decision_tree.py`)
* **Purpose:** Catch sudden jumps in class size that happen when a department opens or merges sections, and flag classes likely to exceed the **50-seat limit** of standard classrooms.
* **How It Works:**
  * Uses **lag features** (looking at what happened in the immediately preceding semester: previous enrollment, previous section count, and previous average class size).
  * **Decision Tree Regressor:** Learns step-by-step threshold rules to estimate exact section headcount.
  * **Decision Tree Classifier:** Specifically classifies whether a class will need a **Standard Room ($\le 50$ seats)** or a **Large Room ($> 50$ seats)**, and exports human-readable `IF-ELSE` rules that administrators can inspect directly on the webpage.

---

### Stage 4: Clash-Prone Course Grouping — K-Means Clustering (`ml/clustering.py`)
* **Purpose:** Automatically discover which courses compete for the exact same students so the timetable solver schedules high-risk courses first.
* **How It Works:**
  * Maps every course against all 39 student sections weighted by student headcount, then groups the 44 unique courses into **9 distinct clusters** ($k = 9$).
  * Calculates an **Overlap Density** and a **Clash Risk Score** (`0.22` up to `8.68`) for every course. For example, Semester 7 CS/SE core and elective courses (`BC`, `DS`, `FSPM`, `IPT`, `IS`, `PPIT`, `QC`, `RS`, `WP`) cluster together with a `0.96` overlap density and an **`8.68` clash risk score** because they share the same students and days off.
  * Feeds `cluster_clash_risk` into the CSP solver's variable-ordering heuristic (`select_variable`) so high-clash courses get first pick of rooms and time slots.

---

### Stage 5: Ensemble Fusion & Solver Guardrails (`ml/pipeline.py`)
* **Purpose:** Combine the predictions of Linear Regression and Decision Trees into a single reliable seat recommendation (`final_recommended_seats`) and safely apply it to the timetable solver (`apply_ml_to_problem`).
* **How It Works:**
  * Averages the continuous headcount predictions from Linear Regression and the Decision Tree Regressor (`ensemble_pred_size`) to cancel out individual model overshoots.
  * Filters out rooms that are too small for a class's predicted student count, while enforcing a safety rule (`len(filtered) >= 6`) so no class ever runs out of valid rooms or labs.

---

## 4. Shortcomings Encountered & How We Mitigated Them

During development and testing, we discovered several real-world limitations in individual ML models and fixed each one systematically:

| Shortcoming / Issue Encountered | Why It Happened | How It Was Mitigated |
| :--- | :--- | :--- |
| **1. Linear Regression missed sudden jumps when section counts changed** | Linear Regression assumes smooth, straight-line growth. When a department cut a course from 3 sections to 2 sections (causing class size to jump from 41 to 61.5 students), Linear Regression under-predicted it at 50 students. | Added **Decision Trees with previous-semester lag features**, which directly capture sudden section-count changes and step-function jumps. |
| **2. Linear Regression missed most $>50$-seat classes (`37.5%` Recall)** | Because ~86% of classes have $\le 50$ students, standard regression pulled borderline predictions down below 50, missing 5 out of 8 oversized classes. | Added a **balanced Decision Tree Classifier** (`class_weight='balanced'`) that pays extra attention to rare large classes, raising Large-Room Recall from **37.5% to 50.0%**. |
| **3. Individual models occasionally over- or under-shot noisy courses** | Single models can overreact to a single unusual semester in historical data. | Created an **Ensemble Average** combining Linear Regression and Decision Tree predictions, lowering average error (`MAE`) to **3.27 seats** (better than either model alone). |
| **4. Over-strict room filtering starved computer labs and broke timetable generation** | Initially, forcing a strict 53-seat minimum on flagged classes pushed **34 out of 43 weekly labs** above 48 seats. Because 8 of the 12 general computing labs hold 48 seats and only 4 hold 54–56 seats, 34 three-hour labs were squeezed into just 4 rooms—causing the solver to fail (`BCS-5C-DB-LAB#1` and `BSE-5A-DB-LAB#1` had only 4 possible rooms). | Replaced the hard 53-seat floor with the calibrated **Ensemble seat forecast** (reducing $>48$-seat labs from 34 down to 5) and added a **6-room minimum supply guard** (`len(filtered) >= 6`), restoring 100% timetable solvability (`536 / 536` classes scheduled). |
| **5. Regression had no awareness of student schedule clashes** | Predicting class size alone does not tell the solver which courses share the same student batches. | Added **K-Means Clustering** to score student cohort overlap (`cluster_clash_risk`) and guide the CSP solver's scheduling priority. |

---

## 5. Statistics, Performance Metrics & What They Tell Us

All supervised models were evaluated on the unseen **Fall 2024 holdout set ($n = 58$ courses)** after training only on earlier semesters (Fall 2021 – Spring 2024).

### A. Model-by-Model Comparison Table

| Model | Section MAE *(seats)* | Section RMSE *(seats)* | Section MAPE *(%)* | Room Tier Accuracy *(%)* | Large-Room Precision *(%)* | Large-Room Recall *(%)* | Large-Room F1 *(%)* |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Linear Regression (OLS)** | `3.52` | `4.33` | `7.97%` | **`82.76%`** | **`37.50%`** | `37.50%` | **`37.50%`** |
| **Decision Tree (Reg + Cls)** | `3.48` | `4.54` | `7.14%` | `70.69%` | `23.53%` | **`50.00%`** | `32.00%` |
| **Ensemble (Reg + DT Avg)** | **`3.27`** | **`4.25`** | **`7.12%`** | `81.03%` | `33.33%` | `37.50%` | `35.29%` |

---

### B. Plain-Language Guide to Every Metric

1. **Course Enrollment $R^2$ (`0.9718` / `97.18%`):**
   * *What it measures:* How much of the variation in total course enrollment our trend model successfully explains (out of 100%).
   * *What it tells us:* University enrollment growth from 2021 (`5,557` students) to 2024 (`6,550` students) follows a highly predictable pattern, and our model captures **97.18%** of it.
2. **Section MAE — Mean Absolute Error (`3.27` seats for Ensemble):**
   * *What it measures:* On average, how many seats off our prediction is from the actual number of students in a classroom.
   * *What it tells us:* Across all courses, our ensemble prediction is within **±3.3 students** of the true headcount—accurate enough to pick the right room size without wasting seats.
3. **Section RMSE — Root Mean Squared Error (`4.25` seats for Ensemble):**
   * *What it measures:* Similar to MAE, but penalizes large mistakes much more heavily.
   * *What it tells us:* Because `4.25` is very close to `3.27`, our ensemble model rarely makes big errors and avoids extreme over- or under-predictions.
4. **Section MAPE — Mean Absolute Percentage Error (`7.12%` for Ensemble):**
   * *What it measures:* The average prediction error expressed as a percentage of the actual class size.
   * *What it tells us:* Our seat forecasts are **~92.9% accurate** across both small specialized electives and large core classes.
5. **Room Tier Accuracy (`82.76%` for Linear Regression):**
   * *What it measures:* How often the model correctly distinguishes between a standard class ($\le 50$ seats) and a large class ($> 50$ seats).
   * *What it tells us:* Nearly **83% of all courses** are placed into the exact right room-size category before any safety buffer is even added.
6. **Large-Room Recall (`50.00%` for Decision Tree Classifier):**
   * *What it measures:* Out of all classes that actually exceeded 50 seats, what percentage did the model catch?
   * *What it tells us:* Catching half of all sudden enrollment spikes without any manual intervention prevents real-world classroom overcrowding.
7. **Large-Room Precision (`37.50%` for OLS / `23.53%` for Decision Tree):**
   * *What it measures:* When the model flags a class as needing a large room ($> 50$ seats), how often does it actually exceed 50 seats?
   * *What it tells us:* The Decision Tree intentionally acts cautiously on borderline classes (47–50 students), which is why we used the continuous Ensemble average for solver room filtering so scarce large halls and 48-seat labs are not wasted.
8. **K-Means Silhouette Score (`0.8178` at $k = 9$):**
   * *What it measures:* How cleanly separated the course clusters are from one another (scored from `-1` to `+1`, where anything above `0.70` indicates strong, clear grouping).
   * *What it tells us:* A score of **`0.8178`** confirms that courses naturally divide into **9 distinct student-cohort groups**, making the resulting `cluster_clash_risk` scores highly reliable for prioritizing the scheduler.
9. **Within-Cluster Inertia (`3.65` at $k = 9$):**
   * *What it measures:* How tightly packed courses are inside each cluster (lower is tighter).
   * *What it tells us:* Inertia drops steeply up to $k = 9$ and levels off afterward, proving **9 clusters** is the sweet spot.

---

## 6. End-to-End System Results (After Integration)

When the ML pipeline is active alongside the CSP solver (`Backtracking + MRV + Forward Checking`), the system achieves:

* **Classes Scheduled:** **`536 / 536` (`100%` completeness)**
* **Hard Constraint Violations:** **`0`** (zero teacher clashes, room double-bookings, capacity overflows, or day-off violations)
* **Average Seat Utilization:** **`79.2%`** across 55 utilized rooms (balanced seating with no overcrowded rooms and minimal wasted space)
* **Interactive Web Analytics (`app.py`):**
  * **`8. Data analytics`:** Displays cleaned dataset KPIs, historical enrollment trends (2021–2024), faculty workload distributions, and room capacity breakdowns.
  * **`9. ML analytics`:** Displays the live Model Benchmark Scorecard, Confusion Matrices, Decision Tree `IF-ELSE` rules, 2D PCA cluster scatter plots, and clash-risk rankings.