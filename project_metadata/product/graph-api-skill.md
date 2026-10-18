# Product requirements: graph API skill

## Tool and API access

| ID | Clause |
| --- | --- |
| 1.1 | Instructed tool calls are limited to the graph APIs and the Python scripts bundled with the skill. |
| 1.2 | Instructions cannot rely on source code access. |
| 1.3 | The skill is published and installed as a standard agent skill on Claude, Codex, and other AI agent systems. Using it requires no additional installation or environment setup. |

## Service discovery

| ID | Clause |
| --- | --- |
| 2.1 | The skill locates the local graph service without the user supplying its location. |
| 2.2 | The graph service runs on demand. The user or the agent starts and stops it, and it does not start automatically at login. |

## AKG guidelines

| ID | Clause |
| --- | --- |
| 3.1 | An AKG holds all the data that serves one objective; that objective is its relevance boundary. It is a forest of subgraphs of graph nodes and edges. |
| 3.2 | An AI agent builds the AKG incrementally from graph API responses, adding, removing, and checking for graph objects. Graph knowledge is immutable at runtime, so graph objects are never updated. |
| 3.3 | The AKG is structurally sound and consistently parseable by an LLM with tools. Minor deviations do not cause total failure, the agent may add custom fields, and node and edge properties are optional: the agent decides what to include for the problem. |
| 3.4 | The AKG includes canonical node and edge identifiers and data-source information, so that graph-knowledge provenance can be validated and the data system an agent must connect to can be identified. |
| 3.5 | The pillars are dataset nodes, relationships, and data statistics. Internal system attributes are excluded for readability, while the minimum object references are kept so that an agent can fetch more properties and navigate to related objects. |
| 3.6 | The immediate goal is stable editing and parsing correctness. A finalized AKG can be converted into other representations, such as input for SQL generation. |
| 3.7 | No person is involved while the AKG is built. People may validate a finalized AKG. |
