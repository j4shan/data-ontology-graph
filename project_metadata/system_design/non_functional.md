# System design: non-functional

## Capacity

| ID | Clause |
| --- | --- |
| 1.1 | The service keeps one published snapshot and its immutable search and navigation indexes resident. Evicting a disposable cache may change performance but never response semantics. Serves `product/non_functional.md#1.1`. |
| 1.2 | Search performs exact and prefix lookup over the static trie, intersects per-word lookups for a multi-word query, then filters, deduplicates, orders stably, and limits per kind, with no dedicated relevance-ranking structure. Serves `product/non_functional.md#5.1`. |
| 1.3 | Graph computation runs outside the request event loop, with bounded concurrent computations and cancellation support. Serves `product/non_functional.md#1.1`. |
| 1.4 | Connecting-subgraph search runs in time linear in the graph size and stops once the tree is settled, so nearby endpoints touch only their neighbourhood. Serves `product/non_functional.md#1.1`. |
| 1.5 | A ranked-path multiplicity filter prunes disallowed hops before expansion, without worsening asymptotic traversal time or space. Serves `product/non_functional.md#1.1`. |

## Resilience

| ID | Clause |
| --- | --- |
| 2.1 | Publication promotes a fully built and reload-validated candidate in one replacement, keeps a transient backup until success, and restores the prior artifact if promotion fails. Serves `product/non_functional.md#2.3`. |
| 2.2 | `launchd` starts the service at login and restarts it after an unexpected failure. Serves `product/non_functional.md#3.2`. |

## Security

| ID | Clause |
| --- | --- |
| 3.1 | Socket filesystem permissions restrict the service socket to the local user, and the service opens no network listener. Serves `product/non_functional.md#4.1`. |
| 3.2 | Accessors hold configuration and deployed location only. Preparation writes no credential into YAML, the survey, the decision log, generated commands, or other artifacts. Serves `product/non_functional.md#4.2`. |
| 3.3 | Source adapters open source databases read-only, and bundled profiling queries only read. Serves `product/non_functional.md#4.3`. |
| 3.4 | The collector verifies each source file's SHA-256 hash against Critic's `resources/data/SOURCES.md` before extraction and again before publication. Serves `product/non_functional.md#4.4`. |

## Observability

| ID | Clause |
| --- | --- |
| 4.1 | Validation findings name the invalid location and violated rule. Serves `product/non_functional.md#2.5`. |
| 4.2 | The build report lists every unknown typed claim and every deterministic rule violation, located by stable IDs, for the upstream preparation cycle. Serves `product/non_functional.md#2.5`. |

## Deployment

| ID | Clause |
| --- | --- |
| 5.1 | One singleton graph service runs per user as a user-owned `launchd` agent, loading the current artifact from one stable, caller-configured path. Serves `product/non_functional.md#3.2`. |
| 5.2 | The current graph artifact lives at a caller-supplied path outside this repository. Serves `product/non_functional.md#2.3`. |
| 5.3 | Production and local development use the same socket interface and process model. Serves `product/non_functional.md#5.2`. |
