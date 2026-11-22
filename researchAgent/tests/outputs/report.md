# Test run

| case | result | status | counts | verdict |
|---|---|---|---|---|
| tokyo-5d-5000 | PASS | ok | F6 L12 A92 T1 | comfortable |
| cos-daytrip-500 | PASS | ok | F0 L0 A48 T1 | comfortable |
| europe-2w-10000 | PASS | ok | F10 L36 A257 T5 | very_tight |
| japan-month-500-impossible | PASS | infeasible | F6 L12 A92 T1 | likely_impossible |
| ukraine-3d-1000-hard | PASS | ok | F6 L12 A89 T1 | very_tight |
| solo-budget-cheap-regional | PASS | ok | F4 L12 A75 T1 | tight |
| tight-budget-borderline | PASS | ok | F3 L12 A83 T1 | very_tight |
| group-of-four | PASS | ok | F3 L12 A43 T2 | very_tight |
| ambiguous-destination | PASS | ok | F6 L12 A86 T1 | comfortable |
| remote-sparse-data | PASS | error | F0 L0 A0 T0 | unknown |
| invalid-past-date | PASS | error | F0 L0 A0 T0 | unknown |
| invalid-zero-budget | PASS | error | F0 L0 A0 T0 | unknown |
| non-usd-budget | PASS | ok | F6 L12 A55 T1 | tight |

## tokyo-5d-5000
- MANUAL: flight prices are within 30% of a manual Google Flights check

## tight-budget-borderline
- MANUAL: breakdown sums within 5% of estimated_minimum_total
