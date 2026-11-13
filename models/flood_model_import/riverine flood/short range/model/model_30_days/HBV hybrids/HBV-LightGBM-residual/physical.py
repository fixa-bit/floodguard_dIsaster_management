"""Daily lumped HBV: degree-day snow, nonlinear soil, two response stores, routing.

Water units are mm; routing is a conservative linear reservoir. Its state is
included in every saved restart. No discharge observations enter the simulation.
"""
import numpy as np
from numba import njit
from scipy.optimize import differential_evolution

PARAMETERS = ["tt", "cfmax", "sfcf", "cfr", "cwh", "fc", "beta", "lp",
              "perc", "uzl", "k0", "k1", "k2", "routing_k"]
BOUNDS = [(-2., 2.), (0.5, 8.), (0.7, 1.5), (0., 0.1), (0., 0.2),
          (50., 800.), (0.5, 5.), (0.2, 1.), (0.05, 5.), (0., 80.),
          (0.1, 0.95), (0.01, 0.5), (0.001, 0.15), (0.15, 1.)]
STATE_NAMES = ["snowpack_mm", "snow_liquid_mm", "soil_moisture_mm",
               "upper_storage_mm", "lower_storage_mm", "routing_storage_mm"]
FLUX_NAMES = ["melt_mm", "refreeze_mm", "actual_evaporation_mm", "runoff_mm",
              "effective_precipitation_mm", "water_balance_error_mm"]


@njit(cache=True)
def step(p, t, pet, par, state):
    tt, cfmax, sfcf, cfr, cwh, fc, beta, lp, perc, uzl, k0, k1, k2, kr = par
    snow, liquid, soil, upper, lower, route = state
    before = snow + liquid + soil + upper + lower + route
    rainfall = p if t >= tt else 0.0
    snowfall = p * sfcf if t < tt else 0.0
    snow += snowfall
    liquid += rainfall
    melt = min(snow, cfmax * max(t - tt, 0.0))
    snow -= melt
    liquid += melt
    freeze = min(liquid, cfr * cfmax * max(tt - t, 0.0))
    snow += freeze
    liquid -= freeze
    release = max(liquid - cwh * snow, 0.0)
    liquid -= release
    recharge = release * min(soil / fc, 1.0) ** beta
    soil += release - recharge
    overflow = max(soil - fc, 0.0)
    soil -= overflow
    evap = min(soil, max(pet, 0.0) * min(soil / (lp * fc), 1.0))
    soil -= evap
    upper += recharge + overflow
    percolation = min(upper, perc)
    upper -= percolation
    lower += percolation
    q0 = min(upper, k0 * max(upper - uzl, 0.0))
    upper -= q0
    q1 = min(upper, k1 * upper)
    upper -= q1
    q2 = min(lower, k2 * lower)
    lower -= q2
    route += q0 + q1 + q2
    runoff = kr * route
    route -= runoff
    new = np.array([snow, liquid, soil, upper, lower, route])
    effective_p = rainfall + snowfall
    balance = before + effective_p - new.sum() - evap - runoff
    return new, np.array([melt, freeze, evap, runoff, effective_p, balance])


@njit(cache=True)
def simulate(p, t, pet, par, initial):
    states = np.empty((len(p), 6))
    fluxes = np.empty((len(p), 6))
    state = initial.copy()
    for i in range(len(p)):
        state, flux = step(p[i], t[i], pet[i], par, state)
        states[i] = state
        fluxes[i] = flux
    return states, fluxes


@njit(cache=True)
def branches(p, t, pet, par, initial_states):
    """Run each issue/member trajectory from its own causal HBV restart."""
    n, horizon = p.shape
    states = np.empty((n, horizon, 6))
    fluxes = np.empty((n, horizon, 6))
    for i in range(n):
        state = initial_states[i].copy()
        for lead in range(horizon):
            state, flux = step(p[i, lead], t[i, lead], pet[i, lead], par, state)
            states[i, lead] = state
            fluxes[i, lead] = flux
    return states, fluxes


def kge(obs, sim):
    mask = np.isfinite(obs) & np.isfinite(sim)
    o, s = np.asarray(obs)[mask], np.asarray(sim)[mask]
    if len(o) < 3 or np.std(o) < 1e-12 or np.std(s) < 1e-12 or abs(o.mean()) < 1e-12:
        return float("nan")
    r = np.corrcoef(o, s)[0, 1]
    return float(1 - np.sqrt((r - 1)**2 + (s.std() / o.std() - 1)**2 + (s.mean() / o.mean() - 1)**2))


def initial_state(par):
    # Assumed inventories; excluded warm-up lets stores spin up without Q input.
    return np.array([0., 0., par[5] / 2, 10., 30., 0.])


def calibrate(p, t, pet, q, mask, area_km2, config):
    if mask.sum() < 365:
        raise ValueError("HBV calibration needs at least 365 observed, post-warmup days")
    conversion = area_km2 / 86.4  # mm/day over km2 -> m3/s
    history = []
    def objective(par):
        _, flux = simulate(p, t, pet, par, initial_state(par))
        score = kge(q[mask], flux[mask, 3] * conversion)
        return 10.0 if not np.isfinite(score) else 1 - score
    def callback(x, convergence):
        history.append({"generation": len(history) + 1,
                        "kge": float(1 - objective(x)), "convergence": float(convergence)})
    result = differential_evolution(
        objective, BOUNDS, seed=config["seed"], popsize=config["de_popsize"],
        maxiter=config["de_maxiter"], tol=config["de_tolerance"], polish=False,
        workers=1, updating="immediate", callback=callback)
    return result.x, {"parameters": dict(zip(PARAMETERS, result.x.tolist())),
                      "calibration_kge": float(1 - result.fun), "evaluations": int(result.nfev),
                      "generations": int(result.nit), "converged": bool(result.success),
                      "message": str(result.message), "generation_history": history}
