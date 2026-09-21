# Current Graph Artifact Publication

This specification records the initial-release build and publication contract for the generated
graph artifact. It is an implementation contract for the project build, not a product goal in the
root PRD.

## 1 Current-artifact boundary

1. The source-controlled repository contains one current generated graph artifact at a stable
   project path.
2. A successful publication replaces that artifact as one complete unit.
3. The application does not maintain prior-release directories, a release catalog, rollback
   metadata, or historical artifacts. Git history is the only history of the source-controlled
   artifact.
4. The artifact's schema version identifies its data contract; it is not an application-managed
   release identifier.

## 2 Validation boundary

1. Publication accepts only a finalized YAML directory that passes the builder's rule-based
   validation: YAML syntax, required and optional fields, data types, allowed values, canonical
   forms, uniqueness, and reference integrity.
2. Semantic validation of business meaning belongs to the upstream YAML-generator agent skill.
   The builder and publisher do not infer business meaning, classify semantic findings, or repair
   authored knowledge.
3. Explicit `unknown` and unassessed values that conform to the schema are valid inputs. The
   publisher does not convert them into confirmed knowledge.

## 3 Publication behavior

1. The publisher builds and validates a complete candidate before replacing the current artifact.
2. A failed validation, build, or replacement leaves the existing current artifact unchanged.
3. The replacement must not expose a mixture of files from different builds.
4. Publication does not create or retain a prior release for rollback.

## 4 Daemon lifecycle

The graph daemon loads the one current artifact from its stable path. The existing Python
`data-ontology-graph-launchd` command is extended to install, start, reload, report status for, and
uninstall the user-owned `launchd` service. A separate shell script is not required.

The command resolves the configured stable artifact path, verifies that the artifact exists and is
loadable, writes the `launchd` property list, invokes the required `launchctl` lifecycle operation,
and may call `graph.snapshot_info` to verify the running daemon. It does not search for the newest
artifact, compare versions or timestamps, follow a `latest` release pointer, or validate a release
manifest. `launchd` manages process lifecycle; neither it nor the application manages a graph-
release history.

## 5 Initial-release verification

Verification is limited to unit tests. Unit coverage verifies successful replacement, rejection of
invalid input, preservation of the current artifact after failure, prevention of mixed-build
output, daemon configuration against the stable artifact path, and construction of the expected
`launchctl` operations. Integration, deployment, historical-release, rollback, performance, and
AKG-benchmark tests are not initial-release gates.

## 6 Non-goals

- Application-managed release history, immutable version directories, rollback catalogs, release
  discovery, version resolution, and release-manifest validation.
- Semantic validation or correction of YAML knowledge.
- Performance measurement and downstream AKG evaluation.
