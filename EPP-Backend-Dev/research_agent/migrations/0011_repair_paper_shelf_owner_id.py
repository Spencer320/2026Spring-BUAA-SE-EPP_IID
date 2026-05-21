# 修复 0010 半完成迁移：物理表缺少 owner_id 列导致展示区 API 500

from django.db import migrations, models


def _table_name(apps):
    return apps.get_model("research_agent", "ResearchPaperShelfItem")._meta.db_table


def _column_exists(connection, table, column):
    with connection.cursor() as cursor:
        for col in connection.introspection.get_table_description(cursor, table):
            if col.name == column:
                return True
    return False


def _column_nullable(connection, table, column):
    with connection.cursor() as cursor:
        for col in connection.introspection.get_table_description(cursor, table):
            if col.name == column:
                return col.null_ok
    return True


def _constraint_exists(connection, table, name):
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, table)
    return name in constraints


def _drop_owner_dedupe_index(connection, table):
    name = "ra_paper_shelf_owner_dedupe"
    if not _constraint_exists(connection, table, name):
        return
    qn = connection.ops.quote_name
    with connection.cursor() as c:
        if connection.vendor == "sqlite":
            c.execute(f"DROP INDEX IF EXISTS {qn(name)}")
        else:
            c.execute(f"ALTER TABLE {qn(table)} DROP CONSTRAINT {qn(name)}")


def _dedupe_owner_shelf_items(connection, table):
    qn = connection.ops.quote_name
    with connection.cursor() as c:
        if connection.vendor == "sqlite":
            c.execute(
                f"""
                DELETE FROM {qn(table)}
                WHERE {qn("id")} IN (
                    SELECT {qn("id")} FROM (
                        SELECT {qn("id")},
                            ROW_NUMBER() OVER (
                                PARTITION BY {qn("owner_id")}, {qn("dedupe_key")}
                                ORDER BY {qn("created_at")} DESC, {qn("id")} DESC
                            ) AS rn
                        FROM {qn(table)}
                        WHERE {qn("owner_id")} IS NOT NULL AND {qn("owner_id")} != ''
                    ) ranked
                    WHERE rn > 1
                )
                """
            )
        else:
            c.execute(
                f"""
                DELETE t_old FROM {qn(table)} t_old
                INNER JOIN {qn(table)} t_keep ON
                    t_old.{qn("owner_id")} = t_keep.{qn("owner_id")}
                    AND t_old.{qn("dedupe_key")} = t_keep.{qn("dedupe_key")}
                    AND (
                        t_old.{qn("created_at")} < t_keep.{qn("created_at")}
                        OR (
                            t_old.{qn("created_at")} = t_keep.{qn("created_at")}
                            AND t_old.{qn("id")} < t_keep.{qn("id")}
                        )
                    )
                WHERE t_old.{qn("owner_id")} IS NOT NULL AND t_old.{qn("owner_id")} != ''
                """
            )


def _backfill_orphan_owner_ids(connection, apps, table):
    """无 session_id 的历史行：按最近活跃会话的 owner 回填（单用户开发库常见）。"""
    Session = apps.get_model("research_agent", "ResearchSession")
    session_table = Session._meta.db_table
    qn = connection.ops.quote_name
    with connection.cursor() as c:
        c.execute(
            f"""
            UPDATE {qn(table)} AS item
            SET {qn("owner_id")} = (
                SELECT s.{qn("owner_id")}
                FROM {qn(session_table)} AS s
                ORDER BY s.{qn("updated_at")} DESC, s.{qn("created_at")} DESC
                LIMIT 1
            )
            WHERE item.{qn("owner_id")} IS NULL OR item.{qn("owner_id")} = ''
            """
        )


def _add_owner_dedupe_constraint(connection, table):
    name = "ra_paper_shelf_owner_dedupe"
    if _constraint_exists(connection, table, name):
        return
    qn = connection.ops.quote_name
    with connection.cursor() as c:
        if connection.vendor == "sqlite":
            c.execute(
                f"CREATE UNIQUE INDEX {qn(name)} ON {qn(table)} "
                f"({qn('owner_id')}, {qn('dedupe_key')})"
            )
        else:
            c.execute(
                f"ALTER TABLE {qn(table)} ADD CONSTRAINT {qn(name)} "
                f"UNIQUE ({qn('owner_id')}, {qn('dedupe_key')})"
            )


def repair_paper_shelf_owner_id(apps, schema_editor):
    connection = schema_editor.connection
    Item = apps.get_model("research_agent", "ResearchPaperShelfItem")
    table = _table_name(apps)

    _drop_owner_dedupe_index(connection, table)

    if not _column_exists(connection, table, "owner_id"):
        field = models.CharField(max_length=128, null=True, blank=True, db_index=True)
        field.set_attributes_from_name("owner_id")
        schema_editor.add_field(Item, field)

    _backfill_orphan_owner_ids(connection, apps, table)
    _dedupe_owner_shelf_items(connection, table)

    if _column_exists(connection, table, "owner_id") and _column_nullable(
        connection, table, "owner_id"
    ):
        nullable_field = models.CharField(max_length=128, null=True, blank=True, db_index=True)
        nullable_field.set_attributes_from_name("owner_id")
        non_null_field = models.CharField(max_length=128, db_index=True)
        non_null_field.set_attributes_from_name("owner_id")
        schema_editor.alter_field(Item, nullable_field, non_null_field)

    _dedupe_owner_shelf_items(connection, table)
    _add_owner_dedupe_constraint(connection, table)


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ("research_agent", "0010_paper_shelf_user_scope"),
    ]

    operations = [
        migrations.RunPython(repair_paper_shelf_owner_id, noop_reverse),
    ]
