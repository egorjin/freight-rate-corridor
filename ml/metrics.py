import numpy as np
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score


def regression_metrics(y_true, y_pred):
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) == 0:
        raise ValueError("no rows to score")
    abs_pct = np.abs(y_true - y_pred) / y_true
    return {
        "r2": float(r2_score(y_true, y_pred)),
        "mape_pct": float(np.mean(abs_pct) * 100.0),
        "rmse_rub": float(np.sqrt(mean_squared_error(y_true, y_pred))),
        "mae_rub": float(mean_absolute_error(y_true, y_pred)),
    }
