# YAML Preparation Skill Product Requirements

## 1. Purpose and scope

This document defines the product requirements for the `ddl_collector` package and source-family
agent skills in the top-level `skills/` directory. They prepare finalized YAML for the graph
builder. A directory catalog has a
[`directory-manifest.yaml`](../../resources/schema/intermediary-directory.schema.json) beside its
`yaml/` directory and separate collection files inside that directory. The builder assembles those
files and validates the result against
[`intermediary.schema.json`](../../resources/schema/intermediary.schema.json). The graph builder
validates and consumes finalized YAML; it does not perform the upstream preparation described
here.

| ID | Requirement |
| --- | --- |
| 1.1.1 | A preparation skill must transform evidence about one supported data-source family into complete project-schema YAML. Static definitions are evidence, not an independently sufficient or authoritative description of business meaning. |
| 1.1.2 | The skill must maximize the value of collaboration between an AI agent and data-schema owners. A schema owner is typically a human expert who can confirm structural meaning, explain ambiguity, or state that the answer is unknown. |
| 1.1.3 | The skill must not invent business semantics or silently resolve an ambiguous decision. It must present the decision to a schema owner or record the knowledge as unknown when the target schema permits an explicit unknown. |
| 1.1.4 | The skill must preserve traceability from source evidence, direct data inspection, and human answers to the decisions used to produce the finalized YAML. |

## 2. Skill goals

| ID | Goal | Required outcome |
| --- | --- | --- |
| 2.1.1 | Parse static DDL resources | Extract the available dataset, column, constraint, comment, and relationship evidence without treating declared structure as complete business metadata. |
| 2.1.2 | Collect structural metadata insights | Guide the agent through a question-and-answer cycle with data-schema owners to confirm meaning, fill gaps, resolve ambiguity, or explicitly document an unknown. |
| 2.1.3 | Collect data statistics | Use bundled data-access tools to inspect the deployed data source and gather evidence needed to assess grain, identity, uniqueness, population coverage, multiplicity, and match existence. |

Processing a static data definition is only the starting point. The critical value proposition is
the skill's ability to guide an AI agent in combining three forms of evidence: static resources,
answers from data-schema owners, and statistics obtained by directly inspecting the deployed data
source.

## 3. Skill packaging and project structure

| ID | Requirement |
| --- | --- |
| 3.1.1 | The `ddl_collector` package must live beside the graph core and provide shared preparation tools; all data-source preparation skills must be tracked beneath the top-level `skills/` directory. |
| 3.1.2 | The project must use a one-skill-per-data-source-family structure. Each skill directory must contain the instructions and bundled resources for exactly one source family, such as SQLite. |
| 3.1.3 | Every skill directory must contain a `SKILL.md`. Its instructions must link to the target [`intermediary.schema.json`](../../resources/schema/intermediary.schema.json) and require the agent to consult that schema before preparing or validating YAML. |
| 3.1.4 | Each skill must bundle the tools needed for its three goals: a source-appropriate DDL parser, a readable and fillable survey template, and source-appropriate read-only query templates and commands. |
| 3.1.5 | A skill may reuse shared contracts or utilities, but it must not combine preparation logic for multiple data-source families into one skill. |

## 4. Evidence and authority

The preparation process uses the following evidence classes:

| Code | Evidence class | Role |
| --- | --- | --- |
| `S` | Static resource | DDL, schema dumps, comments, constraints, and other source definitions. |
| `H` | Schema-owner response | Business meaning, confirmed structure, accepted uncertainty, and waivers supplied through the survey. |
| `D` | Direct data inspection | Statistics and observations returned by bundled read-only queries and commands. |
| `R` | Schema rule | Values fixed or constrained by `intermediary.schema.json` and its provider-specific validation rules. |

| ID | Requirement |
| --- | --- |
| 4.1.1 | The skill must distinguish observed evidence from an interpretation or proposal made by the agent. |
| 4.1.2 | Static constraints may generate candidates and questions, but they must not by themselves establish business identities, dataset grain, semantic relationships, or population completeness. |
| 4.1.3 | Direct inspection must be read-only. Credentials must not be written to YAML, the survey, the decision log, generated commands, or other preparation artifacts. |
| 4.1.4 | Collected statistics are preparation evidence. Unless the target schema defines a field for a statistic, the skill must not add raw statistics or undeclared properties to the finalized YAML. |

## 5. YAML field-preparation strategy

### 5.1 General rules

