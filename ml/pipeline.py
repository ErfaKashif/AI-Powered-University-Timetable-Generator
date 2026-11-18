"""Unified ML Pipeline connecting EDA, Linear Regression, Decision Trees, and K-Means
to the CSP & Genetic Algorithm Timetable Solvers and Streamlit UI.
"""
import os
import sys
import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    confusion_matrix,
    f1_score,
    mean_absolute_error,
    mean_absolute_percentage_error,
    precision_score,
    r2_score,
    recall_score,
    root_mean_squared_error,
)

ML_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_DIR = os.path.dirname(ML_DIR)
for p in (ML_DIR, PROJECT_DIR):
    if p not in sys.path:
        sys.path.insert(0, p)

from eda import load_and_clean_all, summarize_eda
from regression import forecast_offerings_section_size, train_linear_regression
from decision_tree import forecast_with_decision_trees, train_decision_trees
from clustering import cluster_courses_kmeans

DEFAULT_DATA_DIR = os.path.join(PROJECT_DIR, 'data') if os.path.exists(os.path.join(PROJECT_DIR, 'data')) else PROJECT_DIR


def _compute_full_eval_metrics(y_true_sec, y_pred_sec, seat_threshold=50.0):
    """Computes continuous regression + operational room-tier classification metrics."""
    actual_large = (y_true_sec > seat_threshold).astype(int)
    pred_large = (y_pred_sec > seat_threshold).astype(int)

    return {
        'section_size_MAE': round(float(mean_absolute_error(y_true_sec, y_pred_sec)), 2),
        'section_size_RMSE': round(float(root_mean_squared_error(y_true_sec, y_pred_sec)), 2),
        'section_size_MAPE_%': round(float(mean_absolute_percentage_error(y_true_sec, y_pred_sec) * 100), 2),
        'section_size_R2': round(float(r2_score(y_true_sec, y_pred_sec)), 4),
        'room_tier_Accuracy_%': round(float(accuracy_score(actual_large, pred_large) * 100), 2),
        'large_room_Precision_%': round(float(precision_score(actual_large, pred_large, zero_division=0) * 100), 2),
        'large_room_Recall_%': round(float(recall_score(actual_large, pred_large, zero_division=0) * 100), 2),
        'large_room_F1_%': round(float(f1_score(actual_large, pred_large, zero_division=0) * 100), 2),
        'confusion_matrix': confusion_matrix(actual_large, pred_large),
        'classification_report': classification_report(
            actual_large,
            pred_large,
            target_names=['Standard Room (<=50)', 'Large Room (>50)'],
            zero_division=0,
        ),
    }


