# How many loans are there per region of the account's opening branch, including accounts with no loan?

**Objective:** Count loans by the opening region of their repayment account, keeping accounts without loans.

**Status:** draft · **Components:** 1

## Datasets

| Alias | Dataset | Source | Grain | Role |
| --- | --- | --- | --- | --- |
| loan | `lending.main.loan` | sqlite | loan_id | anchor |
| account | `lending.main.account` | sqlite | account_id | bridge |
| region | `lending.main.region` | sqlite | region_id | grouping |

### Columns

| Column | Description | Usage |
| --- | --- | --- |
| loan.loan_id | the id of the loan | count |
| loan.account_id | the account that repays the loan | — |
| account.account_id | the id of the account | — |
| account.region_id | region of the opening branch | — |
| region.region_id | the id of the region | — |
| region.region_name | the region name | group |

## Directed edges

### loan.account_id → account.account_id

- Every loan row matches exactly one account row.
- Each account row matches any number of loan rows; some match none.
- Keep unmatched rows of: account
- Note: account LEFT JOIN loan keeps accounts with no loan; they count as zero.

### account.region_id → region.region_id

- Each account row matches at most one region row; whether every account row matches is unknown.
- Each region row matches any number of account rows; some match none.

## Data gaps

- **region-match:** Whether every account matches a region is unknown, so accounts may drop out of the grouping. Involves: account, region.
