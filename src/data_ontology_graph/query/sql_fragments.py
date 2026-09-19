from data_ontology_graph.model.dataset import DatasetNode
from data_ontology_graph.model.relationship import JoinEndpoint, JoinRelationship


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def qualified_column(table: str, column: str) -> str:
    return f"{quote_ident(table)}.{quote_ident(column)}"


def apply_transform(expression: str, transform: str | None) -> str:
    if not transform:
        return expression
    return f"{transform}({expression})"


def join_on_sql(
    relationship: JoinRelationship,
    from_node: DatasetNode,
    to_node: DatasetNode,
) -> str:
    source = relationship.endpoint(from_node.node_id)
    target = relationship.endpoint(to_node.node_id)
    if len(source.columns) != len(target.columns):
        raise ValueError("join endpoints must have the same number of columns")
    clauses = [
        f"{apply_transform(qualified_column(from_node.table_name, left), source.transform)} = "
        f"{apply_transform(qualified_column(to_node.table_name, right), target.transform)}"
        for left, right in zip(source.columns, target.columns)
    ]
    return " AND ".join(clauses)


def hop_join_type(from_endpoint: JoinEndpoint) -> str:
    from data_ontology_graph.model.enums import Participation

    if from_endpoint.participation == Participation.TOTAL:
        return "INNER"
    return "LEFT"
