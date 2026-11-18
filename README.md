[![make.fun · gta6-twitch-ccu-forecast-01](https://make.fun/badge/gta6-twitch-ccu-forecast-01.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![rank](https://make.fun/badge/gta6-twitch-ccu-forecast-01/RaihanPratama-comp/gta6-twitch-forecast/rank.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01/leaderboard?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)
[![reward](https://make.fun/badge/gta6-twitch-ccu-forecast-01/RaihanPratama-comp/gta6-twitch-forecast/reward.svg)](https://make.fun/bounty/gta6-twitch-ccu-forecast-01?utm_source=github&utm_medium=readme&utm_campaign=gta6-twitch-ccu-forecast-01)

# GTA VI Twitch CCU forecast

Forecasts, hour by hour, how many people watch Grand Theft Auto VI live on
Twitch over the 24 UTC hours of its release day (2026-11-19), from everything
recorded up to the end of the first hour.

`main.py` (Python 3.13, standard library only) reads a case from
`$MAKEFUN_INPUT_DIR` (default `/input`) and writes `$MAKEFUN_OUTPUT_DIR/<id>.out`
(default `/output`) with five quantiles (5%, 25%, 50%, 75%, 95%) for each of
hours 2..24.

The model pools past game launches whose early shape resembles this one —
how far hour 1 sits below the previous day's peak, and how far it sits above
the pre-release baseline — and averages three views of that pool per hour:
empirical log-ratio quantiles against hour 1, a normal fit to the same
ratios, and log-ratio quantiles against the previous day's peak, re-anchored.
Curves are smoothed across neighbouring hours. The program is deterministic
and runs offline in well under a second per case.

Entry for the make.fun competition `gta6-twitch-ccu-forecast-01`.
Licensed under MIT (see `LICENSE`).
