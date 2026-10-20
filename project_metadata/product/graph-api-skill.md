# Product requirements: graph API skill

An abstract knowledge graph (AKG) is the subset of graph datasets and relationships an agent selects for one objective, together with the relevant graph properties and statistics.

## Purpose

- **Tool discovery:** List the graph service application programming interface (API) definitions and tell the agent which tools can access data graph knowledge and mutate an AKG.
- **Workflow instructions:** Provide a standard procedure for incrementally collecting and composing data knowledge into an AKG.

## Non-goals

The skill does not translate an AKG into a query language.

## Tool and API access

| ID | Clause |
| --- | --- |
| 1.1 | The skill limits instructed tool calls to graph APIs and the Python tools bundled with the skill. |
| 1.2 | The skill instructions do not rely on access to project source code. |

## Distribution and setup

| ID | Clause |
| --- | --- |
| 1.3 | The skill follows the Agent Skills open standard, bundles Python tools, and is published and installed as a standard agent skill on Claude, Codex, and other artificial intelligence (AI) agent systems. Using the skill requires no additional installation or environment setup. |
| 1.4 | The skill does not bundle tools that mutate AKGs; AKG mutation tools belong to the graph APIs. |
| 2.1 | The skill discovers the local graph service through a default service location known to both the skill and the service, without requiring the user to supply that location. |
| 2.3 | A future release will target a Model Context Protocol (MCP) server. |

## AKG guidelines

| ID | Clause |
| --- | --- |
| 3.1 | The skill instructs the agent to include all data that serves one objective; that objective is the AKG's relevance boundary. An AKG consists of subgraphs of graph nodes and edges that may be disconnected or contain cycles. |
| 3.2 | The skill instructs the agent to build an AKG incrementally through graph APIs that add and remove AKG elements and check whether an element is present in the AKG. The agent preserves graph-supplied facts while changing AKG membership. |
| 3.3 | The skill instructs the agent to keep the AKG structurally sound and consistently parseable by a large language model (LLM) with tools. Minor deviations do not cause total failure. The agent may add custom fields and choose which optional node and edge properties to include for the objective. |
| 3.4 | The skill instructs the agent to retain canonical node and edge identifiers and data-source information so that the agent can check provenance and identify the relevant data system. |
| 3.5 | The skill focuses the agent on datasets, relationships, and statistics. The agent omits internal system attributes while retaining the object references needed to fetch more properties and navigate related objects. |
| 3.6 | The skill's immediate goal is stable AKG editing and parsing correctness. A finalized AKG can be converted into other representations, such as input for Structured Query Language (SQL) generation. |
| 3.7 | No person is involved while the agent builds an AKG. People may validate a finalized AKG. |

Note: the graph model has no fields that capture statistics yet, so the statistics pillar in 3.5 is a
future enhancement and AKGs carry none for now ([functional.md#4.2.1](functional.md)).