| ID | Requirement |
| --- | --- |
| 5.1.1 | Before preparing YAML, the agent must inspect the target schema and use its current `required`, type, enumeration, cardinality, and `additionalProperties` rules. This section is guidance for the current schema and does not replace the machine-readable contract. |
| 5.1.2 | The skill must account for every field in the target schema, including nested and repeated fields, and distinguish required fields from optional fields. |
| 5.1.3 | A required field must be present in finalized YAML. When a required field supports an explicit `unknown` value, the skill must use it rather than infer an unsupported answer. When no valid unknown representation exists, the issue remains open and prevents finalization until a valid value is obtained. |
| 5.1.4 | An optional field must be populated only when supported by evidence. Otherwise, it must be omitted or retain the schema-defined empty default; the literal text `unknown` must not be used as a substitute unless the schema explicitly permits it. |
| 5.1.5 | Every physical source column must appear in the node's `columns` inventory by default. A column may be omitted only through a recorded decision. Every YAML column must exist in the deployed dataset, and every omitted source column must have a matching omission decision. |
| 5.1.6 | Lists of `dataset_columns` must use exact source names, contain no duplicates, and follow the canonical ordering required by the target schema and validators. |
| 5.1.7 | A finalized directory catalog must place `directory-manifest.yaml` beside its `yaml/` directory. The manifest must use schema version `"3"` and name, relative to `yaml/`, exactly one logical-identity file, one or more node files, and exactly one edge file. Every YAML file in the finalized directory must be listed once. |
| 5.1.8 | Each collection file must use schema version `"3"` and contain exactly its manifest-owned collection. Node files partition the assembled `nodes` list; `logical_identities` and `edges` must not be partitioned. |
| 5.1.9 | Manifest paths must be relative, remain within the finalized YAML directory after resolution, and name existing `.yaml` or `.yml` files. Preparation must reject absolute paths, parent traversal, symlink escapes, duplicate paths, missing files, and unlisted files. |

### 5.2 Field matrix

The evidence column identifies the normal starting evidence, not permission to resolve ambiguity
without consulting a schema owner.

