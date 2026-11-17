"""Forecast a game launch day's Twitch viewers, hour by hour.

Entry for make.fun's gta6-twitch-ccu-forecast-01 (program/v1). The program
is run once per case in a sandbox with no network: it reads the case JSON
(every *.in file in $MAKEFUN_INPUT_DIR, else /input) and writes one
<id>.out per case to $MAKEFUN_OUTPUT_DIR (else /output), holding the five
quantiles (0.05, 0.25, 0.5, 0.75, 0.95) of each of hours 2..24 of the
release day. Python 3.13, standard library only, fully deterministic.

Method — everything is computed at runtime from the case's own data:

  A launch day's shape is forecast from the case's `comparables`, the past
  big launches whose full hourly curves ship inside the case. For each
  comparable we take the log ratio of every release-day hour to that
  launch's own hour-1 print, r_c(h) = ln(v_c(h) / v_c(1)). The case's hour
  h forecast is then its own hour-1 print times the quantiles of those
  ratios across comparables — but not every past launch is equally
  informative about this one, so each comparable is weighted by how
  similar it is to the case at hand:

  * unlock regime — a comparable whose hour-1 print is only a sliver of
    its day peak unlocked late in the UTC day (a single global PC unlock,
    say), and its ratios explode at the unlock hour; a rolling
    midnight-local console launch, like this case, already holds a real
    share of its day at hour 1. Weight: min(1, share / 0.10) with
    share = v_c(1) / max_h v_c(h).
  * scale — launches of a similar hour-1 magnitude trace similar days.
    Weight: a Gaussian kernel on ln(v_c(1) / p1) with bandwidth 1.0.
  * ramp — whether the audience was still flooding in at the day's first
    hour, g = ln(p1 / v(-1)) with v(-1) the last hour before the day.
    Weight: a Gaussian kernel on g_c - g with bandwidth 0.7.

  The weighted quantiles of the ratios at each hour are smoothed across
  neighbouring hours, their log-spread around the median is shrunk by a
  factor 0.9 (leave-one-out testing showed the raw pool slightly
  over-disperses), and the result, exponentiated and scaled by the case's
  hour-1 print, is the forecast. A comparable with no usable release day
  (the case's own category history before release, for one) never enters
  the pool, and if the pool somehow comes up empty the program falls back
  to persistence: every hour at hour 1's print.
"""

import json
import math
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# The grader runs python3 -P -s, which keeps this file's directory off
# sys.path; put it back first so sibling modules would import.
sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
HOURS = list(range(2, 25))
HOUR = timedelta(hours=1)

# Weighting constants (chosen by leave-one-out validation over the
# comparables themselves; see README.md).
SHARE_FULL = 0.10     # hour-1 share of day peak at which regime weight is 1
BW_SCALE = 1.0        # kernel bandwidth on ln(hour-1 ratio), scale match
BW_RAMP = 0.7         # kernel bandwidth on the ramp feature g
SPREAD_SHRINK = 0.9   # the raw pool slightly over-disperses; shrink its
                      # log-spread around the median by this factor
SMOOTH_SIDE = 0.25    # weight of each neighbour hour when smoothing a
                      # quantile curve across the day
Q_MIN = 0.01          # output bounds: every quantile in (0, 1e9]
Q_MAX = 1_000_000_000.0


def parse_ts(text):
    """An ISO 8601 UTC timestamp as an aware datetime."""
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def hour1_print(case):
    """The case's hour-1 print (a print below 1 counts as 1)."""
    for row in case.get("known", []):
        if row.get("hour") == 1:
            return max(1.0, float(row["viewers"]))
    day_start = parse_ts(case["day_start"])
    for row in case.get("history_hourly") or []:
        if parse_ts(row["from"]) == day_start:
            return max(1.0, float(row["viewers"]))
    return 1.0


def last_hour_before(case):
    """Viewers in the hour just before the case's day, or None.

    Read from history_hourly when the case carries it, else from the raw
    history points inside that hour.
    """
    day_start = parse_ts(case["day_start"])
    want = day_start - HOUR
    for row in case.get("history_hourly") or []:
        if parse_ts(row["from"]) == want:
            return float(row["viewers"])
    pts = [float(p["viewers"]) for p in case.get("history") or []
           if want <= parse_ts(p["at"]) < day_start]
    return sum(pts) / len(pts) if pts else None


def ramp_feature(p1, v_prev):
    """g = ln(p1 / v(-1)): how hard the audience was still arriving."""
    if v_prev is None or v_prev <= 0:
        return 0.0
    return math.log(p1 / v_prev)


