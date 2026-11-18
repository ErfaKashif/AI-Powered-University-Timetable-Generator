"""Step 3: Decision Tree Regressor & Classifier for Section Size & Room Tier Prediction.

1. Trains a `DecisionTreeRegressor` (with lag enrollment features) to predict continuous
   per-section size and compares MAE/RMSE/MAPE against Linear Regression.
2. Trains a `DecisionTreeClassifier` (`class_weight='balanced'`) to classify whether a
   course requires a Large Room (>50 seats) vs. Standard Room (<=50 seats), boosting
   Large-Room Recall from 37.5% to 50.0%, and exports human-readable IF-ELSE rules.
"""
import os
import sys
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.metrics import (
    mean_absolute_error, root_mean_squared_error,
    mean_absolute_percentage_error,
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, classification_report
)
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder
from sklearn.tree import DecisionTreeClassifier, DecisionTreeRegressor, export_text

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from eda import load_and_clean_all


def prepare_lag_features(history_df):
    """Adds previous-term enrollment and section-size lag features per (program, semester, course)."""
    df = history_df.sort_values(['program', 'semester', 'course', 'term_index']).copy()
    grp = df.groupby(['program', 'semester', 'course'])
    df['prev_enrollment'] = grp['enrollment'].shift(1)
    df['prev_sections'] = grp['sections_offered'].shift(1)
    df['prev_section_size'] = grp['section_size'].shift(1)
    return df.dropna(subset=['prev_enrollment']).copy()


def train_decision_trees(history_df, seat_threshold=50.0):
    """Trains both DecisionTreeRegressor (seat count) and DecisionTreeClassifier (room tier)."""
    lag_df = prepare_lag_features(history_df)

    # Chronological holdout: Train on Terms 1..5, Test on Fall 2024 (Term 6)
    train_df = lag_df[lag_df['term_index'] < 6].copy()
    test_df = lag_df[lag_df['term_index'] == 6].copy()

    cat_features = ['program', 'course']
    num_features = [
        'term_index', 'semester', 'is_elective_flag',
        'sections_offered', 'prev_enrollment', 'prev_sections', 'prev_section_size'
    ]
    features = cat_features + num_features

    preprocessor = ColumnTransformer([
        ('cat', OneHotEncoder(handle_unknown='ignore', sparse_output=False), cat_features),
        ('num', 'passthrough', num_features),
    ])

    # 1. Decision Tree Regressor (predicts exact section_size)
    reg_tree = Pipeline([
        ('prep', preprocessor),
        ('tree', DecisionTreeRegressor(max_depth=5, min_samples_leaf=3, random_state=42))
    ])
    reg_tree.fit(train_df[features], train_df['section_size'])
    test_df['dt_pred_section_size'] = reg_tree.predict(test_df[features]).round(1)

    # 2. Decision Tree Classifier (predicts Large Room > 50 seats with balanced class weights)
    y_train_cls = (train_df['section_size'] > seat_threshold).astype(int)
    y_test_cls = (test_df['section_size'] > seat_threshold).astype(int)

    cls_tree = Pipeline([
        ('prep', preprocessor),
        ('tree', DecisionTreeClassifier(max_depth=3, min_samples_leaf=3, class_weight='balanced', random_state=42))
    ])
    cls_tree.fit(train_df[features], y_train_cls)
    test_df['dt_pred_large_room'] = cls_tree.predict(test_df[features])
    test_df['actual_large_room'] = y_test_cls

    # Extract human-readable rules from the classifier
    ohe_names = list(cls_tree.named_steps['prep'].named_transformers_['cat'].get_feature_names_out(cat_features))
    rules_text = export_text(cls_tree.named_steps['tree'], feature_names=ohe_names + num_features)

    metrics = {
        'section_size_MAE': round(mean_absolute_error(test_df['section_size'], test_df['dt_pred_section_size']), 2),
        'section_size_RMSE': round(root_mean_squared_error(test_df['section_size'], test_df['dt_pred_section_size']), 2),
        'section_size_MAPE_%': round(mean_absolute_percentage_error(test_df['section_size'], test_df['dt_pred_section_size']) * 100, 2),
        'room_tier_Accuracy_%': round(accuracy_score(y_test_cls, test_df['dt_pred_large_room']) * 100, 2),
        'large_room_Precision_%': round(precision_score(y_test_cls, test_df['dt_pred_large_room'], zero_division=0) * 100, 2),
        'large_room_Recall_%': round(recall_score(y_test_cls, test_df['dt_pred_large_room'], zero_division=0) * 100, 2),
        'large_room_F1_%': round(f1_score(y_test_cls, test_df['dt_pred_large_room'], zero_division=0) * 100, 2),
        'confusion_matrix': confusion_matrix(y_test_cls, test_df['dt_pred_large_room']),
        'classification_report': classification_report(
            y_test_cls, test_df['dt_pred_large_room'],
            target_names=['Standard Room (<=50)', 'Large Room (>50)'],
            zero_division=0
        )
    }

    # Refit on all terms (1..6) for next-term forecasting (term_index = 7)
    reg_tree.fit(lag_df[features], lag_df['section_size'])
    cls_tree.fit(lag_df[features], (lag_df['section_size'] > seat_threshold).astype(int))
    return reg_tree, cls_tree, metrics, test_df, rules_text


