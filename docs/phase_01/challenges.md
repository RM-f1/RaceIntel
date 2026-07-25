# Challenges

## FastF1 Cache

Problem:
Initial session loading required downloading data.

Solution:
Enabled FastF1 caching.

Lesson:
Caching significantly reduces repeated loading times.

---

## Invalid Laps

Problem:
Fastest lap selection included inaccurate laps.

Solution:
Used pick_accurate() before selecting the fastest lap.

Lesson:
Motorsport timing data requires validation before analysis.

---

## Pit Laps

Problem:
Pit laps distorted average race pace.

Solution:
Excluded pit laps from pace statistics.

Lesson:
Race strategy events should be handled separately from representative race pace.

---

## Notebook Organization

Problem:
Large notebooks became difficult to maintain.

Solution:
Separated analysis into dedicated notebooks for laps, telemetry, and weather.

Lesson:
Modular notebooks improve readability and reproducibility.