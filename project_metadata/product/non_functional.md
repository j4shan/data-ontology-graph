# Product non-functional requirements

## Latency

| ID | Clause |
| --- | --- |
| 1.1 | A long-running graph-navigation request must not block unrelated clients' requests while the service handles concurrent callers. |
| 1.2 | For direct lookups whose work is proportional to their result, such as a dataset's edges and logical entity detail, the result-item limit bounds response size, not compute time. For ranked paths, the result-item limit also bounds the search. |

## Reliability

| ID | Clause |
| --- | --- |
| 2.1 | Accuracy of collected knowledge takes precedence over collection speed and refresh frequency in every release. Publication follows a controlled release process comparable to code deployment, not real-time configuration updates. |
| 2.2 | Every published artifact has passed rule-based validation of YAML syntax, required and optional fields, data types, allowed values, canonical forms, uniqueness, and reference integrity. |
| 2.3 | A failed validation, build, or replacement leaves the existing current artifact unchanged, and no replacement exposes a mixture of files from different builds. |
| 2.4 | Unification keeps physical dataset identity and unknown or unassessed knowledge, so it never implies unsupported equivalence or certainty. Publication never converts an explicit `unknown` into confirmed knowledge. |
| 2.5 | Collection and publication preserve uncertainty and surface conflicting or unsupported entity and relationship knowledge for validation before release. |
| 2.6 | Given known graph definitions, search, lookup, and navigation return the corresponding entity and relationship evidence and invent no unsupported knowledge. |
| 2.7 | Identical requests against the same snapshot return identically ordered responses. |
| 2.8 | Every accepted definition and schema change is reviewable, and a rebuild is reproducible from the source-controlled YAML definitions and their schemas. |

## Availability

| ID | Clause |
| --- | --- |
| 3.1 | Local agents read knowledge from an offline copy on the same machine, with no network dependency between agents and the knowledge service. |
| 3.2 | The local graph service runs on demand: the user or an agent starts and stops it, nothing starts it at login, and while it is started it restarts after an unexpected failure without manual action. |

## Security and privacy

| ID | Clause |
| --- | --- |
| 4.1 | Only the local user who owns the graph service can call it; the initial release has no network boundary. |
| 4.2 | No credential appears in a dataset accessor, YAML definition, survey, decision log, generated command, or other preparation artifact. |
| 4.3 | Preparation inspects source catalogs and profiling data read-only. |
| 4.4 | Preparation verifies the integrity of every source file before reading it. |

## Compatibility

| ID | Clause |
| --- | --- |
| 5.1 | The product supports hybrid estates with up to about 10,000 business entities, different storage vendors and source formats, and relationship links that cross those boundaries. |
| 5.2 | Agents integrate through one JSON-RPC 2.0 request/response tool interface over a Unix-domain socket, shared by production and development. |
| 5.3 | A new storage or access environment is supported by registering an accessor schema, without changing the universal dataset model. The first supported preparation source family is SQLite. |