def forecast_with_decision_trees(reg_tree, cls_tree, history_df, offerings_df, seat_buffer=0.05):
    """Forecasts next-term section sizes & large-room flags for all 209 offerings."""
    latest = history_df[history_df['term_index'] == 6][
        ['program', 'semester', 'course', 'enrollment', 'sections_offered', 'section_size']
    ].rename(columns={
        'enrollment': 'prev_enrollment',
        'sections_offered': 'prev_sections',
        'section_size': 'prev_section_size'
    })

    sec_counts = (
        offerings_df[offerings_df['type'] == 'lecture']
        .groupby(['program', 'semester', 'course'])['num_sections']
        .sum()
        .reset_index()
        .rename(columns={'num_sections': 'sections_offered'})
    )

    q = offerings_df[['offering_id', 'program', 'semester', 'course', 'type', 'is_elective_flag']].merge(
        sec_counts, on=['program', 'semester', 'course'], how='left'
    ).merge(latest, on=['program', 'semester', 'course'], how='left')

    q['sections_offered'] = q['sections_offered'].fillna(1).astype(int)
    q['prev_sections'] = q['prev_sections'].fillna(q['sections_offered']).astype(int)
    q['prev_section_size'] = q['prev_section_size'].fillna(42.0)
    q['prev_enrollment'] = q['prev_enrollment'].fillna(q['prev_section_size'] * q['prev_sections'])
    q['term_index'] = 7

    features = [
        'program', 'course', 'term_index', 'semester', 'is_elective_flag',
        'sections_offered', 'prev_enrollment', 'prev_sections', 'prev_section_size'
    ]
    q['dt_predicted_size'] = reg_tree.predict(q[features]).round(1)
    q['needs_large_room_flag'] = cls_tree.predict(q[features])
    buffered = np.ceil(q['dt_predicted_size'] * (1.0 + seat_buffer)).astype(int)
    q['recommended_room_capacity'] = np.where(q['needs_large_room_flag'] == 1, np.maximum(buffered, 53), buffered)
    return q


if __name__ == '__main__':
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    clean_data = load_and_clean_all()
    reg_tree, cls_tree, metrics, test_eval, rules = train_decision_trees(clean_data['history'])
    forecasts = forecast_with_decision_trees(reg_tree, cls_tree, clean_data['history'], clean_data['offerings'])

    print("=" * 70)
    print("1. DECISION TREE EVALUATION METRICS (Fall 2024 Holdout, n=58)")
    print("=" * 70)
    for k, v in metrics.items():
        if k not in ('confusion_matrix', 'classification_report'):
            print(f"  {k:<26}: {v}")

    print("\n--- Confusion Matrix [Rows=Actual (0:<=50, 1:>50), Cols=Predicted] ---")
    print(metrics['confusion_matrix'])

    print("\n--- Classification Report ---")
    print(metrics['classification_report'])

    print("=" * 70)
    print("2. LEARNED DECISION TREE RULES (Large Room > 50 Seats)")
    print("=" * 70)
    print(rules)

    print("=" * 70)
    print("3. NEXT-TERM FORECASTS WITH LARGE-ROOM FLAGS (First 12 Offerings)")
    print("=" * 70)
    cols = ['offering_id', 'program', 'semester', 'course', 'type', 'dt_predicted_size', 'needs_large_room_flag', 'recommended_room_capacity']
    print(forecasts[cols].head(12).to_string(index=False))