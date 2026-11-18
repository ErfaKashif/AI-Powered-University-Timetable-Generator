"""Step 2: Linear Regression for Enrollment & Section Size Prediction.

Trains an Ordinary Least Squares (LinearRegression) pipeline on historical enrollment
data (`enrollment_history_synthetic.csv`) using a chronological train/test split
(Terms 0-5 -> Term 6), then forecasts section sizes for all 209 Fall 2024 offerings.
"""
import os
import sys
import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.linear_model import LinearRegression
from sklearn.metrics import mean_absolute_error, root_mean_squared_error, r2_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

# Ensure sibling imports work whether run directly or imported from project root
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from eda import load_and_clean_all


def train_linear_regression(history_df):
    """Trains LinearRegression to predict course enrollment, then derives section_size."""
    cat_features = ['program', 'course'] #categorical
    num_features = ['term_index', 'semester', 'is_elective_flag', 'sections_offered'] #numerical
    features = cat_features + num_features #combined training features

    # Chronological split: train on Fall 2021-Spring 2024 (0..5), test on Fall 2024 (6)
    train_df = history_df[history_df['term_index'] < 6].copy()
    test_df = history_df[history_df['term_index'] == 6].copy()

    preprocessor = ColumnTransformer(
        transformers=[
            ('cat', OneHotEncoder(handle_unknown='ignore'), cat_features),
            ('num', 'passthrough', num_features),
        ]
    )

    pipeline = Pipeline([
        ('preprocessor', preprocessor),
        ('regressor', LinearRegression())
    ])

    pipeline.fit(train_df[features], train_df['enrollment'])

    # Evaluate on Fall 2024 holdout set
    test_df['pred_enrollment'] = pipeline.predict(test_df[features]).round(1)
    test_df['pred_section_size'] = (test_df['pred_enrollment'] / test_df['sections_offered']).round(1)

    metrics = {
        'train_rows': len(train_df),
        'test_rows': len(test_df),
        'enrollment_MAE': round(mean_absolute_error(test_df['enrollment'], test_df['pred_enrollment']), 2),
        'enrollment_RMSE': round(root_mean_squared_error(test_df['enrollment'], test_df['pred_enrollment']), 2),
        'enrollment_R2': round(r2_score(test_df['enrollment'], test_df['pred_enrollment']), 4),
        'section_size_MAE': round(mean_absolute_error(test_df['section_size'], test_df['pred_section_size']), 2),
    }

    # Refit on all available history (Terms 0..6) to forecast next term (term_index = 7)
    pipeline.fit(history_df[features], history_df['enrollment'])
    return pipeline, metrics, test_df


def forecast_offerings_section_size(pipeline, offerings_df, seat_buffer=0.05):
    """Maps predicted section sizes onto all 209 course offerings for room allocation."""
    sec_counts = (
        offerings_df[offerings_df['type'] == 'lecture']
        .groupby(['program', 'semester', 'course'])['num_sections']
        .sum()
        .reset_index()
        .rename(columns={'num_sections': 'sections_offered'})
    )

    query_df = offerings_df[['offering_id', 'program', 'semester', 'course', 'type', 'is_elective_flag']].merge(
        sec_counts, on=['program', 'semester', 'course'], how='left'
    )
    query_df['sections_offered'] = query_df['sections_offered'].fillna(1).astype(int)
    query_df['term_index'] = 7  # Next upcoming term forecast

    features = ['program', 'course', 'term_index', 'semester', 'is_elective_flag', 'sections_offered']
    pred_total = pipeline.predict(query_df[features])
    raw_section_size = np.maximum(15.0, pred_total / query_df['sections_offered'])

    query_df['predicted_section_size'] = np.round(raw_section_size, 1)
    query_df['recommended_room_capacity'] = np.ceil(raw_section_size * (1.0 + seat_buffer)).astype(int)
    return query_df

from sklearn.metrics import (
    accuracy_score, precision_score, recall_score, f1_score,
    confusion_matrix, classification_report, mean_absolute_percentage_error
)

def evaluate_room_tier_classification(test_df, seat_threshold=50.0):
    """Evaluates continuous section-size predictions on the binary room-capacity threshold."""
    y_true = test_df['section_size']
    y_pred = test_df['pred_section_size']

    actual_large = (y_true > seat_threshold).astype(int)
    pred_large = (y_pred > seat_threshold).astype(int)

    cm = confusion_matrix(actual_large, pred_large)
    report = {
        'MAPE_%': round(mean_absolute_percentage_error(y_true, y_pred) * 100, 2),
        'Accuracy_%': round(accuracy_score(actual_large, pred_large) * 100, 2),
        'Precision_%': round(precision_score(actual_large, pred_large, zero_division=0) * 100, 2),
        'Recall_%': round(recall_score(actual_large, pred_large, zero_division=0) * 100, 2),
        'F1_Score_%': round(f1_score(actual_large, pred_large, zero_division=0) * 100, 2),
        'Confusion_Matrix': cm,
        'Classification_Report': classification_report(
            actual_large, pred_large,
            target_names=['Standard Room (<=50)', 'Large Room (>50)'],
            zero_division=0
        )
    }
    return report

if __name__ == '__main__':
    pd.set_option('display.max_columns', None)
    pd.set_option('display.width', 1000)

    clean_data = load_and_clean_all()
    model, metrics, test_eval = train_linear_regression(clean_data['history'])
    forecasts = forecast_offerings_section_size(model, clean_data['offerings'])

    print("=" * 70)
    print("1. LINEAR REGRESSION EVALUATION METRICS (Holdout: Fall 2024)")
    print("=" * 70)
    for k, v in metrics.items():
        print(f"  {k:<25}: {v}")

    print("\n" + "=" * 70)
    print("2. ACTUAL VS. PREDICTED SAMPLE (Fall 2024 Test Set)")
    print("=" * 70)
    cols = ['program', 'semester', 'course', 'sections_offered', 'enrollment', 'pred_enrollment', 'section_size', 'pred_section_size']
    print(test_eval[cols].head(10).to_string(index=False))

    print("\n" + "=" * 70)
    print("3. NEXT-TERM ROOM CAPACITY FORECASTS FOR COURSE OFFERINGS (First 12)")
    print("=" * 70)
    f_cols = ['offering_id', 'program', 'semester', 'course', 'type', 'sections_offered', 'predicted_section_size', 'recommended_room_capacity']
    print(forecasts[f_cols].head(12).to_string(index=False))
