def quote_identifier(value: str, dialect: str) -> str:
    if not value or "\x00" in value:
        raise ValueError("Identifier must not be empty")
    if dialect.lower() in {"mysql", "mysql_compatible"}:
        return f"`{value.replace('`', '``')}`"
    return f'"{value.replace(chr(34), chr(34) * 2)}"'


def qualify_table(schema_name: str | None, table_name: str, dialect: str) -> str:
    table = quote_identifier(table_name, dialect)
    if not schema_name or (dialect.lower() == "sqlite" and schema_name == "main"):
        return table
    return f"{quote_identifier(schema_name, dialect)}.{table}"
