import os
import re
import threading
from flask import g, current_app
import pg8000.dbapi
from utils.logger import get_logger

logger = get_logger("db")

db_lock = threading.Lock()


def get_pg_config(app=None):
    if app:
        cfg = app.config
    elif current_app:
        cfg = current_app.config
    else:
        cfg = {}

    return {
        "host": cfg.get("PG_HOST") or os.getenv("PG_HOST") or "localhost",
        "port": int(cfg.get("PG_PORT") or os.getenv("PG_PORT") or 5432),
        "user": cfg.get("PG_USER") or os.getenv("PG_USER") or "postgres",
        "password": cfg.get("PG_PASSWORD") or os.getenv("PG_PASSWORD") or "",
        "database": cfg.get("PG_DB") or os.getenv("PG_DB") or "postgres",
    }


def init_db(app):
    app.teardown_appcontext(close_db)


def get_db():
    if "db_conn" not in g:
        env = current_app.extensions.get("hyperdrive") if current_app else None
        conn = None

        if env:
            try:
                conn = pg8000.dbapi.connect(
                    host=env.host,
                    port=int(env.port),
                    user=env.user,
                    password=env.password,
                    database=env.database,
                    ssl_context=None,
                )
            except Exception as e:
                logger.warning("Hyperdrive connection failed (%s), falling back to direct connection", e)
                conn = None

        if conn is None:
            cfg = get_pg_config()
            ssl_mode = cfg.get("sslmode") or os.getenv("PG_SSLMODE", "require")
            use_ssl = True if ssl_mode not in ("disable", "none", "false", "0") else None
            try:
                conn = pg8000.dbapi.connect(
                    host=cfg["host"],
                    port=cfg["port"],
                    user=cfg["user"],
                    password=cfg["password"],
                    database=cfg["database"],
                    ssl_context=use_ssl,
                )
            except Exception as e:
                if "refuses SSL" in str(e) or "Server refuses SSL" in str(e):
                    conn = pg8000.dbapi.connect(
                        host=cfg["host"],
                        port=cfg["port"],
                        user=cfg["user"],
                        password=cfg["password"],
                        database=cfg["database"],
                        ssl_context=None,
                    )
                else:
                    raise

        g.db_conn = conn

    if "db_cursor" not in g:
        g.db_cursor = g.db_conn.cursor()

    return g.db_cursor


def query_db(query, args=(), one=False):
    try:
        with db_lock:
            cur = get_db()
            cur.execute(query, args)
            columns = [desc[0] for desc in cur.description] if cur.description else []
            rows = [dict(zip(columns, row)) for row in cur.fetchall()]

            if one:
                return rows[0] if rows else None

            return rows

    except Exception as e:
        logger.error(
            "Database Query Error: %s | Query: %s | Args: %s",
            e, query, args
        )
        if "db_conn" in g:
            try:
                g.db_conn.rollback()
            except Exception:
                pass
        raise


def execute_db(query, args=()):
    try:
        with db_lock:
            cur = get_db()

            stripped = query.strip()
            is_insert = bool(
                re.match(r"^INSERT\s+INTO\s+", stripped, re.IGNORECASE)
            )
            has_returning = bool(
                re.search(r"\bRETURNING\b", stripped, re.IGNORECASE)
            )

            no_id_tables = {"role_permissions"}

            table_match = re.search(
                r"^INSERT\s+INTO\s+([a-zA-Z0-9_]+)",
                stripped,
                re.IGNORECASE
            )

            target_table = (
                table_match.group(1).lower()
                if table_match else ""
            )

            if is_insert and not has_returning and target_table not in no_id_tables:
                modified_query = (
                    stripped.rstrip("; \n\t") +
                    " RETURNING id"
                )

                cur.execute(modified_query, args)
                row = cur.fetchone()
                g.db_conn.commit()

                if row:
                    return row[0]

                return None

            cur.execute(query, args)
            g.db_conn.commit()
            return None

    except Exception as e:
        logger.error(
            "Database Execute Error: %s | Query: %s | Args: %s",
            e, query, args
        )

        if "db_conn" in g:
            try:
                g.db_conn.rollback()
            except Exception:
                pass

        raise


def close_db(e=None):
    cursor = g.pop("db_cursor", None)

    if cursor is not None:
        try:
            cursor.close()
        except Exception:
            pass

    conn = g.pop("db_conn", None)

    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
