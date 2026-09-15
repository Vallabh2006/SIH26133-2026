import os
import re
from flask import g, current_app
import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor
from utils.logger import get_logger

pg_pool = None
logger = get_logger("db")


def get_pg_config(app=None):
    if app:
        cfg = app.config
    elif current_app:
        cfg = current_app.config
    else:
        cfg = {}

    host = cfg.get("PG_HOST") or os.getenv("PG_HOST") or os.getenv("PGHOST") or "/tmp"
    port = int(cfg.get("PG_PORT") or os.getenv("PG_PORT") or os.getenv("PGPORT") or 5432)
    user = cfg.get("PG_USER") or os.getenv("PG_USER") or os.getenv("PGUSER") or "vallabh"
    password = cfg.get("PG_PASSWORD") or os.getenv("PG_PASSWORD") or os.getenv("PGPASSWORD") or ""
    dbname = cfg.get("PG_DB") or os.getenv("PG_DB") or os.getenv("PGDATABASE") or "postgres"
    sslmode = cfg.get("PG_SSLMODE") or os.getenv("PG_SSLMODE")

    res = {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "dbname": dbname
    }
    if sslmode:
        res["sslmode"] = sslmode
    elif not (host.startswith("/") or host in ("localhost", "127.0.0.1")):
        res["sslmode"] = "require"

    return res


def init_db(app):
    global pg_pool
    if pg_pool is None:
        db_cfg = get_pg_config(app)
        try:
            pg_pool = pool.ThreadedConnectionPool(
                minconn=2,
                maxconn=20,
                **db_cfg
            )
        except Exception as e:
            logger.error("Failed to initialize PostgreSQL connection pool: %s", e)
            raise
    app.teardown_appcontext(close_db)


def get_db():
    if "db_conn" not in g:
        if pg_pool is None:
            db_cfg = get_pg_config()
            g.db_conn = psycopg2.connect(**db_cfg)
            g.is_pooled = False
        else:
            g.db_conn = pg_pool.getconn()
            g.is_pooled = True

    if "db_cursor" not in g:
        g.db_cursor = g.db_conn.cursor(cursor_factory=RealDictCursor)

    return g.db_cursor


def query_db(query, args=(), one=False):
    try:
        cur = get_db()
        cur.execute(query, args)
        rv = cur.fetchall()
        if one:
            return rv[0] if rv else None
        return rv
    except Exception as e:
        logger.error("Database Query Error: %s | Query: %s | Args: %s", e, query, args)
        if "db_conn" in g and g.db_conn:
            try:
                g.db_conn.rollback()
            except Exception:
                pass
        raise e


def execute_db(query, args=()):
    try:
        cur = get_db()

        stripped = query.strip()
        is_insert = bool(re.match(r"^INSERT\s+INTO\s+", stripped, re.IGNORECASE))
        has_returning = bool(re.search(r"\bRETURNING\b", stripped, re.IGNORECASE))

        no_id_tables = {"role_permissions"}
        table_match = re.search(r"^INSERT\s+INTO\s+([a-zA-Z0-9_]+)", stripped, re.IGNORECASE)
        target_table = table_match.group(1).lower() if table_match else ""

        if is_insert and not has_returning and target_table not in no_id_tables:
            modified_query = stripped.rstrip("; \n\t") + " RETURNING id"
            cur.execute(modified_query, args)
            row = cur.fetchone()
            g.db_conn.commit()
            return row["id"] if row and "id" in row else None
        else:
            cur.execute(query, args)
            g.db_conn.commit()
            return None
    except Exception as e:
        logger.error("Database Execute Error: %s | Query: %s | Args: %s", e, query, args)
        if "db_conn" in g and g.db_conn:
            try:
                g.db_conn.rollback()
            except Exception:
                pass
        raise e


def close_db(e=None):
    cursor = g.pop("db_cursor", None)
    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass

    conn = g.pop("db_conn", None)
    is_pooled = g.pop("is_pooled", False)
    if conn is not None:
        if is_pooled and pg_pool is not None:
            try:
                pg_pool.putconn(conn)
            except Exception:
                pass
        else:
            try:
                conn.close()
            except Exception:
                pass
