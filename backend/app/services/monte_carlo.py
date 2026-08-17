"""Monte Carlo simulation engine for the risk portfolio.

Runs a Cholesky-correlated Monte Carlo over a portfolio of risks. Each risk
derives its loss model from its recorded likelihood/impact (heat) because the
database stores L x I scores, not dollar exposures:

  - occurrence probability p = f(likelihood level 1-5)
  - maximum exposure cap  = g(impact level 1-5)
  - severity distribution by heat tier:
      heat >= 10 -> LogNormal (heavy tail)
      heat 5-9   -> PERT (bounded, expert-style)
      heat < 5   -> Normal (frequent operational)

Correlation is applied through a Gaussian copula (Cholesky decomposition of a
PSD correlation matrix): base correlation between all pairs, boosted within
keyword clusters (cyber / vendor / DT-legacy / ops).

Each risk's marginal loss is zero-inflated: loss = 0 with probability (1 - p),
otherwise severity = F_sev^{-1}(v) for v re-scaled into the positive part.
This keeps occurrence AND severity correlated across risks via the same
correlated uniform u. Fully vectorized with numpy/scipy.
"""

import logging
from math import erf

import numpy as np

logger = logging.getLogger("stratroom.services.monte_carlo")

try:
    from scipy.stats import norm, beta as beta_dist
except Exception:  # pragma: no cover - numpy-only fallback
    norm = None
    beta_dist = None

LH_MAP = {
    "Almost Certain": 5,
    "Likely": 4,
    "Possible": 3,
    "Seldom": 2,
    "Happe very Rarely": 1,
    "Rare": 1,
}
IM_MAP = {
    "Catastrophic": 5,
    "Severe": 4,
    "Extreme": 4,
    "Major": 3,
    "Moderate": 2,
    "Minor": 1,
}

OCCURRENCE_BY_L = {1: 0.05, 2: 0.15, 3: 0.30, 4: 0.55, 5: 0.80}
CAP_BY_I = {1: 0.10e6, 2: 0.25e6, 3: 0.60e6, 4: 1.50e6, 5: 4.0e6}

DEFAULT_L = 3
DEFAULT_I = 3

BASE_CORR = 0.25
CLUSTER_BOOST = 0.25
CLUSTERS = {
    "cyber": ("cyber", "breach", "ransomware", "phishing", "it security", "network", "data", "hack"),
    "vendor": ("vendor", "supplier", "outsourc", "third party", "procurement", "concentrat"),
    "dt": ("dt", "digital", "legacy", "migration", "sprint", "transformation", "system", "platform"),
    "ops": ("operational", "ops", "fraud", "complianc", "regulatory", "safety", "emergency"),
}


def _split_heat(heat: int):
    """Best-effort L/I split of a 1-25 heat score (mirrors frontend _splitHeat)."""
    if not isinstance(heat, int) or not (1 <= heat <= 25):
        return None
    for l in range(5, 0, -1):
        i = round(heat / l)
        if l * i == heat and 1 <= i <= 5:
            return l, i
    l = int(np.ceil(np.sqrt(heat)))
    i = heat // l
    return l, (i if 1 <= i <= 5 else 1)


def parse_risk(row: dict) -> dict | None:
    """Extract a modelable risk (name, heat, likelihood, impact) from a raw row."""
    name = (row.get("name") or "").strip() or f"Risk #{row.get('id')}"

    heat = None
    try:
        heat = int(row.get("score"))
        if not (1 <= heat <= 25):
            heat = None
    except (TypeError, ValueError):
        heat = None

    l = LH_MAP.get((row.get("likeliHood") or "").strip())
    i = IM_MAP.get((row.get("impact") or "").strip())

    if heat is None:
        if l is None or i is None:
            return None
    else:
        split = _split_heat(heat)
        if l is None and split:
            l = split[0]
        if i is None and split:
            i = split[1]

    l = l or DEFAULT_L
    i = i or DEFAULT_I

    if heat is None:
        heat = l * i

    probability = OCCURRENCE_BY_L[l]
    cap = CAP_BY_I[i]

    if heat >= 10:
        distribution = "LogNormal"
        params = {"median": 0.25 * cap, "sigma": 0.75}
    elif heat >= 5:
        distribution = "PERT"
        params = {"min": 0.08 * cap, "mode": 0.25 * cap, "max": cap}
    else:
        distribution = "Normal"
        params = {"mean": 0.30 * cap, "std": 0.15 * cap}

    return {
        "name": name,
        "heat": heat,
        "likelihood": l,
        "impact": i,
        "probability": probability,
        "cap": cap,
        "distribution": distribution,
        "params": params,
    }


