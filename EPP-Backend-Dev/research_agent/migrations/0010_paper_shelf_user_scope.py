# 论文展示区：会话级 -> 用户级（幂等，可修复半完成迁移）

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


def _dedupe_owner_shelf_items(connection, table):
    """同一用户下重复 dedupe_key 仅保留 created_at 最新的一条。"""
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


def _backfill_owner_from_session(connection, apps, table):
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
                WHERE s.id = item.{qn("session_id")}
            )
            WHERE item.{qn("session_id")} IS NOT NULL
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


def migrate_to_user_scope(apps, schema_editor):
    connection = schema_editor.connection
    Item = apps.get_model("research_agent", "ResearchPaperShelfItem")
    table = _table_name(apps)

    if not _column_exists(connection, table, "owner_id"):
        field = models.CharField(max_length=128, null=True, blank=True, db_index=True)
        field.set_attributes_from_name("owner_id")
        schema_editor.add_field(Item, field)

    if _column_exists(connection, table, "session_id"):
        _backfill_owner_from_session(connection, apps, table)

    _dedupe_owner_shelf_items(connection, table)

    if _constraint_exists(connection, table, "ra_paper_shelf_session_dedupe"):
        old_constraint = models.UniqueConstraint(
            fields=("session", "dedupe_key"),
            name="ra_paper_shelf_session_dedupe",
        )
        schema_editor.remove_constraint(Item, old_constraint)

    if _column_exists(connection, table, "session_id"):
        session_field = Item._meta.get_field("session")
        # 约束已从库中删除，但历史模型 Meta 仍引用 session；SQLite 重建表会因此失败
        Item._meta.constraints = [
            c
            for c in Item._meta.constraints
            if getattr(c, "name", None) != "ra_paper_shelf_session_dedupe"
        ]
        schema_editor.remove_field(Item, session_field)

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
        ("research_agent", "0009_researchmessage_metadata"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(migrate_to_user_scope, noop_reverse),
            ],
            state_operations=[
                migrations.AddField(
                    model_name="researchpapershelfitem",
                    name="owner_id",
                    field=models.CharField(db_index=True, max_length=128),
                ),
                migrations.RemoveConstraint(
                    model_name="researchpapershelfitem",
                    name="ra_paper_shelf_session_dedupe",
                ),
                migrations.RemoveField(
                    model_name="researchpapershelfitem",
                    name="session",
                ),
                migrations.AddConstraint(
                    model_name="researchpapershelfitem",
                    constraint=models.UniqueConstraint(
                        fields=("owner_id", "dedupe_key"),
                        name="ra_paper_shelf_owner_dedupe",
                    ),
                ),
            ],
        ),
    ]
