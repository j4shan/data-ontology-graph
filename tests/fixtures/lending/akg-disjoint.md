# List each loan with its repayment account, and separately list customers with their home region.

**Objective:** Two disjoint facts: loans by repayment account, and customers by home region.

**Status:** draft · **Components:** 2

## Datasets

| Alias | Dataset | Source | Grain | Role |
| --- | --- | --- | --- | --- |
| loan | `lending.main.loan` | sqlite | loan_id | anchor |
| account | `lending.main.account` | sqlite | account_id | — |
| customer | `lending.main.customer` | sqlite | customer_id | anchor |
| region | `lending.main.region` | sqlite | region_id | — |

### Columns

| Column | Description | Usage |
| --- | --- | --- |
| loan.loan_id | the id of the loan | output |
| account.account_id | the id of the account | output |
| customer.customer_id | the id of the customer | output |
| region.region_name | the region name | output |

## Directed edges

### loan.account_id → account.account_id

- Every loan row matches exactly one account row.
- Each account row matches any number of loan rows; some match none.

### customer.region_id → region.region_id

- Every customer row matches exactly one region row.
- Each region row matches any number of customer rows; some match none.