def _cluster_of(name: str) -> str | None:
    n = (name or "").lower()
    for key, words in CLUSTERS.items():
        if any(w in n for w in words):
            return key
    return None


def _build_correlation_matrix(names: list[str], boost: float = CLUSTER_BOOST) -> np.ndarray:
    n = len(names)
    c = np.full((n, n), BASE_CORR)
    np.fill_diagonal(c, 1.0)
    clusters = [_cluster_of(nm) for nm in names]
    for i in range(n):
        for j in range(i + 1, n):
            if clusters[i] and clusters[i] == clusters[j]:
                c[i][j] = c[j][i] = min(0.95, BASE_CORR + boost)
    return c


def _cholesky(names: list[str]) -> np.ndarray:
    """Cholesky factor of a PSD correlation matrix; reduces cluster boost if needed."""
    n = len(names)
    boost = CLUSTER_BOOST
    while boost >= 0:
        mat = _build_correlation_matrix(names, boost)
        try:
            return np.linalg.cholesky(mat)
        except np.linalg.LinAlgError:
            boost -= 0.05
    return np.linalg.cholesky(np.eye(n))


def _norm_cdf(x: np.ndarray) -> np.ndarray:
    if norm is not None:
        return norm.cdf(x)
    return 0.5 * (1.0 + np.vectorize(erf)(x / np.sqrt(2.0)))


def _severity_quantile(distribution: str, params: dict, u: np.ndarray) -> np.ndarray:
    """Inverse CDF of the severity distribution at quantiles u (0..1)."""
    v = np.clip(u, 1e-9, 1.0 - 1e-9)
    if distribution == "LogNormal":
        mu = np.log(params["median"])
        if norm is not None:
            return np.exp(mu + params["sigma"] * norm.ppf(v))
        return np.exp(mu + params["sigma"] * _inv_normal(v))
    if distribution == "Normal":
        if norm is not None:
            return params["mean"] + params["std"] * norm.ppf(v)
        return params["mean"] + params["std"] * _inv_normal(v)
    if distribution == "PERT":
        lo = params["min"]
        hi = params["max"]
        mode = params["mode"]
        if hi - lo <= 0:
            return np.full_like(u, lo)
        alpha = 1.0 + 4.0 * (mode - lo) / (hi - lo)
        beta_par = 1.0 + 4.0 * (hi - mode) / (hi - lo)
        if beta_dist is not None:
            return lo + (hi - lo) * beta_dist.ppf(v, alpha, beta_par)
        return _inv_beta_approx(v, alpha, beta_par, lo, hi)
    return np.full_like(u, 0.0)


def _inv_normal(p: np.ndarray) -> np.ndarray:
    """Acklam rational approximation of the inverse normal CDF (numpy-only fallback)."""
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2,
         1.38357751867269e2, -3.066479806614716e1, 2.506628277459239]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2,
         6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996,
         3.754408661907416]
    plow = 0.02425
    phigh = 1.0 - plow
    p = np.asarray(p, dtype=float)
    x = np.empty_like(p)
    lo = p < plow
    hi = p > phigh
    mid = ~(lo | hi)
    q = np.sqrt(-2.0 * np.log(np.clip(p[lo], 1e-300, 1.0)))
    x[lo] = (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    )
    q = p[mid] - 0.5
    r = q * q
    x[mid] = (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1.0
    )
    q = np.sqrt(-2.0 * np.log(np.clip(1.0 - p[hi], 1e-300, 1.0)))
    x[hi] = -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1.0)
    )
    return x


