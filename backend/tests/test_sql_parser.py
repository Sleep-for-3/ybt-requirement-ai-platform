from app.services.sql_parser import parse_sql


def test_parse_sql_extracts_tables_fields_where_and_join():
    raw_sql = """
    select c.customer_id, c.cert_type, l.loan_no
    from ecif_customer c
    join loan_contract l on c.customer_id = l.customer_id
    where c.status = 'A' and l.balance > 0
    """

    result = parse_sql(raw_sql)

    assert result.parsed_success is True
    assert "ecif_customer" in result.source_tables
    assert "loan_contract" in result.source_tables
    assert any("cert_type" in field for field in result.selected_fields)
    assert any("customer_id" in join for join in result.joins)
    assert any("balance" in condition for condition in result.where_conditions)


def test_parse_sql_keeps_error_message_for_invalid_sql():
    result = parse_sql("select from where")

    assert result.parsed_success is False
    assert result.error_message
    assert result.source_tables == []
