# 论文展示区：会话级 -> 用户级（幂等，可修复半完成迁移）

from django.db import migrations, models


def _table_name(apps):
    return apps.get_model("research_agent", "ResearchPaperShelfItem")._meta.db_table


def _column_exists(connection, table, column):
    with connection.cursor() as c:
        c.execute(f"SHOW COLUMNS FROM `{table}` LIKE %s", [column])
        return c.fetchone() is not None


def _constraint_exists(connection, table, name):
    with connection.cursor() as c:
        c.execute(
            """
            SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
            WHERE TABLE_SCHEMA = DATABASE()
              AND TABLE_NAME = %s
              AND CONSTRAINT_NAME = %s
            LIMIT 1
            """,
            [table, name],
        )
        return c.fetchone() is not None


def _dedupe_owner_shelf_items(connection, table):
    """同一用户下重复 dedupe_key 仅保留 created_at 最新的一条。"""
    with connection.cursor() as c:
        c.execute(
            f"""
            DELETE t_old FROM `{table}` t_old
            INNER JOIN `{table}` t_keep ON
                t_old.owner_id = t_keep.owner_id
                AND t_old.dedupe_key = t_keep.dedupe_key
                AND (
                    t_old.created_at < t_keep.created_at
                    OR (
                        t_old.created_at = t_keep.created_at
                        AND t_old.id < t_keep.id
                    )
                )
            WHERE t_old.owner_id IS NOT NULL AND t_old.owner_id != ''
            """
        )


def migrate_to_user_scope(apps, schema_editor):
    connection = schema_editor.connection
    Item = apps.get_model("research_agent", "ResearchPaperShelfItem")
    Session = apps.get_model("research_agent", "ResearchSession")
    table = _table_name(apps)

    if not _column_exists(connection, table, "owner_id"):
        field = models.CharField(max_length=128, null=True, blank=True, db_index=True)
        field.set_attributes_from_name("owner_id")
        schema_editor.add_field(Item, field)

    if _column_exists(connection, table, "session_id"):
        session_owners = {
            str(s.id): s.owner_id for s in Session.objects.all().only("id", "owner_id")
        }
        for item in Item.objects.all().iterator():
            owner = session_owners.get(str(item.session_id))
            if owner and item.owner_id != owner:
                item.owner_id = owner
                item.save(update_fields=["owner_id"])

    _dedupe_owner_shelf_items(connection, table)

    if _constraint_exists(connection, table, "ra_paper_shelf_session_dedupe"):
        old_constraint = models.UniqueConstraint(
            fields=("session", "dedupe_key"),
            name="ra_paper_shelf_session_dedupe",
        )
        schema_editor.remove_constraint(Item, old_constraint)

    if _column_exists(connection, table, "session_id"):
        session_field = Item._meta.get_field("session")
        schema_editor.remove_field(Item, session_field)

    # owner_id 可能仍是 NULL（半完成迁移）；用原生 SQL，避免历史模型尚无 owner_id 字段
    with connection.cursor() as c:
        c.execute(f"SHOW COLUMNS FROM `{table}` LIKE 'owner_id'")
        col = c.fetchone()
        if col and col[2] == "YES":
            c.execute(
                f"ALTER TABLE `{table}` MODIFY COLUMN `owner_id` varchar(128) NOT NULL"
            )

    _dedupe_owner_shelf_items(connection, table)

    if not _constraint_exists(connection, table, "ra_paper_shelf_owner_dedupe"):
        with connection.cursor() as c:
            c.execute(
                f"""
                ALTER TABLE `{table}`
                ADD CONSTRAINT `ra_paper_shelf_owner_dedupe`
                UNIQUE (`owner_id`, `dedupe_key`)
                """
            )


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