| YAML path | Presence | Evidence | Preparation strategy |
| --- | --- | --- | --- |
| `directory-manifest.yaml.schema_version` | Required for directory input | `R` | Use `"3"`, matching every collection file and the assembled intermediary. |
| `directory-manifest.yaml.logical_identities` | Required for directory input | `R` | Name the only logical-identity collection file relative to the finalized YAML directory. |
| `directory-manifest.yaml.nodes[]` | Required for directory input; one or more unique paths | `R` | List each node collection file once, relative to the finalized YAML directory. |
| `directory-manifest.yaml.edges` | Required for directory input | `R` | Name the only edge collection file relative to the finalized YAML directory. |
| `schema_version` | Required in each collection file and the assembled intermediary | `R` | Use the constant `"3"`. |
| `logical_identities` | Required; non-empty | `S`, `H` | Build the registry from identities confirmed by a schema owner. DDL names and keys may suggest candidates only. |
| `logical_identities.<identity_id>` | Required map key | `H`, `R` | Assign a stable, non-empty identifier to each confirmed logical identity. Reuse the same identifier across all of its physical definitions. |
| `logical_identities.<identity_id>.name` | Required | `H` | Record the owner-confirmed business name. |
| `logical_identities.<identity_id>.description` | Optional | `H` | Record the supported business definition; otherwise omit it or leave the schema-defined empty value. |
| `logical_identities.<identity_id>.synonyms` | Optional | `H` | Record only confirmed alternate business terms. |
| `nodes` | Required; non-empty | `S`, `D` | Create one node for each addressable dataset included in the preparation scope. |
| `nodes[].node_id` | Required | `R` | Construct and maintain the stable identifier exactly as described by the `node_id` property in the target schema. |
| `nodes[].descriptor` | Required | `S`, `H` | Create the dataset-facing descriptive envelope. |
| `nodes[].descriptor.qualified_name` | Required | `S`, `D` | Record the deployed dataset's fully qualified name, not the path of a DDL or test fixture. |
| `nodes[].descriptor.display_name` | Required | `S`, `H` | Use the established human-readable name; ask the owner when source naming is unclear. |
| `nodes[].descriptor.description` | Optional | `H` | Record a supported description of the dataset's purpose and contents. |
| `nodes[].descriptor.synonyms` | Optional | `H` | Record confirmed alternate names for the dataset. |
| `nodes[].descriptor.tags` | Optional | `H` | Record confirmed classification or discovery tags. |
| `nodes[].accessor` | Required | `S`, `D`, `R` | Describe how an external tool locates the deployed dataset. Never include credentials. |
| `nodes[].accessor.schema_id` | Required | `R` | Use the registered accessor schema for the source family; the SQLite skill uses `accessor.sqlite.v1`. |
| `nodes[].accessor.properties` | Required | `S`, `D`, `R` | Populate every property required by the selected accessor subtype and no undeclared property. For SQLite, provide `host`, absolute `database_path`, `schema`, and `object`; `main` is the schema of a directly opened database file. |
| `nodes[].grain` | Required | `S`, `H`, `D` | Record the owner-confirmed row boundary as a grain object. Use the schema's explicit `unknown` value when the evidence cannot establish it. |
| `nodes[].grain.components` | Required when grain is an object; non-empty | `H`, `D` | Record the components that collectively define one dataset record. Different record boundaries require different nodes. |
| `nodes[].grain.components[].dataset_columns` | Required | `S`, `H`, `D` | Record the exact columns that realize the component and verify them against the column inventory. |
| `nodes[].grain.components[].identity_id` | Optional | `H` | Link the component to a registered identity only when that identity realization is confirmed. |
| `nodes[].grain.components[].description` | Optional | `H` | Explain a component when its meaning is supported and not evident from its identity reference. |
| `nodes[].grain.description` | Optional | `H` | Describe the collective row boundary when useful and supported. |
| `nodes[].columns` | Required; non-empty | `S`, `D` | Inventory every physical column by default and reconcile the inventory with the deployed dataset. |
| `nodes[].columns[].name` | Required | `S`, `D` | Preserve the exact physical column name. |
| `nodes[].columns[].description` | Optional | `S`, `H` | Use supported source documentation or an owner response; otherwise omit or leave empty. |
| `nodes[].columns[].value_description` | Optional | `H`, `D` | Describe the value domain or interpretation when established by an owner and, where useful, supported by profiling. |
| `nodes[].columns[].synonyms` | Optional | `H` | Record confirmed alternate business terms for the column. |
| `nodes[].entity_definitions` | Optional | `S`, `H`, `D` | Add a definition for each confirmed physical realization of a registered logical identity. Do not create one from name similarity alone. |
| `nodes[].entity_definitions[].identity_id` | Required | `H` | Reference an existing logical-identity registry key. |
| `nodes[].entity_definitions[].dataset_columns` | Required; non-empty | `S`, `H`, `D` | Record the complete, canonical physical column set that realizes the identity. |
| `nodes[].entity_definitions[].entity_universe` | Required | `H`, `D` | Record `complete`, `partial`, or `unknown` for this physical realization. Do not infer completeness merely from uniqueness. |
| `nodes[].entity_definitions[].entity_expression` | Optional | `S`, `H` | Record supported agent-facing expression labels without treating them as executable or validated code. |
| `nodes[].entity_definitions[].entity_metadata` | Optional | `S`, `H` | Record supported contextual properties needed to interpret the physical realization. |
| `edges` | Required; may be empty | `S`, `H`, `D` | Include every confirmed relationship in scope. DDL foreign keys create candidates, not automatic edges. |
| `edges[].endpoint_a`, `edges[].endpoint_b` | Required | `R` | Reference two different registered entity definitions of the same logical identity. |
| `edges[].endpoint_*.node_id` | Required | `R` | Reference an existing node. |
| `edges[].endpoint_*.identity_id` | Required | `H`, `R` | Reference the shared registered identity used by both endpoints. |
| `edges[].endpoint_*.dataset_columns` | Required; non-empty | `S`, `H`, `R` | Repeat the exact canonical column set of the referenced entity definition. |
| `edges[].a_to_b`, `edges[].b_to_a` | Required | `H`, `D` | Assess the relationship independently in both directions. |
| `edges[].*_to_*.multiplicity` | Required | `H`, `D` | Record `1:1`, `1:many`, `many:1`, `many:many`, or `unknown`, using uniqueness statistics as evidence rather than as unsupported semantic proof. |
| `edges[].*_to_*.match_existence` | Required | `H`, `D` | Record `always`, `optional`, or `unknown`, using coverage queries to test whether unmatched records exist. |

## 6. Human survey and question-and-answer cycle

