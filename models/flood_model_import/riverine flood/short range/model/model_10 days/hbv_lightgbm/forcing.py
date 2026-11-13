"""Train-only monthly empirical quantile mapping and dated forecast ingestion."""
import numpy as np
import pandas as pd


class QuantileMapper:
    def __init__(self, grids=None):
        self.grids = grids or {}

    def fit(self, frame, train_mask):
        probabilities = np.linspace(0, 1, 201)
        for month in range(1, 13):
            selected = train_mask & (frame.index.month == month)
            for kind, source, reference in [
                ("rain", "rain_era5_mm", "rain_chirps_mm"),
                ("temperature", "temperature_c", "temperature_c")]:
                # Temperature reference == reanalysis: explicitly an identity mapping.
                x, y = frame.loc[selected, source], frame.loc[selected, reference]
                ok = np.isfinite(x) & np.isfinite(y)
                if ok.sum() < 30:
                    raise ValueError(f"Insufficient paired {kind} data in month {month}")
                self.grids[f"{kind}_{month}"] = {
                    "source": np.quantile(x[ok], probabilities).tolist(),
                    "reference": np.quantile(y[ok], probabilities).tolist(),
                    "pairs": int(ok.sum()), "identity": source == reference}
        return self

    def fit_archive(self, archive, frame, train_end, first_year):
        """Fit issued forecasts to reference weather by lead and calendar month."""
        a = archive.copy()
        a["valid_date"] = a.valid_date.dt.tz_localize(None)
        a = a[(a.valid_date <= pd.Timestamp(train_end)) & (a.valid_date.dt.year >= first_year)]
        a = a.join(frame[["rain_chirps_mm", "temperature_c"]].rename(
            columns={"temperature_c": "reference_temperature_c"}), on="valid_date")
        for lead in sorted(archive.lead_day.unique()):
            for month in range(1, 13):
                rows = a[(a.lead_day == lead) & (a.valid_date.dt.month == month)]
                for kind, source, reference in [("rain", "precipitation_mm", "rain_chirps_mm"),
                                                 ("temperature", "temperature_c", "reference_temperature_c")]:
                    ok = np.isfinite(rows[source]) & np.isfinite(rows[reference])
                    if ok.sum() < 30:
                        raise ValueError(f"Archive has <30 training pairs: lead={lead}, month={month}, {kind}")
                    self.grids[f"{kind}_{month}_lead{lead}"] = {
                        "source": np.quantile(rows.loc[ok, source], np.linspace(0, 1, 201)).tolist(),
                        "reference": np.quantile(rows.loc[ok, reference], np.linspace(0, 1, 201)).tolist(),
                        "pairs": int(ok.sum()), "identity": False}
        return self

    def transform(self, values, months, kind, lead=None):
        values = np.asarray(values, float)
        months = np.broadcast_to(np.asarray(months), values.shape)
        out = np.empty_like(values)
        for month in np.unique(months):
            selected = months == month
            key = f"{kind}_{month}" + (f"_lead{lead}" if lead is not None else "")
            if key not in self.grids and lead is not None:
                # Deployment from a reanalysis-trained run: retain its saved mapping;
                # caller must flag the provider/operations mismatch in output metadata.
                key = f"{kind}_{month}"
            grid = self.grids[key]
            if grid["identity"]:
                out[selected] = values[selected]
                continue
            x, y = np.array(grid["source"]), np.array(grid["reference"])
            # Rightmost quantile for ties (incl. dry values), explicit exact dry-day rule.
            x_unique = np.unique(x)
            y_unique = y[np.searchsorted(x, x_unique, side="right") - 1]
            mapped = np.interp(values[selected], x_unique, y_unique)
            # Additive tail extrapolation avoids silently clipping extreme precipitation.
            mapped += np.maximum(values[selected] - x[-1], 0)
            if kind == "rain":
                mapped = np.where(values[selected] <= 0, 0, np.maximum(mapped, 0))
            out[selected] = mapped
        return out


