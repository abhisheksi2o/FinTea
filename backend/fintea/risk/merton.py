"""Merton (1974) structural model: solve for the unobservable asset value and asset volatility.

Given the market value of equity E, its volatility sigma_E, the default point F
(face value of debt), the risk-free rate r and the horizon T, the two equations

    E       = V N(d1) - F e^(-rT) N(d2)
    sigma_E = (V / E) N(d1) sigma_V
    d1      = [ln(V/F) + (r + sigma_V^2 / 2) T] / (sigma_V sqrt(T)),   d2 = d1 - sigma_V sqrt(T)

are solved for V and sigma_V by alternating a Newton step on V with a fixed-point
update of sigma_V. The solver is deliberately dependency free (no scipy) and
returns the residuals so the workbook can display them as a check; the workbook
itself recomputes d1, d2, the model equity value and equity volatility from the
solved V and sigma_V with live formulas.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


@dataclass
class MertonSolution:
    asset_value: float
    asset_vol: float
    d1: float
    d2: float
    equity_model: float          # E implied by (V, sigma_V) - should equal the input E
    equity_vol_model: float      # sigma_E implied by (V, sigma_V) - should equal the input sigma_E
    residual_equity: float       # relative residual
    residual_vol: float          # relative residual
    pd_risk_neutral: float       # N(-d2)
    iterations: int
    converged: bool
    message: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _equity(V: float, sV: float, F: float, r: float, T: float):
    sq = sV * math.sqrt(T)
    d1 = (math.log(V / F) + (r + 0.5 * sV * sV) * T) / sq
    d2 = d1 - sq
    E = V * norm_cdf(d1) - F * math.exp(-r * T) * norm_cdf(d2)
    return E, d1, d2


def solve_merton(E: float, sigma_E: float, F: float, r: float, T: float = 1.0,
                 tol: float = 1e-10, max_iter: int = 500) -> Optional[MertonSolution]:
    """Return the Merton solution, or None when the inputs make the model undefined (no debt, non-positive equity)."""
    if E <= 0 or F <= 0 or sigma_E <= 0 or T <= 0:
        return None
    # starting values: V = E + F, sigma_V from the naive leverage-weighted volatility
    V = E + F
    sV = max(sigma_E * E / (E + F), 1e-4)
    it = 0
    converged = False
    for it in range(1, max_iter + 1):
        # Newton on V for the equity equation, holding sigma_V fixed (dE/dV = N(d1))
        for _ in range(100):
            Em, d1, d2 = _equity(V, sV, F, r, T)
            g = Em - E
            dg = norm_cdf(d1)
            if dg < 1e-12:
                V = V * 1.5
                continue
            step = g / dg
            V_new = V - step
            if V_new <= F * 1e-6 or V_new <= 0:
                V_new = 0.5 * (V + max(F * 1e-6, E))
            if abs(V_new - V) <= tol * max(1.0, V):
                V = V_new
                break
            V = V_new
        Em, d1, d2 = _equity(V, sV, F, r, T)
        # fixed-point update of sigma_V from the volatility equation
        nd1 = norm_cdf(d1)
        if nd1 < 1e-12:
            sV_new = sV * 0.5
        else:
            sV_new = sigma_E * E / (V * nd1)
        sV_new = min(max(sV_new, 1e-5), 5.0)
        if abs(sV_new - sV) <= tol * max(1.0, sV):
            sV = sV_new
            converged = True
            break
        sV = 0.5 * sV + 0.5 * sV_new   # damped for stability
    Em, d1, d2 = _equity(V, sV, F, r, T)
    sE_model = V * norm_cdf(d1) * sV / Em if Em > 0 else float("nan")
    return MertonSolution(
        asset_value=V, asset_vol=sV, d1=d1, d2=d2, equity_model=Em, equity_vol_model=sE_model,
        residual_equity=(Em - E) / E, residual_vol=(sE_model - sigma_E) / sigma_E,
        pd_risk_neutral=norm_cdf(-d2), iterations=it, converged=converged,
        message="" if converged else "did not converge within the iteration limit; values are the last iterate",
    )


def naive_distance_to_default(E: float, F: float, sigma_E: float, mu: float, T: float = 1.0,
                              a: float = 0.05, b: float = 0.25) -> Optional[Dict[str, float]]:
    """Bharath & Shumway (2008) naive DD, for cross-checking the workbook formulas in tests."""
    if E <= 0 or F <= 0 or sigma_E <= 0:
        return None
    sD = a + b * sigma_E
    sV = E / (E + F) * sigma_E + F / (E + F) * sD
    dd = (math.log((E + F) / F) + (mu - 0.5 * sV * sV) * T) / (sV * math.sqrt(T))
    return {"sigma_d": sD, "sigma_v": sV, "dd": dd, "pd": norm_cdf(-dd)}
