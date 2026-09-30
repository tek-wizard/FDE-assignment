# Metric definitions

All metrics are computed in SQL (`scripts/stage4_metrics.py`) on the SQLite model, per week (Monday start) and
pooled. "Valid" means the row passed every FAIL rule. "Pooled" means all weeks added up before dividing.
"Eligible" means booked 3+ days ahead, the only bookings that ever get an SMS.

## Project KPI: no-show rate of advance-booked appointments

```
valid appointments booked 1+ days ahead with no_show = 1
--------------------------------------------------------
valid appointments booked 1+ days ahead
```

Pooled: **28.52%** (20,522 of 71,959). All appointments together: 20.19%.

Why not the plain no-show rate: 35% of rows are same-day bookings (mostly walk-ins at the desk) with a 4.65%
no-show rate. They can't be reminded and almost always show up. If the share of walk-ins changes, the plain rate
moves even when nothing changed for booked patients. The KPI is about slots booked in advance, which is where
the waste is.

## Supporting metrics

| # | Metric | Formula | Link to the KPI | Pooled | Decision trigger |
|---|---|---|---|---|---|
| S1 | Reminder coverage | eligible valid appointments with SMS / eligible valid appointments | a reminder that isn't sent can't help | 59.12% (81.69% on normal days) | a week under 70%, or a day under 50%: ask the SMS vendor what failed |
| S2 | Reminder effect at the same lead time | for each lead band (3-7, 8-14, 15-30, 31+ days): no-show % without SMS - with SMS, weighted by the band's size | how many KPI points a reminder saves | 5.4 pts; outage days vs normal days: 4.3 pts | under 1 pt: don't scale reminders |
| S3 | Repeat no-show concentration | no-shows by patients with 2+ no-shows in the window / all no-shows (valid ids only) | if high, a targeted call is cheaper than messaging everyone | 35.3% from 5.17% of patients | none; sizes the call list |
| S4 | Long lead-time share | advance bookings made 15+ days ahead / advance bookings | these no-show most (33%) | 38.56% | none; context for slot policy |

Operational output (not a metric): the **call list**, meaning advance-booked appointments in the latest week for
patients with 2+ earlier no-shows. The latest week has 572 (about 3 per neighbourhood per day), and 38.5% of
bookings like these no-showed. Written to `data/processed/call_list.csv` only, because it has patient ids.

## Why S2 is computed this way

The plain comparison says SMS is harmful: 27.57% no-show with an SMS vs 16.70% without. That comparison mixes
two groups. Everyone without an SMS includes all same-day and 1-2 day bookings (low no-show). Everyone with an
SMS was booked 3+ days ahead (high no-show). Comparing inside each lead band removes that mix. SMS is better in
every band, by 2.8 to 7.3 points.

Selection could still be a problem: on normal days, the ~18% of eligible patients with no SMS may be different
(e.g. no phone on file). The outage days avoid that. On those 7 days nobody got an SMS, whoever they were.
Comparing outage days with normal days at the same lead time gives 4.3 points, close to 5.4. So the effect
isn't only selection.

## Why the trigger levels

- KPI above 30% in a week: the 6 weeks range from 25.8% to 30.6%. 30% is only crossed in the week with 5 outage
  days. It's a fixed level I chose, not a statistical one; 6 weeks is too few for a standard deviation.
- Coverage under 70% in a week, or under 50% on a day: normal days sit between 76% and 85%. An outage day is 0%.
  So 50% catches a failed day without false alarms, and 70% catches a week with 2 bad days.
- Reminder effect under 1 point: below that, the 1.8-point KPI gain from full coverage (see the scope doc) would
  shrink to about 0.3 points, not worth the SMS cost.

## Context (not metrics)

- No-show by lead band: 4.65% same day, 22.7% at 1-2 days, 25.0% at 3-7, 30.5% at 8-14, 32.6% at 15-30, 33.0% at 31+.
- Rain: 18.9% on rainy days (10 mm+, 2 days) vs 20.3% on dry days (19 days). Only 2 rainy days, so I
  can't say whether rain matters.
