"""Импорт квестовых реплик из локальной MySQL с дампом vmangos.

Отличия от legacy tts_cli/sql_queries.py:
- русский и английский текст приходят раздельно, без IFNULL-подмены английским;
- из версий по патчам берётся последняя (vmangos хранит несколько строк на entry);
- NPC без DisplayInfoExtra (звери, существа) не теряются: раса и пол остаются пустыми.
"""
import os

from voru.corpus.record import LOCALE_COLUMN_SUFFIX, record_from_row

FINAL_PATCH = 10  # 1.12 — последний контентный патч vmangos

QUEST_ROWS_SQL = """
WITH
qt AS (
    SELECT q.* FROM quest_template q
    JOIN (SELECT entry, MAX(patch) AS patch FROM quest_template GROUP BY entry) last USING (entry, patch)
),
ct AS (
    SELECT c.entry, c.name, c.display_id1 FROM creature_template c
    JOIN (SELECT entry, MAX(patch) AS patch FROM creature_template GROUP BY entry) last USING (entry, patch)
),
gt AS (
    SELECT g.entry, g.name FROM gameobject_template g
    JOIN (SELECT entry, MAX(patch) AS patch FROM gameobject_template GROUP BY entry) last USING (entry, patch)
),
it AS (
    SELECT i.entry, i.name, i.start_quest FROM item_template i
    JOIN (SELECT entry, MAX(patch) AS patch FROM item_template GROUP BY entry) last USING (entry, patch)
),
rel AS (
    SELECT 'accept' AS stage, quest, 'creature' AS npc_type, id AS npc_id
        FROM creature_questrelation WHERE patch_max >= {final_patch}
    UNION ALL SELECT 'progress', quest, 'creature', id
        FROM creature_involvedrelation WHERE patch_max >= {final_patch}
    UNION ALL SELECT 'complete', quest, 'creature', id
        FROM creature_involvedrelation WHERE patch_max >= {final_patch}
    UNION ALL SELECT 'accept', quest, 'gameobject', id
        FROM gameobject_questrelation WHERE patch_max >= {final_patch}
    UNION ALL SELECT 'progress', quest, 'gameobject', id
        FROM gameobject_involvedrelation WHERE patch_max >= {final_patch}
    UNION ALL SELECT 'complete', quest, 'gameobject', id
        FROM gameobject_involvedrelation WHERE patch_max >= {final_patch}
    UNION ALL SELECT 'accept', start_quest, 'item', entry
        FROM it WHERE start_quest > 0
),
rows_all AS (
    SELECT
        rel.quest AS quest_id,
        qt.Title AS quest_title_en,
        lq.Title{loc} AS quest_title_ru,
        qt.ZoneOrSort AS zone_id,
        rel.stage,
        rel.npc_type,
        rel.npc_id,
        COALESCE(ct.name, gt.name, it.name) AS npc_name_en,
        CASE rel.npc_type
            WHEN 'creature' THEN lc.name{loc}
            WHEN 'gameobject' THEN lg.name{loc}
            ELSE li.name{loc}
        END AS npc_name_ru,
        cdie.DisplayRaceID AS npc_race_id,
        cdie.DisplaySexID AS npc_sex_id,
        CASE rel.stage
            WHEN 'accept' THEN qt.Details
            WHEN 'progress' THEN qt.RequestItemsText
            ELSE qt.OfferRewardText
        END AS text_en,
        CASE rel.stage
            WHEN 'accept' THEN lq.Details{loc}
            WHEN 'progress' THEN lq.RequestItemsText{loc}
            ELSE lq.OfferRewardText{loc}
        END AS text_ru
    FROM rel
    JOIN qt ON qt.entry = rel.quest
    LEFT JOIN ct ON rel.npc_type = 'creature' AND ct.entry = rel.npc_id
    LEFT JOIN gt ON rel.npc_type = 'gameobject' AND gt.entry = rel.npc_id
    LEFT JOIN it ON rel.npc_type = 'item' AND it.entry = rel.npc_id
    LEFT JOIN db_CreatureDisplayInfo cdi ON cdi.ID = ct.display_id1
    LEFT JOIN db_CreatureDisplayInfoExtra cdie ON cdie.ID = cdi.ExtendedDisplayInfoID
    LEFT JOIN locales_quest lq ON lq.entry = rel.quest
    LEFT JOIN locales_creature lc ON lc.entry = rel.npc_id
    LEFT JOIN locales_gameobject lg ON lg.entry = rel.npc_id
    LEFT JOIN locales_item li ON li.entry = rel.npc_id
)
SELECT DISTINCT * FROM rows_all
WHERE npc_name_en IS NOT NULL
  AND (NULLIF(text_en, '') IS NOT NULL OR NULLIF(text_ru, '') IS NOT NULL)
ORDER BY quest_id, stage, npc_type, npc_id
"""


def connect():
    import pymysql
    from dotenv import load_dotenv

    load_dotenv()
    return pymysql.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", ""),
        database=os.getenv("MYSQL_DATABASE", "mangos"),
        charset="utf8mb4",
    )


def fetch_quest_records(connection, client, source_revision: str) -> list:
    sql = QUEST_ROWS_SQL.format(loc=LOCALE_COLUMN_SUFFIX[client.locale], final_patch=FINAL_PATCH)
    with connection.cursor() as cursor:
        cursor.execute(sql)
        columns = [d[0] for d in cursor.description]
        rows = [dict(zip(columns, values)) for values in cursor.fetchall()]
    return [record_from_row(row, client, source_revision) for row in rows]
