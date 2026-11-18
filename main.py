"""Hour-by-hour Twitch viewer forecast for a big game launch day.

The program reads one case file: everything known at the end of hour 1 of
the release day (that hour's viewer print included) plus a library of past
launches ("comparables") with their full hourly curves. It writes, for each
of hours 2..24, five quantiles of that hour's viewer count.

Method, in short:

* A launch day is summarised by two numbers that are known at forecast
  time: how far hour 1 sits below the previous day's peak (the unlock wave
  of a rolling midnight launch crests the day before, so hour 1 is often a
  dip), and how far hour 1 sits above the quiet pre-release baseline.
* Past launches whose two numbers resemble this launch's are pooled with
  Gaussian weights, and each future hour is forecast three ways from that
  pool: the weighted empirical quantiles of the hour's ratio to hour 1, a
  normal curve fitted to the same ratios, and the weighted quantiles of
  the hour's ratio to the previous day's peak, re-anchored to this launch.
  The three are averaged in log space and smoothed across neighbouring
  hours, which keeps any single noisy order statistic from dominating.

Only the Python standard library is used, there is no network access and
no randomness: two runs on the same case write identical bytes.
"""

import json
import math
import os
import statistics
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

INPUT_DIR = Path(os.environ.get("MAKEFUN_INPUT_DIR", "/input"))
OUTPUT_DIR = Path(os.environ.get("MAKEFUN_OUTPUT_DIR", "/output"))

LEVELS = [0.05, 0.25, 0.5, 0.75, 0.95]
Z_AT_LEVEL = [-1.6448536269514722, -0.6744897501960817, 0.0,
              0.6744897501960817, 1.6448536269514722]
IQR_TO_SIGMA = 1.3489795003921634

# Similarity weighting: distance in (dip depth, surge over baseline) space.
BANDWIDTH = 0.7
BASELINE_WEIGHT = 0.9
WEIGHT_FLOOR = 0.05
# Launches already under way by hour 1 carry the signal; tiny hour-1
# prints belong to launches whose unlock lands later in the UTC day.
MIN_POOL_HOUR1 = 10000
MIN_POOL_SIZE = 6


def parse_ts(text):
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def ts_key(moment):
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def hourly_map(rows):
    """Map an hourly row list to {timestamp string: viewers}."""
    table = {}
    for row in rows or []:
        viewers = row.get("viewers")
        stamp = row.get("from")
        if stamp is not None and viewers is not None:
            table[stamp] = viewers
    return table


def launch_shape(day_start, table):
    """Summarise one launch: hour 1, the day's curve, and shape features.

    Returns None when the launch has no usable hour-1 print. The features
    use only data up to the end of hour 1, mirroring what is knowable for
    the launch being forecast.
    """
    start = parse_ts(day_start)
    day = []
    for offset in range(24):
        day.append(table.get(ts_key(start + timedelta(hours=offset))))
    first = day[0]
    if first is None or first <= 0:
        return None
    before = []
    for back in range(1, 25):
        value = table.get(ts_key(start - timedelta(hours=back)))
        if value is not None:
            before.append(value)
    prior_peak = max(before) if before else first
    older = []
    for back in range(48, 337):
        value = table.get(ts_key(start - timedelta(hours=back)))
        if value is not None:
            older.append(value)
    baseline = statistics.median(older) if older else (statistics.median(before) if before else 1)
    dip = math.log(max(first, 1) / max(prior_peak, 1))
    surge = math.log(max(first, 1) / max(baseline, 1))
    return {"hour1": first, "day": day, "prior_peak": prior_peak,
            "dip": dip, "surge": surge}


def target_shape(case):
    """The same summary for the case being forecast, from its history."""
    start = parse_ts(case["day_start"])
    table = hourly_map(case.get("history_hourly"))
    if len(table) < 24:
        # Sparse or minute-level history: fold points into hourly means.
        buckets = {}
        for point in case.get("history") or []:
            stamp = point.get("at")
            viewers = point.get("viewers")
            if stamp is None or viewers is None:
                continue
            buckets.setdefault(stamp[:13] + ":00:00Z", []).append(viewers)
        for stamp, values in buckets.items():
            table.setdefault(stamp, sum(values) / len(values))
    known = next((row for row in case.get("known") or [] if row.get("hour") == 1), None)
    if known is None:
        return None
    first = max(known.get("viewers") or 0, 1)
    before = []
    for back in range(1, 25):
        value = table.get(ts_key(start - timedelta(hours=back)))
        if value is not None:
            before.append(value)
    prior_peak = max(before) if before else first
    older = []
    for back in range(48, 337):
        value = table.get(ts_key(start - timedelta(hours=back)))
        if value is not None:
            older.append(value)
    if older:
        baseline = statistics.median(older)
    elif before:
        baseline = statistics.median(before)
    else:
        baseline = 1
    return {"hour1": first, "prior_peak": prior_peak,
            "dip": math.log(max(first, 1) / max(prior_peak, 1)),
            "surge": math.log(max(first, 1) / max(baseline, 1))}