def _inv_beta_approx(u, alpha, beta_par, lo, hi):
    """numpy-only PERT fallback: scalar bisection on the regularized incomplete beta."""
    def _gammln(xx):
        cof = [76.18009172947146, -86.50532032941677, 24.01409824083091,
               -1.231739572450155, 0.1208650973866179e-2, -0.5395239384953e-5]
        x = xx - 1.0
        tmp = x + 5.5
        tmp = tmp - (x + 0.5) * np.log(tmp)
        ser = 1.000000000190015
        for j in range(6):
            x = x + 1.0
            ser = ser + cof[j] / x
        return -tmp + np.log(2.5066282746310005 * ser)

    def _betacf(xx, a, b):
        maxit = 200
        eps = 3e-12
        fpmin = 1e-300
        qab = a + b
        qap = a + 1.0
        qam = a - 1.0
        c = 1.0
        d = 1.0 - qab * xx / qap
        if abs(d) < fpmin:
            d = fpmin
        d = 1.0 / d
        h = d
        for m in range(1, maxit):
            m2 = 2 * m
            aa = m * (b - m) * xx / ((qam + m2) * (a + m2))
            d = 1.0 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1.0 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1.0 / d
            h = h * d * c
            aa = -(a + m) * (qab + m) * xx / ((a + m2) * (qap + m2))
            d = 1.0 + aa * d
            if abs(d) < fpmin:
                d = fpmin
            c = 1.0 + aa / c
            if abs(c) < fpmin:
                c = fpmin
            d = 1.0 / d
            delta = d * c
            h = h * delta
            if abs(delta - 1.0) < eps:
                break
        return h

    def _betai(xx, a, b):
        if xx <= 0.0:
            return 0.0
        if xx >= 1.0:
            return 1.0
        bt = np.exp(_gammln(a + b) - _gammln(a) - _gammln(b) +
                    a * np.log(xx) + b * np.log1p(-xx))
        if xx < (a + 1.0) / (a + b + 2.0):
            return bt * _betacf(xx, a, b) / a
        return 1.0 - bt * _betacf(1.0 - xx, b, a) / b

    uf = np.asarray(u, dtype=float)
    res = np.empty_like(uf)
    a = float(alpha)
    b = float(beta_par)
    for idx, target in enumerate(uf.ravel()):
        lo_q, hi_q = 0.0, 1.0
        for _ in range(60):
            mid = 0.5 * (lo_q + hi_q)
            if _betai(mid, a, b) < target:
                lo_q = mid
            else:
                hi_q = mid
        res.ravel()[idx] = 0.5 * (lo_q + hi_q)
    return lo + (hi - lo) * res.reshape(np.shape(u))


def select_portfolio(risks: list[dict], limit: int = 8) -> list[dict]:
    """Top-N risks by heat; falls back to all if fewer available."""
    ordered = sorted(risks, key=lambda r: (r["heat"], r["name"]), reverse=True)
    return ordered[:limit]


def run_simulation(risks: list[dict], runs: int = 10000, confidence: float = 0.95) -> dict:
    """Run the correlated Monte Carlo and return summary metrics."""
    portfolio = select_portfolio(risks, 8)
    n = len(portfolio)
    if n == 0:
        raise ValueError("No modelable risks to simulate.")

    names = [r["name"] for r in portfolio]
    p = np.array([r["probability"] for r in portfolio])
    cap = np.array([r["cap"] for r in portfolio])

    chol = _cholesky(names)

    rng = np.random.default_rng()
    z = rng.standard_normal((n, runs))
    x = chol @ z
    u = _norm_cdf(x)

    losses = np.zeros((n, runs))
    for i, r in enumerate(portfolio):
        sev = np.minimum(_severity_quantile(r["distribution"], r["params"], u[i]), cap[i])
        zero_threshold = 1.0 - p[i]
        losses[i] = np.where(u[i] < zero_threshold, 0.0, sev)

    total = losses.sum(axis=0)
    var = float(np.percentile(total, confidence * 100.0))
    cvar = float(total[total >= var].mean()) if np.any(total >= var) else var
    expected = float(total.mean())
    p99 = float(np.percentile(total, 99.0))
    exposure = float(cap.sum())
    resilience = 100.0 * (1.0 - expected / exposure) if exposure > 0 else 0.0

    return {
        "runs": runs,
        "confidence": confidence,
        "correlated": True,
        "expected_loss": round(expected, 2),
        "var": round(var, 2),
        "cvar": round(cvar, 2),
        "p99": round(p99, 2),
        "resilience": round(resilience, 2),
        "total_exposure": round(exposure, 2),
        "portfolio": [
            {
                "name": r["name"],
                "heat": r["heat"],
                "likelihood": r["likelihood"],
                "impact": r["impact"],
                "probability": r["probability"],
                "cap": r["cap"],
                "distribution": r["distribution"],
            }
            for r in portfolio
        ],
    }
