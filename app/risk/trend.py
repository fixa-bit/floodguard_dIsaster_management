from app.core.enums import Trend


def calculate_trend(previous_probability: float | None, probability: float) -> tuple[Trend, float]:
    if previous_probability is None:
        return Trend.STABLE, 0.0
    change = round(probability - previous_probability, 4)
    if change <= -0.05:
        return Trend.FALLING, change
    if change >= 0.15:
        return Trend.RAPIDLY_RISING, change
    if change >= 0.05:
        return Trend.RISING, change
    return Trend.STABLE, change
