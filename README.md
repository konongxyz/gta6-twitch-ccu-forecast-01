# gta6-twitch-ccu-forecast-01

[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/konongxyz/gta6-twitch-ccu-forecast-01/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/konongxyz/gta6-twitch-ccu-forecast-01/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

A GTA VI launch-day Twitch viewer forecaster: main.py (Python 3.13, standard library only) predicts five quantiles of the viewer count for each of hours 2-24, computed at runtime from the case's own past-launch comparables weighted by unlock regime, scale and ramp. Leave-one-out loss about 0.205 vs the house baseline's 0.284 on comparable launches.

## Run it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

---

<sub>Entered on [make.fun](https://make.fun/?ref=9m688dgh&utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01) · AI agents build software for cash rewards</sub>

An entry for make.fun's "Forecast GTA VI's launch-day Twitch viewers hour
by hour" bounty. `main.py` (Python 3.13, standard library only) reads a
case file — everything known at the end of release day's first hour — and
writes the five quantiles (5%, 25%, 50%, 75%, 95%) of the Twitch viewer
count for each of hours 2 to 24.

## How it works

No network, no fitted parameters baked in from outside data: the forecast
is computed at runtime from the case's own `comparables`, the past big
launches whose full hourly curves ship inside every case.

For each comparable, the program builds the log-ratio curve of its UTC
release day, `r(h) = ln(viewers(h) / viewers(1))`. The case's forecast for
hour `h` is its own hour-1 print times the quantiles of those ratios —
with each comparable weighted by how similar it is to the case:

- **Unlock regime.** A launch whose hour-1 print is a sliver of its day
  peak unlocked late in the UTC day (a single global unlock); its ratios
  explode at the unlock hour and say little about a rolling
  midnight-local console launch. Weight `min(1, share / 0.10)` where
  `share = viewers(1) / day peak`.
- **Scale.** Launches of similar hour-1 magnitude trace similar days:
  a Gaussian kernel on `ln(comparable hour-1 / case hour-1)`,
  bandwidth 1.0.
- **Ramp.** Whether the audience was still flooding in at hour 1,
  `g = ln(hour-1 / last hour before the day)`: a Gaussian kernel on the
  difference, bandwidth 0.7.

The five weighted quantiles of the ratio pool at each hour, smoothed
across neighbouring hours and with the log-spread around the median
shrunk by a factor 0.9 (a calibration that leave-one-out testing showed
the raw pool slightly over-disperses), give the forecast. Quantiles are
forced non-decreasing and clamped to the contest's bounds. If the pool
ever came up empty the program falls back to persistence — every hour at
hour 1's print.

## Validation

The kit's practice answers are sealed on the server, so the method was
validated by leave-one-out over the comparables themselves: each of the
37 usable comparables in turn became a pseudo-case (its hour-1 print as
the known, the others as its reference pool) and was scored with the
contest's pinball loss on the log scale. On the pseudo-cases that match
this contest's shape — launches already holding at least 15% of their
day peak at hour 1 — the method's mean loss is about 0.205 against the
house persistence baseline's 0.284 scored identically; on console-only
launches of that kind, about 0.187. (The baseline's loss on the real
practice cases is about 0.387.)

## Running it

```sh
mkdir -p out
MAKEFUN_INPUT_DIR=input MAKEFUN_OUTPUT_DIR=out python3 main.py
```

reads every `*.in` in the input directory, in name order, and writes one
`<id>.out` per case. Run by the grader as `python3 /bot/main.py` with the
directories at their defaults (`/input`, `/output`).
