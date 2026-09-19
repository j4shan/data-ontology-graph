from typing import Annotated, Literal, Union

from pydantic import BaseModel, Field


class S3Source(BaseModel):
    type: Literal["s3"] = "s3"
    bucket: str
    prefix: str
    format: str = "parquet"
    partition_keys: list[str] = Field(default_factory=list)


class DatabricksUnitySource(BaseModel):
    type: Literal["databricks_unity"] = "databricks_unity"
    workspace_host: str
    catalog: str
    schema_name: str = Field(alias="schema")
    table: str

    model_config = {"populate_by_name": True}


class SqlDbSource(BaseModel):
    type: Literal["sql_db"] = "sql_db"
    host: str
    database: str
    schema_name: str = Field(alias="schema")
    table: str
    dialect: str = "Microsoft SQL Server"

    model_config = {"populate_by_name": True}

    def qualified_name(self) -> str:
        return f"{self.database}.{self.table}"


class SnowflakeSource(BaseModel):
    type: Literal["snowflake"] = "snowflake"
    account: str
    database: str
    schema_name: str = Field(alias="schema")
    table: str

    model_config = {"populate_by_name": True}


Source = Annotated[
    Union[S3Source, DatabricksUnitySource, SqlDbSource, SnowflakeSource],
    Field(discriminator="type"),
]


def source_qualified_name(source: Source) -> str:
    if isinstance(source, SqlDbSource):
        return source.qualified_name()
    if isinstance(source, DatabricksUnitySource):
        return f"{source.catalog}.{source.schema_name}.{source.table}"
    if isinstance(source, SnowflakeSource):
        return f"{source.database}.{source.schema_name}.{source.table}"
    return f"{source.bucket}/{source.prefix}"


def make_node_id(source: Source) -> str:
    return f"{source.type}:{source_qualified_name(source)}"