def run_ml_pipeline(data_dir=DEFAULT_DATA_DIR, n_clusters=9, seat_buffer=0.05):
    """Runs all 4 ML components end-to-end and returns predictions, clusters, and full metrics."""
    clean_data = load_and_clean_all(data_dir)
    kpis, eda_tables = summarize_eda(clean_data)

    # 1. Linear Regression + Full Holdout Metrics
    reg_model, reg_metrics, reg_test = train_linear_regression(clean_data['history'])
    reg_metrics.update(_compute_full_eval_metrics(reg_test['section_size'], reg_test['pred_section_size']))
    reg_forecasts = forecast_offerings_section_size(
        reg_model, clean_data['offerings'], seat_buffer=seat_buffer
    )

    # 2. Decision Trees (Regressor + Classifier) + Full Holdout Metrics
    dt_reg, dt_cls, dt_metrics, dt_test, dt_rules = train_decision_trees(clean_data['history'])
    dt_metrics['section_size_R2'] = round(
        float(r2_score(dt_test['section_size'], dt_test['dt_pred_section_size'])), 4
    )
    dt_forecasts = forecast_with_decision_trees(
        dt_reg, dt_cls, clean_data['history'], clean_data['offerings'], seat_buffer=seat_buffer
    )

    # 3. Holdout Ensemble Evaluation (Average of Linear Regression + Decision Tree Regressor)
    holdout_merged = reg_test[
        ['program', 'semester', 'course', 'sections_offered', 'enrollment', 'pred_enrollment', 'section_size', 'pred_section_size']
    ].merge(
        dt_test[['program', 'semester', 'course', 'prev_section_size', 'dt_pred_section_size', 'actual_large_room', 'dt_pred_large_room']],
        on=['program', 'semester', 'course'],
    )
    holdout_merged['ensemble_pred_size'] = (
        (holdout_merged['pred_section_size'] + holdout_merged['dt_pred_section_size']) / 2.0
    ).round(1)
    ens_metrics = _compute_full_eval_metrics(holdout_merged['section_size'], holdout_merged['ensemble_pred_size'])

    # 4. K-Means Clustering
    cluster_res = cluster_courses_kmeans(clean_data['offerings'], clean_data['sections'], n_clusters=n_clusters)
    k_eval = cluster_res['k_evaluation']
    selected_k_row = k_eval[k_eval['k'] == min(n_clusters, len(cluster_res['course_assignments']))].iloc[0]
    cluster_metrics = {
        'n_clusters': int(selected_k_row['k']),
        'silhouette_score': round(float(selected_k_row['silhouette_score']), 4),
        'inertia': round(float(selected_k_row['inertia']), 2),
        'max_clash_risk': round(float(cluster_res['cluster_summary']['clash_risk_score'].max()), 2),
        'avg_overlap_density': round(float(cluster_res['cluster_summary']['overlap_density'].mean()), 2),
    }

    # 5. Master Model Comparison Table (Fall 2024 Chronological Holdout, n=58)
    model_comparison = pd.DataFrame([
        {
            'Model': 'Linear Regression (OLS)',
            'Section MAE': reg_metrics['section_size_MAE'],
            'Section RMSE': reg_metrics['section_size_RMSE'],
            'Section MAPE (%)': reg_metrics['section_size_MAPE_%'],
            'Section R²': reg_metrics['section_size_R2'],
            'Room Accuracy (%)': reg_metrics['room_tier_Accuracy_%'],
            'Large-Room Precision (%)': reg_metrics['large_room_Precision_%'],
            'Large-Room Recall (%)': reg_metrics['large_room_Recall_%'],
            'Large-Room F1 (%)': reg_metrics['large_room_F1_%'],
        },
        {
            'Model': 'Decision Tree (Reg + Cls)',
            'Section MAE': dt_metrics['section_size_MAE'],
            'Section RMSE': dt_metrics['section_size_RMSE'],
            'Section MAPE (%)': dt_metrics['section_size_MAPE_%'],
            'Section R²': dt_metrics['section_size_R2'],
            'Room Accuracy (%)': dt_metrics['room_tier_Accuracy_%'],
            'Large-Room Precision (%)': dt_metrics['large_room_Precision_%'],
            'Large-Room Recall (%)': dt_metrics['large_room_Recall_%'],
            'Large-Room F1 (%)': dt_metrics['large_room_F1_%'],
        },
        {
            'Model': 'Ensemble (Reg + DT Avg)',
            'Section MAE': ens_metrics['section_size_MAE'],
            'Section RMSE': ens_metrics['section_size_RMSE'],
            'Section MAPE (%)': ens_metrics['section_size_MAPE_%'],
            'Section R²': ens_metrics['section_size_R2'],
            'Room Accuracy (%)': ens_metrics['room_tier_Accuracy_%'],
            'Large-Room Precision (%)': ens_metrics['large_room_Precision_%'],
            'Large-Room Recall (%)': ens_metrics['large_room_Recall_%'],
            'Large-Room F1 (%)': ens_metrics['large_room_F1_%'],
        },
    ])

    # 6. Merge Next-Term Forecasts & Cluster Priorities across all 209 offerings
    merged_offerings = reg_forecasts[[
        'offering_id', 'program', 'semester', 'course', 'type',
        'sections_offered', 'predicted_section_size', 'recommended_room_capacity'
    ]].rename(columns={
        'predicted_section_size': 'reg_pred_size',
        'recommended_room_capacity': 'reg_room_cap'
    }).merge(
        dt_forecasts[['offering_id', 'dt_predicted_size', 'needs_large_room_flag', 'recommended_room_capacity']].rename(
            columns={'recommended_room_capacity': 'dt_room_cap'}
        ),
        on='offering_id'
    ).merge(
        cluster_res['offerings_enriched'][['offering_id', 'sections', 'is_elective', 'cluster_id', 'cluster_clash_risk']],
        on='offering_id'
    )

    merged_offerings['ensemble_pred_size'] = (
        (merged_offerings['reg_pred_size'] + merged_offerings['dt_predicted_size']) / 2.0
    ).round(1)
    merged_offerings['final_recommended_seats'] = merged_offerings['ensemble_pred_size'].round().astype(int)

    return {
        'clean_data': clean_data,
        'kpis': kpis,
        'eda_tables': eda_tables,
        'reg_metrics': reg_metrics,
        'reg_test': reg_test,
        'dt_metrics': dt_metrics,
        'dt_test': dt_test,
        'dt_rules': dt_rules,
        'ens_metrics': ens_metrics,
        'holdout_merged': holdout_merged,
        'model_comparison': model_comparison,
        'cluster_res': cluster_res,
        'cluster_metrics': cluster_metrics,
        'merged_offerings': merged_offerings,
        'room_capacity_map': dict(zip(merged_offerings['offering_id'], merged_offerings['final_recommended_seats'])),
        'course_risk_map': cluster_res['course_risk_map'],
    }


def apply_ml_to_problem(problem, ml_out):
    """Applies ML-predicted room capacities (respecting physical room supply) and K-Means clash risk."""
    cap_map = ml_out['room_capacity_map']
    risk_map = ml_out['course_risk_map']

    adjusted_count = 0
    for m in problem.meetings:
        req_seats = cap_map.get(m.offering.id, 0)
        if req_seats > 0:
            filtered = [r for r in problem.rooms_ok[m.id] if problem.room_by_name[r].capacity >= req_seats]
            if len(filtered) >= 6 and len(filtered) < len(problem.rooms_ok[m.id]):
                problem.rooms_ok[m.id] = filtered
                adjusted_count += 1

    problem.ml_clash_risk = {
        m.id: risk_map.get(m.offering.course, 0.0) for m in problem.meetings
    }
    return adjusted_count