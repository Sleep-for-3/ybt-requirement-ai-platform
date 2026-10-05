from app.services.db.safe_sql_executor import SafeSqlExecutor


def test_safe_sql_executor_allows_select_with_added_limit():
    executor = SafeSqlExecutor(default_limit=100)

    safe_sql = executor.validate_and_prepare("select customer_id from ecif_customer")

    assert safe_sql.lower().endswith("limit 100")


def test_safe_sql_executor_rejects_select_star():
    executor = SafeSqlExecutor()

    try:
        executor.validate_and_prepare("select * from ecif_customer")
    except ValueError as exc:
        assert "SELECT *" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_safe_sql_executor_rejects_mutating_sql():
    executor = SafeSqlExecutor()

    try:
        executor.validate_and_prepare("delete from ecif_customer")
    except ValueError as exc:
        assert "Only SELECT" in str(exc)
    else:
        raise AssertionError("Expected ValueError")


def test_profiling_refuses_an_identifier_that_carries_sql():
    """B608 regression: a crafted "field name" must never reach the assembled statement.

    ``validate_and_prepare`` only proves the whole string is a single SELECT; the crafted value
    ``1) from t union select password from users --`` passes that check and smuggles a second result
    set (confirmed by probe_b608_reachability.py before the fix). The profiler interpolates the two
    names, so it owns the "these must be identifiers" contract.
    """

    executor = SafeSqlExecutor()
    for table_name, field_name in (
        ("t", "1) from t union select password from users --"),
        ("t; drop table users", "amount"),
        ("t", "amount) from users --"),
        ("t", "amount; select 1"),
        ("t", ""),
    ):
        try:
            executor.profile_field(table_name, field_name)
        except ValueError as exc:
            assert "plain SQL identifier" in str(exc)
        else:
            raise AssertionError(f"expected refusal for table={table_name!r} field={field_name!r}")


def test_profiling_still_accepts_a_normal_identifier():
    """The guard must not break the feature it protects."""

    executor = SafeSqlExecutor()
    for table_name, field_name in (("orders", "amount"), ("public.orders", "amount")):
        result = executor.profile_field(table_name, field_name)
        assert result["status"] == "reserved"
        assert field_name in result["safe_sql"]
        assert table_name in result["safe_sql"]
