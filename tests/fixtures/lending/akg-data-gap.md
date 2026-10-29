# What is the total loan amount per region where the loan was disbursed?

**Objective:** Sum loan amounts grouped by disbursement region.

**Status:** draft · **Components:** 2

## Datasets

| Alias | Dataset | Source | Grain | Role |
| --- | --- | --- | --- | --- |
| loan | `lending.main.loan` | accessor.sqlite.v1 | loan_id | anchor |
| region | `lending.main.region` | accessor.sqlite.v1 | region_id | grouping |

### Columns

| Column | Description | Usage |
| --- | --- | --- |
| loan.amount | approved loan amount | measure |
| region.region_name | the region name | group |

## Data gaps

- **disbursement-region:** No relationship records the region where a loan was disbursed. The path loan -> account -> region carries the account's opening-branch region, a different role, so loan and region stay disconnected. Involves: loan, region.
