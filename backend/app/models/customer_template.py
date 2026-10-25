"""客户需求文档模板注册（P0-D）。

与监管报送模板（``TemplateVersion`` / ``TargetTable``）的区别：

- 监管报送模板描述的是"报表有哪些表、表有哪些字段、字段的监管口径"；
- 客户需求文档模板描述的是"客户的 Word/Excel 长什么样、正文往哪个锚点或命名
  单元格里填"，由人工配置锚点/单元格映射后注册。

模板版本包含原始文件 hash、适配配置与配置摘要、渲染器版本与支持范围，导出时可以
只给 ``template_id`` 复用它，不需要每次重新上传文件。
"""

from __future__ import annotations

from sqlalchemy import JSON, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.ext.mutable import MutableDict
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.entities import TimestampMixin


class CustomerTemplate(Base, TimestampMixin):
    __tablename__ = "customer_templates"
    __table_args__ = (
        UniqueConstraint("project_id", "name", "version_no", name="uq_customer_template_version"),
        Index("ix_customer_template_scope", "project_id", "name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    project_id: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(200))
    version_no: Mapped[int] = mapped_column(Integer, default=1)
    format: Mapped[str] = mapped_column(String(10))
    source_file_name: Mapped[str] = mapped_column(String(255), default="")
    file_sha256: Mapped[str] = mapped_column(String(64))
    file_size: Mapped[int] = mapped_column(Integer, default=0)
    storage_key: Mapped[str] = mapped_column(String(500))
    config_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    config_digest: Mapped[str] = mapped_column(String(64), default="")
    renderer_version: Mapped[str] = mapped_column(String(80), default="")
    supported_scope_json: Mapped[dict] = mapped_column(MutableDict.as_mutable(JSON), default=dict)
    notes: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
