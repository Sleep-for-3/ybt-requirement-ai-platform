"""GBase/4A batch scripts must import without vendor-dialect failures.

The real customer scripts use ``#`` line comments, ``#{VAR}`` placeholders and
``INSERT INTO ... SELECT ... AS <target_field>`` without an explicit target
column list.  Two defects used to drop every one of those files on import:

1. ``batch_parser.parse_file`` passed the vendor name straight to sqlglot, which
   raises ``ValueError: Unknown dialect 'gbase'`` (the alias table only existed
   in the lineage parser).
2. ``#`` comment banners crashed or truncated tokenization (sqlglot raises even
   ``IndexError`` for a ``--`` comment that reaches end of input).

These tests pin the fix and the guarantees that came with it: variables are
still reported, ``#{...}`` is never mistaken for a comment, and unknown
dialects degrade with a warning instead of failing the whole batch.
"""

from __future__ import annotations

from app.services.lineage.preprocessing import preprocess_sql, strip_hash_comments
from app.services.lineage.sql_parser import resolve_dialect
from app.services.metadata.batch_parser import effective_dialect, parse_file

GBASE_SCRIPT = """USE #{INSTANCE_GB};

####################################################################
# 说明：岗位信息(#{INSTANCE_GB}.T_1_4)
# 参数：#{DATA_DATE}
####################################################################
DELETE FROM #{INSTANCE_GB}.T_1_4 WHERE A040008 = '#{DATA_DATE}';

#1.插入岗位信息
INSERT INTO #{INSTANCE_GB}.T_1_4
SELECT
       COALESCE(CONCAT(SUBSTR(JG.C_FINA_LICEN_NO,1,11),JG.BRANCH_NO),BLJG.JGID) AS A040001 -- 机构ID
      ,JG.BRANCH_NO AS A040002 -- 机构号
      ,BLJG.JGID AS A040003 -- 补录机构ID
 FROM #{INSTANCE_GB}.HYF_BK_POSITION_INFO_EXT_YBT JG
 LEFT JOIN #{INSTANCE_GB}.BL_YBT_JGXXB BLJG ON BLJG.JGID = JG.JGID
WHERE JG.DATA_DATE = '#{DATA_DATE}'
"""


def _source_tables(result):
    names = set()
    for rule in result.get("rules", []):
        source = rule.get("source") or {}
        if source.get("table_name"):
            names.add(source["table_name"])
    return names


def test_gbase_alias_resolves_to_mysql():
    assert resolve_dialect("gbase").effective == "mysql"
    assert effective_dialect("gbase") == ("mysql", [])
    assert effective_dialect("GBase8a") == ("mysql", [])


def test_unknown_dialect_degrades_with_warning_instead_of_raising():
    effective, warnings = effective_dialect("no-such-dialect")
    assert effective == ""
    assert len(warnings) == 1
    assert "Unsupported SQL dialect" in warnings[0]


def test_gbase_script_parses_with_lineage():
    kind, result = parse_file(GBASE_SCRIPT.encode("utf-8"), "YBT_T_1_4.sql", "auto", "gbase")
    assert kind == "sql"
    assert result["rules"], "GBase INSERT ... SELECT must yield lineage rules"
    tables = _source_tables(result)
    assert "HYF_BK_POSITION_INFO_EXT_YBT" in tables
    assert "BL_YBT_JGXXB" in tables
    assert all(statement["parse_status"] == "parsed" for statement in result["statements"])


def test_gbase_parse_keeps_template_variable_evidence():
    _, result = parse_file(GBASE_SCRIPT.encode("utf-8"), "YBT_T_1_4.sql", "auto", "gbase")
    joined = "\n".join(result["warnings"])
    assert "Unknown template variable preserved: #{DATA_DATE}" in joined
    assert "Statement 1 parse failed" not in joined


def test_hash_comment_stripping_preserves_placeholders_and_strings():
    sql = "SELECT '#not_comment' AS a, #{DATA_DATE} AS b FROM t # real comment\n"
    stripped = strip_hash_comments(sql)
    assert "#not_comment" in stripped
    assert "#{DATA_DATE}" in stripped
    assert "real comment" not in stripped


def test_hash_comment_at_end_of_input_does_not_break_tokenizer():
    sql = "SELECT A040001 AS A040001 FROM #{INSTANCE_GB}.T_1_4\n# trailing banner without newline"
    prepared = preprocess_sql(sql)
    assert prepared.parse_sql.endswith("\n")
    _, result = parse_file(sql.encode("utf-8"), "YBT_EDGE.sql", "sql", "gbase")
    assert result["rules"] or result["statements"][0]["parse_status"] == "parsed"
