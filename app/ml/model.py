from pathlib import Path

import numpy as np
import xgboost as xgb

from app.risk.features import RiskFeatures


class ModelUnavailableError(RuntimeError):
    pass


class XGBoostRiskModel:
    name = "xgboost_v1"
    model_type = "machine_learning"

    def __init__(self, model_path: str):
        self.model_path = Path(model_path)
        self._model: xgb.Booster | None = None

    def _load(self) -> xgb.Booster:
        if self._model is None:
            if not self.model_path.is_file():
                raise ModelUnavailableError(f"Model artifact not found: {self.model_path}")
            model = xgb.Booster()
            try:
                model.load_model(self.model_path)
            except Exception as exc:
                raise ModelUnavailableError("Model artifact could not be loaded") from exc
            self._model = model
        return self._model

    def predict(self, features: RiskFeatures) -> float:
        values = np.asarray([features.as_model_vector()], dtype=np.float32)
        prediction = float(self._load().predict(xgb.DMatrix(values))[0])
        return round(min(max(prediction, 0.0), 1.0), 4)
