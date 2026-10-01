from app.core.enums import FloodStatus, Scenario, Severity
from app.risk.features import RiskFeatures


class RuleBasedRiskEngine:
    def evaluate(self, features: RiskFeatures, scenario: Scenario) -> tuple[float, Severity, FloodStatus, float, list[str], str]:
        warning_pressure = (
            features.river_level_relative_to_warning
            if features.river_level_relative_to_warning is not None
            else features.river_discharge / 2500
        )
        danger_pressure = (
            features.river_level / 7.0
            if features.river_level is not None
            else features.river_discharge / 3500
        )
        rise_pressure = (
            features.river_rise_rate / 0.75
            if features.river_rise_rate is not None
            else max(features.river_discharge_change, 0) / 1000
        )
        score = (
            min(features.rainfall_last_24h / 220, 1) * 0.24
            + min(features.forecast_rainfall_24h / 140, 1) * 0.16
            + min(warning_pressure, 1.4) / 1.4 * 0.22
            + min(danger_pressure, 1.25) / 1.25 * 0.18
            + min(max(rise_pressure, 0), 1) * 0.12
            + min(features.soil_moisture / 100, 1) * 0.08
        )
        probability = max(0, min(round(score, 2), 1))

        if scenario == Scenario.FALSE_ALARM:
            severity = Severity.LOW
            status = FloodStatus.FALSE_ALARM
            probability = min(probability, 0.35)
        elif scenario == Scenario.CONFIRMED_FLOOD:
            severity = Severity.CRITICAL
            status = FloodStatus.CONFIRMED
            probability = max(probability, 0.9)
        elif probability >= 0.78:
            severity = Severity.CRITICAL
            status = FloodStatus.PREDICTED
        elif probability >= 0.58:
            severity = Severity.HIGH
            status = FloodStatus.PREDICTED
        elif probability >= 0.38:
            severity = Severity.MEDIUM
            status = FloodStatus.UNDER_VERIFICATION
        else:
            severity = Severity.LOW
            status = FloodStatus.NORMAL

        factors = self._factors(features)
        if status == FloodStatus.CONFIRMED:
            factors.append("Positive flood verification evidence")
        if status == FloodStatus.FALSE_ALARM:
            factors.append("River remains stable without confirming evidence")
        explanation = ", ".join(factors) if factors else "Conditions are within normal operating ranges"
        confidence = 0.84 if severity in {Severity.HIGH, Severity.CRITICAL} else 0.76
        return probability, severity, status, confidence, factors, explanation

    def _factors(self, features: RiskFeatures) -> list[str]:
        factors = []
        if features.rainfall_last_24h >= 75:
            factors.append("Heavy rainfall")
        if features.forecast_rainfall_24h >= 60:
            factors.append("Continued rainfall forecast")
        if features.river_level_relative_to_warning is not None and features.river_level_relative_to_warning >= 1:
            factors.append("River above warning level")
        if features.river_level is not None and features.river_level >= 7.0:
            factors.append("River near or above danger level")
        if features.river_rise_rate is not None and features.river_rise_rate >= 0.35:
            factors.append("Rapid river rise")
        if features.river_level is None and features.river_discharge >= 2500:
            factors.append("High modeled river discharge")
        if features.river_level is None and features.river_discharge_change >= 500:
            factors.append("Rapid modeled discharge increase")
        if features.soil_moisture >= 80:
            factors.append("High soil saturation")
        return factors
