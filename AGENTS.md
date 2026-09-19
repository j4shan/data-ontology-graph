# Agent instructions

Persistent Cursor rules live in `.cursor/rules/`. Follow them in every session.

## Dev-database resource isolation

Authored overlay, annotation, and other fixture files that belong to a BIRD
Mini-Dev catalog must not share a file with another catalog.

- Put those assets under `resources/data/dev_overlays/<database>/`.
- `<database>` is the directory name under `resources/data/dev_databases/`.
- One overlay file and, when present, one annotations file per catalog.
- Every key and `edge_id` in a file must belong to that catalog only.
- Do not write overlays into the vendored `dev_databases/` SQLite tree.
- Current overlay fixtures are `student_club` and `financial` only. Do not
  reintroduce `superhero` or `toxicology` overlay entries.
