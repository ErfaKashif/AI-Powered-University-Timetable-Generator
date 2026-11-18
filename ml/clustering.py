"""Step 4: K-Means Clustering of Courses by Shared Student Cohorts.

Builds a Course x Section student-enrollment matrix from cleaned `offerings` and `sections`,
L2-normalizes each course's student distribution vector, evaluates optimal cluster count (k)
using Elbow Inertia and Silhouette Score, and groups courses into clash-prone clusters
to guide CSPSolver variable ordering and GeneticAlgorithm crossover.
"""
import os
import sys
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.decomposition import PCA
from sklearn.metrics import silhouette_score

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from eda import load_and_clean_all


def build_course_student_matrix(offerings_df, sections_df):
    """Creates a (Courses x Sections) matrix weighted by estimated student enrollment."""
    all_sections = sorted(sections_df['section'].unique())
    sec_enroll = dict(zip(sections_df['section'], sections_df['estimated_enrollment']))
    batch_sections = sections_df.groupby(['program', 'semester'])['section'].apply(list).to_dict()

    courses = sorted(offerings_df['course'].unique())
    matrix = pd.DataFrame(0.0, index=courses, columns=all_sections)

    for _, row in offerings_df.iterrows():
        course = row['course']
        prog = row['program']
        sem = row['semester']
        is_elec = (str(row['is_elective']).lower() == 'yes')

        if is_elec:
            # Electives draw students proportionally across all sections of that (program, semester)
            cohort_secs = batch_sections.get((prog, sem), [])
            if cohort_secs:
                total_cohort = sum(sec_enroll[s] for s in cohort_secs)
                for s in cohort_secs:
                    share = 42.0 * (sec_enroll[s] / total_cohort)
                    matrix.loc[course, s] = max(matrix.loc[course, s], share)
        else:
            for sec_letter in str(row['sections']).split(';'):
                sec_letter = sec_letter.strip()
                if not sec_letter:
                    continue
                full_sec = f"{prog}-{sem}{sec_letter}"
                if full_sec in matrix.columns:
                    matrix.loc[course, full_sec] = float(sec_enroll[full_sec])

    # L2-normalize rows so K-Means clusters by cosine similarity (shared student overlap)
    norms = np.linalg.norm(matrix.values, axis=1, keepdims=True)
    norms[norms == 0] = 1.0
    norm_matrix = matrix.values / norms
    return matrix, norm_matrix


def evaluate_k_range(norm_matrix, k_min=2, k_max=10, random_state=42):
    """Evaluates Inertia (Elbow) and Silhouette Score across candidate k values."""
    rows = []
    for k in range(k_min, min(k_max + 1, len(norm_matrix))):
        km = KMeans(n_clusters=k, n_init=20, random_state=random_state)
        labels = km.fit_predict(norm_matrix)
        sil = silhouette_score(norm_matrix, labels)
        rows.append({
            'k': k,
            'inertia': round(float(km.inertia_), 2),
            'silhouette_score': round(float(sil), 4)
        })
    return pd.DataFrame(rows)


def cluster_courses_kmeans(offerings_df, sections_df, n_clusters=9, random_state=42):
    """Clusters courses by shared student overlap and computes per-cluster clash risk."""
    raw_matrix, norm_matrix = build_course_student_matrix(offerings_df, sections_df)
    courses = raw_matrix.index.tolist()

    k = min(n_clusters, len(courses))
    kmeans = KMeans(n_clusters=k, n_init=20, random_state=random_state)
    labels = kmeans.fit_predict(norm_matrix)
    sil_score = round(float(silhouette_score(norm_matrix, labels)), 4)

    # 2D PCA coordinates for Streamlit / Matplotlib scatter visualization
    pca = PCA(n_components=2, random_state=random_state)
    coords = pca.fit_transform(norm_matrix)

    course_assignments = pd.DataFrame({
        'course': courses,
        'cluster_id': labels,
        'pca_x': np.round(coords[:, 0], 4),
        'pca_y': np.round(coords[:, 1], 4),
    })

    # Summarize each cluster's internal student overlap & clash density
    summary_rows = []
    course_risk_map = {}
    course_cluster_map = dict(zip(courses, labels))

    for cid in range(k):
        idx = [i for i, lbl in enumerate(labels) if lbl == cid]
        member_courses = [courses[i] for i in idx]

        if len(idx) > 1:
            sub_norm = norm_matrix[idx]
            sub_raw = raw_matrix.values[idx]

            cos_sim = sub_norm @ sub_norm.T
            np.fill_diagonal(cos_sim, 0.0)
            overlap_density = float(cos_sim.sum() / (len(idx) * (len(idx) - 1)))

            shared_students = np.minimum(sub_raw[:, None, :], sub_raw[None, :, :]).sum(axis=2)
            np.fill_diagonal(shared_students, 0.0)
            avg_shared = float(shared_students.sum() / (len(idx) * (len(idx) - 1)))
        else:
            overlap_density = 1.0
            avg_shared = 0.0

        clash_risk = round(overlap_density * len(member_courses), 2)
        for c in member_courses:
            course_risk_map[c] = clash_risk

        summary_rows.append({
            'cluster_id': cid,
            'num_courses': len(member_courses),
            'overlap_density': round(overlap_density, 2),
            'avg_shared_students': round(avg_shared, 1),
            'clash_risk_score': clash_risk,
            'courses': ', '.join(member_courses)
        })

    cluster_summary = pd.DataFrame(summary_rows).sort_values(
        ['clash_risk_score', 'avg_shared_students'], ascending=False
    ).reset_index(drop=True)

    # Map clash risk & cluster ID back onto all 209 course offerings for CSP/GA integration
    offerings_enriched = offerings_df[['offering_id', 'program', 'semester', 'sections', 'course', 'type', 'is_elective']].copy()
    offerings_enriched['cluster_id'] = offerings_enriched['course'].map(course_cluster_map)
    offerings_enriched['cluster_clash_risk'] = offerings_enriched['course'].map(course_risk_map)

    return {
        'silhouette_score': sil_score,
        'k_evaluation': evaluate_k_range(norm_matrix),
        'cluster_summary': cluster_summary,
        'course_assignments': course_assignments,
        'offerings_enriched': offerings_enriched,
        'course_cluster_map': course_cluster_map,
        'course_risk_map': course_risk_map,
    }


if __name__ == '__main__':
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    clean_data = load_and_clean_all()
    res = cluster_courses_kmeans(clean_data['offerings'], clean_data['sections'], n_clusters=9)

    print("=" * 75)
    print("1. K-MEANS HYPERPARAMETER TUNING (ELBOW INERTIA & SILHOUETTE SCORE)")
    print("=" * 75)
    print(res['k_evaluation'].to_string(index=False))

    print("\n" + "=" * 75)
    print(f"2. CLASH-PRONE COURSE CLUSTERS (k=9 | Silhouette Score = {res['silhouette_score']})")
    print("=" * 75)
    print(res['cluster_summary'].to_string(index=False))

    print("\n" + "=" * 75)
    print("3. ENRICHED COURSE OFFERINGS WITH CLASH RISK PRIORITY (Top 12)")
    print("=" * 75)
    top_off = res['offerings_enriched'].sort_values('cluster_clash_risk', ascending=False)
    print(top_off.head(12).to_string(index=False))