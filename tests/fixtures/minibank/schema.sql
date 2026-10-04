-- minibank: a small SQLite catalog for collector unit tests. Every identifier here belongs to
-- this catalog only. Tests build it into a temporary Critic-style source tree.

CREATE TABLE branch (
    branch_id INTEGER PRIMARY KEY,
    name      TEXT NOT NULL UNIQUE
);

CREATE TABLE customer (
    customer_id INTEGER PRIMARY KEY,
    branch_id   INTEGER NOT NULL REFERENCES branch (branch_id),
    segment     TEXT
);

CREATE TABLE account (
    account_id  INTEGER PRIMARY KEY,
    customer_id INTEGER REFERENCES customer (customer_id),
    opened      TEXT NOT NULL
);

CREATE TABLE account_note (
    account_id INTEGER NOT NULL REFERENCES account (account_id),
    note       TEXT
);

INSERT INTO branch VALUES (1, 'North'), (2, 'South'), (3, 'East');
INSERT INTO customer VALUES (10, 1, 'R'), (11, 1, 'B'), (12, 2, 'R');
INSERT INTO account VALUES (100, 10, '2020-01-01'), (101, 10, '2020-02-01'),
                           (102, 11, '2021-01-01'), (103, NULL, '2022-01-01');
INSERT INTO account_note VALUES (100, 'welcome'), (100, 'upgrade'), (101, 'welcome');