| ID | Requirement |
| --- | --- |
| 6.1.1 | The skill must generate a readable and fillable Markdown survey in a temporary preparation workspace. A schema owner must be able to answer it without editing YAML. |
| 6.1.2 | Questions must be grouped by dataset and decision topic, deduplicated, and ordered so that answers about identities and grain can inform later relationship questions. |
| 6.1.3 | Every question must include a stable decision ID, affected YAML path or object, whether the value is required or optional, the question, available evidence, the agent's proposal or candidate choices when useful, a fillable answer area, an explicit unknown choice, and a rationale or reference area. |
| 6.1.4 | The skill must recognize ambiguity arising from conflicting sources, missing business meaning, incompatible statistics, or multiple plausible mappings. It must create a question rather than silently choosing among plausible answers. |
| 6.1.5 | After each response round, the skill must apply answered decisions, regenerate only the still-relevant open questions, and validate the updated YAML. The cycle continues until each decision is answered, explicitly unknown, waived, or blocks finalization. |
| 6.1.6 | The survey must not ask a human to restate facts already established deterministically by the target schema or direct source inspection unless conflicting evidence requires confirmation. |

## 7. Decision log and workspace lifecycle

| ID | Requirement |
| --- | --- |
| 7.1.1 | The decision log must record each stable decision ID, question, answer, status, affected YAML path or object, evidence references, rationale, and waiver. |
| 7.1.2 | Supported statuses must distinguish at least open, answered, unknown, waived, and blocking decisions. |
| 7.1.3 | During preparation, the survey, decision log, draft YAML, parsed DDL output, and collected statistics must live in a temporary preparation workspace. |
| 7.1.4 | Finalized YAML directories may contain only manifest-listed YAML collection files. The directory manifest and durable decision log must be stored beside, not inside, the finalized YAML directory. |
| 7.1.5 | Generated catalogs must be published in Critic at `resources/data/generated_catalogs/<catalog>/`, with `directory-manifest.yaml`, `yaml/` for finalized collection files, `decisions.md` for the durable decision log, and `provenance.yaml` beside `yaml/`. Critic reference catalogs remain human-authored gold. |

## 8. Bundled tool requirements

| ID | Tool | Requirement |
| --- | --- | --- |
| 8.1.1 | DDL parser | Parse the source family's static definitions into structured evidence while preserving source locations and unsupported constructs for agent review. |
| 8.1.2 | Survey template | Provide the fillable Markdown structure defined in Section 6 and support repeated review rounds without losing prior answers or decision IDs. |
| 8.1.3 | Query templates | Provide parameterized, read-only profiling queries for the source family, including row counts, null counts, distinctness and uniqueness, candidate-key checks, relationship coverage, and unmatched-record checks. |
| 8.1.4 | Commands | Provide commands that let the agent inspect the deployed source and run the bundled queries without embedding credentials or assuming that the DDL resource is the deployed database. |
| 8.1.5 | Validator | Validate every draft and finalized artifact against the referenced target schema and report actionable YAML locations and violated rules. |

## 9. Preparation workflow

| ID | Stage | Required behavior |
| --- | --- | --- |
| 9.1.1 | Initialize | Create an isolated temporary workspace, inspect the target schema, and record the source family and preparation scope. |
| 9.1.2 | Parse | Parse the static resources and retain source locations for extracted evidence and warnings. |
| 9.1.3 | Inspect | Use bundled commands and query templates to reconcile the deployed structure and collect relevant statistics. |
| 9.1.4 | Draft | Produce the manifest and collection-owned draft YAML from deterministic evidence and clearly supported decisions. |
| 9.1.5 | Inquire | Generate the fillable survey for gaps, conflicts, semantic decisions, and ambiguous candidates. |
| 9.1.6 | Iterate | Apply owner responses, update the decision log, collect additional evidence when needed, and repeat validation and inquiry. |
| 9.1.7 | Finalize | Finalize only when the manifest, collection files, and assembled intermediary validate; every required field has a valid value; omissions are documented; and no blocking decision remains. |

## 10. Acceptance criteria

| ID | Criterion |
| --- | --- |
| 10.1.1 | A source-specific skill package contains one `SKILL.md`, its DDL parser, its fillable survey template, and its query templates and commands. |
| 10.1.2 | The `SKILL.md` links to and explicitly requires consultation of the target intermediary schema. |
| 10.1.3 | Given static definitions with missing or ambiguous business semantics, the skill produces focused survey questions rather than unsupported YAML assertions. |
| 10.1.4 | Given a reachable data source, the skill can gather read-only structural statistics and retain them as decision evidence without adding undeclared YAML fields. |
| 10.1.5 | The finalized YAML passes schema and semantic validation, contains the complete physical-column inventory unless omissions are recorded, and contains no credentials. |
| 10.1.6 | An unanswered question is either represented by a schema-valid explicit unknown or remains a documented blocking decision; it is never silently resolved by the skill. |
