# Project metadata guideline

**Objective.** Keep project-owned documents and authored assets in a fixed tree so later
sessions find requirements, contracts, plans, and exhibits in one place.

**Your tasks.** Maintain the product spec, place project metadata, and place authored
resources. Each section states when it applies.

## Requirement Housekeeping Guidelines

1. Collect user-specified product and system design requirements from chat messages. Maintain
   documented product requirement and system design specs in the `project_metadata/` directory.
2. Before executing an update action, such as a code modification or CRUD data operation, present
   requirement updates as a numbered list and prompt the user to confirm with `1. Yes` or `2. No`.
   Do this only when the update request introduces a new product or system design requirement.
3. Apply this guideline to UI, backend, data, and project settings. Collect, compare, and update
   only explicit requirements given by the user. Exclude automatic design decisions.

4. Write each explicit product or system design requirement into the matching category document.
   Create that document if it does not exist. Leave the documents unchanged when the user states no
   new requirement.
5. Never write a decision the system made and the user did not confirm. Examples include a UI
   widget theme, colour code, or size. Never write implementation guidelines, tools, dependencies,
   or build processes unless the user explicitly requests them as requirements.
6. Give every clause a hierarchical dotted ID, such as `1.2.3`, that is unique within its
   requirement document. Treat each document as a snapshot of current requirements, not as version
   history. Delete a superseded clause. Never strike it through, annotate it, or renumber the
   remaining IDs.
7. Read the matching requirement documents before modifying code or performing a CRUD data
   operation. When a requirement and the implementation disagree, state which one is defective and
   fix that one. Never silently reword a requirement to match the implementation.
8. Delete a clause when the user retires its requirement.

Store requirement documents in these locations, relative to the project root. Create a missing
location or document when required.

| Requirement document | Location | Category labels |
| --- | --- | --- |
| Product requirements | `project_metadata/product/<category>/` | `UI`, `backend`, `data`, `project_setting` |
| System design requirements | `project_metadata/system_design/<category>/` | `UI`, `backend`, `data`, `project_setting` |

## Static Resource Housekeeping

1. Put project-owned writing and generation contracts in `project_metadata/instructions/`, relative
   to the project root. Create the directory when it does not exist.
2. Keep authored exhibit and fixture assets under `resources/`, relative to the project root. Never
   put temporary or git-ignored resources there.

   - Put authored HTML, canvases, and formal documents in `resources/html/`.
   - Put figures in `resources/img/`.
   - Put figure prompts in `resources/img_prompt/`.
   - Put authored scenario and fixture data in `resources/data/`. Never put runtime-generated data
     there.

## Project Plan Housekeeping

Put transient execution plans in `project_metadata/plans/`, relative to the project root. Create the
directory when it does not exist. Never version these plans.
