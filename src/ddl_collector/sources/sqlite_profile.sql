-- Read-only profiling templates for the SQLite source family.
--
-- Each template starts with a `-- name:` marker. Placeholders in braces take identifiers
-- (table and column names) that the caller has already quoted; no data value is ever
-- interpolated. Every statement is a SELECT and runs on a read-only connection.

-- name: row_count
SELECT COUNT(*) FROM {table};

-- name: column_stats
SELECT COUNT(*) - COUNT({column}), COUNT(DISTINCT {column}) FROM {table};

-- name: key_duplicate_groups
SELECT COUNT(*) FROM (
    SELECT 1 FROM {table} WHERE {key_not_null} GROUP BY {key_columns} HAVING COUNT(*) > 1
);

-- name: fk_child_null_rows
SELECT COUNT(*) FROM {child} AS c WHERE NOT ({child_not_null});

-- name: fk_orphan_rows
SELECT COUNT(*) FROM {child} AS c
WHERE {child_not_null}
  AND NOT EXISTS (SELECT 1 FROM {parent} AS p WHERE {join_condition});

-- name: fk_unreferenced_parent_rows
SELECT COUNT(*) FROM {parent} AS p
WHERE NOT EXISTS (SELECT 1 FROM {child} AS c WHERE {join_condition});

-- name: fk_max_children_per_parent
SELECT COALESCE(MAX(n), 0) FROM (
    SELECT COUNT(*) AS n FROM {child} AS c WHERE {child_not_null} GROUP BY {child_columns}
);