def validate_archive(frame, horizon=10):
    required = {"issue_date", "valid_date", "lead_day", "member", "available_at",
                "precipitation_mm", "temperature_c"}
    if not required.issubset(frame):
        raise ValueError(f"Forecast archive missing {sorted(required - set(frame))}")
    frame = frame.copy()
    for col in ["issue_date", "valid_date", "available_at"]:
        frame[col] = pd.to_datetime(frame[col], utc=True)
        if frame[col].isna().any():
            raise ValueError(f"Missing forecast timestamp: {col}")
    if frame["member"].isna().any():
        raise ValueError("Missing forecast member")
    if not (frame.issue_date == frame.issue_date.dt.normalize()).all() or not (frame.valid_date == frame.valid_date.dt.normalize()).all():
        raise ValueError("Issue/valid dates must be UTC calendar-day labels at midnight")
    # Issue is end-of-day UTC: day t data available, targets t+1,...,t+10.
    if (frame.available_at > frame.issue_date + pd.Timedelta(days=1)).any():
        raise ValueError("Forecast published after issue cutoff")
    if not frame.lead_day.between(1, horizon).all() or not (frame.lead_day % 1 == 0).all():
        raise ValueError("Forecast lead outside configured horizon")
    if not ((frame.valid_date - frame.issue_date).dt.days == frame.lead_day).all():
        raise ValueError("Forecast valid date and lead disagree")
    if (frame[["precipitation_mm", "temperature_c"]].isna().any().any()
            or not np.isfinite(frame[["precipitation_mm", "temperature_c"]]).all().all()
            or (frame.precipitation_mm < 0).any()):
        raise ValueError("Invalid forecast weather")
    if frame.duplicated(["issue_date", "member", "lead_day"]).any():
        raise ValueError("Duplicate issue/member/lead")
    if not (frame.groupby(["issue_date", "member"]).size() == horizon).all():
        raise ValueError("Incomplete forecast trajectory")
    return frame


def mixture_quantiles(member_quantiles, levels=(0.1, 0.5, 0.9)):
    """Invert an equal-member mixture CDF, rather than averaging quantiles.

    Constant tails outside P10/P90 are an explicit limited-tail approximation.
    Returns combined quantiles and diagnostic inverse-CDF samples.
    """
    arr = np.sort(np.maximum(np.asarray(member_quantiles), 0), axis=-1)
    u = (np.arange(101) + 0.5) / 101
    samples = np.stack([np.interp(u, levels, row) for row in arr.reshape(-1, 3)])
    samples = samples.reshape(arr.shape[:-1] + (len(u),))
    # input: issue, member, lead, quantile; combine member and conditional probability.
    samples = samples.transpose(0, 2, 1, 3).reshape(arr.shape[0], arr.shape[2], -1)
    if arr.shape[1] == 1:
        return arr[:, 0], samples
    # Piecewise-linear CDF with point masses at the two constant tails.
    members = arr.transpose(0, 2, 1, 3)
    low_endpoint, middle, high_endpoint = [members[..., j] for j in range(3)]
    quantiles = np.empty((arr.shape[0], arr.shape[2], 3))
    for j, level in enumerate(levels):
        lower, upper = low_endpoint.min(-1), high_endpoint.max(-1)
        for _ in range(55):
            value = ((lower + upper) / 2)[..., None]
            f1 = np.divide(value-low_endpoint, middle-low_endpoint,
                           out=np.zeros_like(middle), where=middle > low_endpoint)
            f2 = np.divide(value-middle, high_endpoint-middle,
                           out=np.zeros_like(middle), where=high_endpoint > middle)
            cdf = np.where(value < low_endpoint, 0., np.where(value < middle, .1 + .4*f1,
                           np.where(value < high_endpoint, .5 + .4*f2, 1.)))
            above = cdf.mean(-1) >= level
            upper, lower = np.where(above, value[..., 0], upper), np.where(above, lower, value[..., 0])
        quantiles[..., j] = upper
    return quantiles, samples


def mixture_exceedance(member_quantiles, threshold):
    """Exact P(Q>=threshold) for the assumed piecewise-linear quantile curves.

    Input is member x lead x quantile; averaging is over members. Equality at a
    tail atom is handled using the left limit of the CDF, including zero flow.
    """
    arr = np.sort(np.maximum(np.asarray(member_quantiles), 0), axis=-1)
    low, middle, high = arr[..., 0], arr[..., 1], arr[..., 2]
    f1 = np.divide(threshold-low, middle-low, out=np.zeros_like(low), where=middle > low)
    f2 = np.divide(threshold-middle, high-middle, out=np.zeros_like(low), where=high > middle)
    below = np.where(threshold <= low, 0., np.where(threshold <= middle, .1 + .4*f1,
                     np.where(threshold <= high, .5 + .4*f2, 1.)))
    return np.clip(1 - below, 0, 1).mean(axis=0)
