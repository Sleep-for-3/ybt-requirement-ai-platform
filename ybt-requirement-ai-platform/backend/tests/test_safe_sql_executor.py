from app.services.db_probe.safe_sql_executor import SafeSqlExecutor


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