def weighted_quantile(pairs, tau):
    """Smallest value whose cumulative weight reaches tau of the total."""
    ordered = sorted(pairs)
    total = sum(weight for _, weight in ordered)
    if total <= 0:
        return None
    running = 0.0
    for value, weight in ordered:
        running += weight
        if running / total >= tau:
            return value
    return ordered[-1][0]


def pool_for(case, target):
    """Weighted pool of comparable launches similar to this case."""
    game_name = (case.get("game") or {}).get("name") or ""
    launches = []
    for comp in case.get("comparables") or []:
        unlock = str(comp.get("unlock") or "")
        if "not a launch" in unlock.lower():
            continue
        name = str(comp.get("name") or "")
        if game_name and name.startswith(game_name):
            continue
        shape = launch_shape(comp["day_start"], hourly_map(comp.get("hourly")))
        if shape is None:
            continue
        missing = sum(1 for value in shape["day"][1:] if value is None)
        if missing <= 6:
            launches.append(shape)
    for floor in (MIN_POOL_HOUR1, 1000, 0):
        pool = [shape for shape in launches if shape["hour1"] >= floor]
        if len(pool) >= MIN_POOL_SIZE or floor == 0:
            launches = pool
            break
    weighted = []
    for shape in launches:
        gap = math.sqrt((shape["dip"] - target["dip"]) ** 2
                        + (BASELINE_WEIGHT * (shape["surge"] - target["surge"])) ** 2)
        weight = math.exp(-(gap * gap) / (2 * BANDWIDTH * BANDWIDTH)) + WEIGHT_FLOOR
        weighted.append((shape, weight))
    return weighted


def forecast_hours(case, target, pool):
    """Log-quantile curves for hours 2..24, smoothed across neighbours."""
    reanchor = math.log(max(target["prior_peak"], 1) / max(target["hour1"], 1))
    raw = {}
    for hour in range(2, 25):
        by_first = []
        by_peak = []
        for shape, weight in pool:
            value = shape["day"][hour - 1]
            if value is None or value <= 0:
                continue
            by_first.append((math.log(value / shape["hour1"]), weight))
            by_peak.append((math.log(value / max(shape["prior_peak"], 1)), weight))
        if not by_first:
            raw[hour] = [0.0] * len(LEVELS)
            continue
        empirical = [weighted_quantile(by_first, tau) for tau in LEVELS]
        median = weighted_quantile(by_first, 0.5)
        low_q = weighted_quantile(by_first, 0.25)
        high_q = weighted_quantile(by_first, 0.75)
        sigma = max((high_q - low_q) / IQR_TO_SIGMA, 0.05)
        normal = [median + z * sigma for z in Z_AT_LEVEL]
        from_peak = [weighted_quantile(by_peak, tau) + reanchor for tau in LEVELS]
        raw[hour] = [(e + n + p) / 3 for e, n, p in zip(empirical, normal, from_peak)]
    smoothed = {}
    for hour in range(2, 25):
        total = [0.0] * len(LEVELS)
        count = 0
        for near in (hour - 1, hour, hour + 1):
            if near in raw:
                for idx in range(len(LEVELS)):
                    total[idx] += raw[near][idx]
                count += 1
        smoothed[hour] = [value / count for value in total]
    return smoothed


def round2(value):
    return math.floor(value * 100 + 0.5) / 100


def emit_row(p1, log_ratios):
    """Turn five log ratios into a clean, non-decreasing quantile row."""
    quantiles = []
    previous = 0.0
    for log_ratio in log_ratios:
        value = round2(p1 * math.exp(log_ratio))
        value = min(max(value, previous, 0.01), 1e9)
        quantiles.append(int(value) if float(value).is_integer() else value)
        previous = value
    return quantiles


def forecast_case(case):
    first_row = next((row for row in case.get("known") or [] if row.get("hour") == 1), None)
    if first_row is None:
        raise ValueError("case has no hour-1 print")
    p1 = max(first_row.get("viewers") or 0, 1)
    target = target_shape(case)
    pool = pool_for(case, target) if target is not None else []
    hours = []
    if pool:
        curves = forecast_hours(case, target, pool)
        for row in case["forecast"]:
            hours.append({"hour": row["hour"], "q": emit_row(p1, curves[row["hour"]])})
    else:
        # No usable comparables: hold hour 1 with a widening log spread.
        for row in case["forecast"]:
            spread = 0.35 * math.sqrt(row["hour"] - 1)
            hours.append({"hour": row["hour"],
                          "q": emit_row(p1, [z * spread for z in Z_AT_LEVEL])})
    return {"hours": hours}


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for path in sorted(INPUT_DIR.glob("*.in")):
        case = json.loads(path.read_text(encoding="utf-8"))
        result = forecast_case(case)
        text = json.dumps(result, separators=(",", ":")) + "\n"
        (OUTPUT_DIR / (path.stem + ".out")).write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
