# Evidence table: clinic no-shows and SMS reminders

Built by `python run_pipeline.py` from the Vitoria (Brazil) public clinic appointment extract, appointment dates 2016-04-29 to 2016-06-08. Pooled = all weeks added up before dividing.

## Project KPI and supporting metrics

| #   | Metric                                                                          | Pooled (6 weeks)                                                                                       | Decision trigger                                           |
|:----|:--------------------------------------------------------------------------------|:-------------------------------------------------------------------------------------------------------|:-----------------------------------------------------------|
| KPI | No-show rate of appointments booked 1+ days ahead                               | 28.52%                                                                                                 | any week above 30%: review that week                       |
| S1  | Reminder coverage: eligible appointments (booked 3+ days ahead) that got an SMS | 59.12% (81.69% on normal days)                                                                         | any week below 70%, or a day below 50%: ask the SMS vendor |
| S2  | Reminder effect at the same lead time (no-show points saved by an SMS)          | 5.4 pts (outage days vs normal days: 4.3 pts)                                                          | below 1 pt: the reminder is not worth scaling              |
| S3  | Share of no-shows from patients with 2+ no-shows in the window                  | 35.3% (from 5.17% of patients)                                                                         | used to size a call list                                   |
| S4  | Advance bookings made more than 14 days ahead                                   | 38.56%                                                                                                 | context for slot policy                                    |
| Ops | Call list: advance bookings by patients with 2+ earlier no-shows                | 572 in the last week (~191 a day, ~2.9 per neighbourhood a day); 38.48% of all such bookings no-showed | sent to reception weekly                                   |

## Why the plain SMS comparison is misleading

Read naively, SMS makes things worse: 27.57% no-show with an SMS vs 16.7% without. But nobody booked under 3 days ahead ever gets an SMS, and those bookings rarely no-show (same-day: 4.65%). Compared at the same lead time, SMS appointments no-show less:

| lead_band   |   appointments |   no_show_pct_with_sms |   no_show_pct_without_sms |   gap_points |
|:------------|---------------:|-----------------------:|--------------------------:|-------------:|
| 3-7 days    |          20247 |                  23.76 |                     26.59 |         2.83 |
| 8-14 days   |          12025 |                  28.11 |                     33.76 |         5.65 |
| 15-30 days  |          17371 |                  29.8  |                     36.87 |         7.07 |
| 31+ days    |          10378 |                  30.2  |                     37.53 |         7.32 |

Check that does not depend on who gets an SMS: on the 7 outage days no eligible appointment got a reminder. Same lead time, outage days vs normal days:

| lead_band   |   appointments |   no_show_pct_normal_days |   no_show_pct_outage_days |   gap_points |
|:------------|---------------:|--------------------------:|--------------------------:|-------------:|
| 3-7 days    |          20235 |                     24.42 |                     26.32 |         1.9  |
| 8-14 days   |          12016 |                     28.79 |                     34.61 |         5.83 |
| 15-30 days  |          17371 |                     31.19 |                     36.72 |         5.53 |
| 31+ days    |          10378 |                     31.66 |                     36.81 |         5.15 |

## No-show by lead time (all valid appointments)

| lead_band   |   appointments |   no_shows |   no_show_pct |
|:------------|---------------:|-----------:|--------------:|
| 0 same day  |          38562 |       1792 |          4.65 |
| 1-2 days    |          11938 |       2715 |         22.74 |
| 3-7 days    |          20247 |       5057 |         24.98 |
| 8-14 days   |          12025 |       3664 |         30.47 |
| 15-30 days  |          17371 |       5661 |         32.59 |
| 31+ days    |          10378 |       3425 |         33    |

## Returning patients: no-show % by earlier no-shows

| prior   |   appointments |   no_shows |   no_show_pct |
|:--------|---------------:|-----------:|--------------:|
| 0       |          20110 |       5290 |         26.31 |
| 1       |           7360 |       2400 |         32.61 |
| 2+      |           2318 |        892 |         38.48 |

## Weekly values

| week_start   |   open_days |   outage_days |   valid_appointments |   advance_booked |   kpi_no_show_pct |   reminder_coverage_pct |   booked_over_14_days_pct |   call_list_size | triggers_fired                             |
|:-------------|------------:|--------------:|---------------------:|-----------------:|------------------:|------------------------:|--------------------------:|-----------------:|:-------------------------------------------|
| 2016-04-25   |           1 |             0 |                 3235 |             2182 |             27.54 |                   78.75 |                     46.65 |                0 | none                                       |
| 2016-05-02   |           5 |             0 |                20949 |            13540 |             28.62 |                   81.05 |                     34.58 |               42 | none                                       |
| 2016-05-09   |           6 |             2 |                21721 |            14037 |             29.98 |                   46.98 |                     33.56 |              201 | reminder coverage below 70%                |
| 2016-05-16   |           5 |             5 |                21455 |            14183 |             30.6  |                    0    |                     37.45 |              455 | KPI above 30%; reminder coverage below 70% |
| 2016-05-23   |           2 |             0 |                 7918 |             4931 |             29.3  |                   83.04 |                     39.51 |              243 | none                                       |
| 2016-05-30   |           5 |             0 |                21657 |            14200 |             26.51 |                   82.5  |                     44.91 |              805 | none                                       |
| 2016-06-06   |           3 |             0 |                13586 |             8886 |             25.76 |                   81.51 |                     41.66 |              572 | none                                       |

## Context and data gaps

- Rain: rainy days (10 mm+, 2 days) averaged 18.88% no-show, dry days (19 days) 20.27%. No sign that rain matters, but 2 rainy days is too few to rule it out.
- Partial weeks: the first week has 1 open day (April 29) and the last week 3 (June 6-8).
- Reminder outage days: 2016-05-09, 2016-05-13, 2016-05-16, 2016-05-17, 2016-05-18, 2016-05-19, 2016-05-20.
- weekdays_without_appointments_explained: WARN (holidays: ['2016-05-26 Corpus Christi']; not explained: ['2016-05-23', '2016-05-27'])
- reminder_coverage_above_outage_level: WARN (7 appointment days under 50%: ['2016-05-09', '2016-05-13', '2016-05-16', '2016-05-17', '2016-05-18', '2016-05-19', '2016-05-20'])
