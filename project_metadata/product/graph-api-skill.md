# Product requirements: graph API skill

In the skill context, an abstract knowledge graph (AKG) is a cut of a data knowledge graph—a conglomerate of dataset nodes, entity relationship edges, and data statistics provided by the data-ontology-graph service.

## Purpose

- **Tool discovery:** List the graph service API documentation with detailed descriptions of functionality and configurability.
- **Provide best practices:** Provide context management practices and an analytic workflow.

## Non-goals

The skill does not output queries or handle AKG -> query translation.

## Tool and API access

| ID | Clause |
| --- | --- |
| 1.1 | Provide detailed and up-to-date data-ontology-graph service API documentation. Show the response schema and all configurable parameters. |
| 1.2 | The skill cannot contain references to project source code. Required public contracts must exist in the skill directory. The AKG schema is an example. |
| 1.3 | The skill must not contain rules that restrict resource usage, such as API calls. |

## Distribution and Setup

| ID | Clause |
| --- | --- |
| 2.1 | The skill design follows the Agent Skills open standard. The dependencies of bundled tools must be specified in a setup section in skill.md. |
| 2.2 | The skill discovers the local graph service through a default service location known to both the skill and the service, without requiring the user to supply that location. |
| 2.3 | A future release will target a Model Context Protocol (MCP) server. |

## Best Practices for AI Agents

| ID | Clause |
| --- | --- |
| 3.1 | Capture graph API response payloads in temporary files. 
- File A: (1) The original question being analyzed. (2) A list (array) of logical entity names. 
- File B: Graph traversal request and response payloads. 1 API call per section. |
| 3.2 | Reference the temporary output from 3.1 to generate the AKG. |

Note: the graph model has no statistics fields. The metadata category is covered in future product roadmap.