def comparable_curve(comp):
    """One comparable's release day, or None when it has no usable day.

    Returns (ratios, p1, share, g): ratios maps hour 2..24 to
    ln(v(h)/v(1)) of the comparable's own UTC release day, share is
    v(1)/peak of that day, g its ramp feature.
    """
    try:
        day_start = parse_ts(comp["day_start"])
    except (KeyError, TypeError, ValueError):
        return None
    day = {}
    prev = None
    for point in comp.get("hourly") or []:
        try:
            at = parse_ts(point["from"])
            viewers = float(point["viewers"])
        except (KeyError, TypeError, ValueError):
            continue
        idx = (at - day_start).total_seconds() / 3600.0
        if idx == int(idx):
            idx = int(idx)
            if 0 <= idx < 24:
                day[idx + 1] = viewers
            elif idx == -1:
                prev = viewers
    if day.get(1) is None or len(day) < 20:
        return None
    p1 = max(1.0, day[1])
    peak = max(day.values())
    if peak <= 0:
        return None
    ratios = {h: math.log(max(1.0, day[h]) / p1) for h in HOURS if h in day}
    if len(ratios) < 20:
        return None
    return ratios, p1, p1 / peak, ramp_feature(p1, prev)


def weight(comp, p1, g):
    """How much one comparable's day should count for this case."""
    _, c_p1, share, c_g = comp
    w = min(1.0, share / SHARE_FULL)
    d = math.log(c_p1 / p1) / BW_SCALE
    w *= math.exp(-0.5 * d * d)
    d = (c_g - g) / BW_RAMP
    w *= math.exp(-0.5 * d * d)
    return w


def weighted_quantile(pairs, tau):
    """The tau quantile of (value, weight) pairs, CDF-interpolated."""
    pairs = sorted(pairs)
    total = sum(w for _, w in pairs)
    if total <= 0:
        return None
    acc = 0.0
    for i, (value, w) in enumerate(pairs):
        acc += w
        if acc / total >= tau:
            if i == 0:
                return value
            prev_value, prev_w = pairs[i - 1]
            prev_cdf = (acc - w) / total
            frac = (tau - prev_cdf) / (w / total) if w > 0 else 0.0
            return prev_value + frac * (value - prev_value)
    return pairs[-1][0]


def round2(x):
    """x rounded to 2 decimals, half up; a whole number stays whole."""
    value = math.floor(x * 100 + 0.5) / 100
    return int(value) if float(value).is_integer() else value


def smooth(curve):
    """One [1/4, 1/2, 1/4] pass over a {hour: value} curve, edges held."""
    out = {}
    for h in HOURS:
        acc = curve[h] * (1 - 2 * SMOOTH_SIDE if 2 < h < 24 else 1 - SMOOTH_SIDE)
        wt = 1 - 2 * SMOOTH_SIDE if 2 < h < 24 else 1 - SMOOTH_SIDE
        if h > 2:
            acc += SMOOTH_SIDE * curve[h - 1]
            wt += SMOOTH_SIDE
        if h < 24:
            acc += SMOOTH_SIDE * curve[h + 1]
            wt += SMOOTH_SIDE
        out[h] = acc / wt
    return out


def clean(qs):
    """Quantiles in viewers: rounded, non-decreasing, inside the bounds."""
    out = []
    for v in qs:
        v = round2(min(Q_MAX, max(Q_MIN, v)))
        if out and v < out[-1]:
            v = out[-1]
        out.append(v)
    return out


def forecast_case(case):
    """The forecast document for one case: {"hours": [...23 rows...]}."""
    p1 = hour1_print(case)
    g = ramp_feature(p1, last_hour_before(case))
    pool = []
    for comp in case.get("comparables") or []:
        curve = comparable_curve(comp)
        if curve is not None:
            pool.append((curve, weight(curve, p1, g)))
    usable = pool and sum(w for _, w in pool) > 1e-9
    # Raw log-ratio quantiles per hour.
    logq = {}
    for h in HOURS:
        if usable:
            pairs = [(c[0][h], w) for c, w in pool if h in c[0]]
            logq[h] = [weighted_quantile(pairs, tau) for tau in LEVELS]
        else:
            logq[h] = [0.0] * len(LEVELS)  # persistence fallback: ratio 1
    # Smooth each quantile's curve across neighbouring hours, then shrink
    # the spread around the median (the pool over-disperses slightly).
    for i in range(len(LEVELS)):
        col = smooth({h: logq[h][i] for h in HOURS})
        for h in HOURS:
            logq[h][i] = col[h]
    rows = []
    for h in HOURS:
        med = logq[h][2]
        qs = [p1 * math.exp(med + SPREAD_SHRINK * (v - med)) for v in logq[h]]
        rows.append({"hour": h, "q": clean(qs)})
    return {"hours": rows}


def persistence_doc(case):
    """Every hour at hour 1's print: the never-invalid last resort."""
    try:
        p1 = hour1_print(case)
    except Exception:
        p1 = 1.0
    return {"hours": [{"hour": h, "q": clean([p1] * len(LEVELS))}
                      for h in HOURS]}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        try:
            doc = forecast_case(case)
        except Exception:
            doc = persistence_doc(case)
        out = json.dumps(doc, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / f"{path.stem}.out").write_text(out, encoding="utf-8")


if __name__ == "__main__":
    main()
