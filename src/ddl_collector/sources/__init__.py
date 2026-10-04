from ddl_collector.evidence import SourceFamily
from ddl_collector.sources.sqlite import SqliteSourceFamily


FAMILIES: dict[str, type] = {
    SqliteSourceFamily.name: SqliteSourceFamily,
}


def family(name: str, **options: object) -> SourceFamily:
    try:
        return FAMILIES[name](**options)
    except KeyError:
        raise ValueError(f"unknown source family {name!r}; known: {sorted(FAMILIES)}") from None


__all__ = ["FAMILIES", "SqliteSourceFamily", "family"]
