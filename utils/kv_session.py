import inspect
import json
from typing import Optional
from datetime import timedelta
from flask import Flask
from flask_session.base import ServerSideSessionInterface, ServerSideSession
from utils.logger import get_logger

logger = get_logger("kv_session")

try:
    from pyodide.ffi import run_sync, to_js
except ImportError:
    run_sync = None
    to_js = None


class CloudflareKVSessionInterface(ServerSideSessionInterface):
    """Flask session interface backed by Cloudflare Workers KV.
    Uses Pyodide JSPI run_sync to execute async KV operations synchronously within WSGI requests.
    """

    def __init__(
        self,
        app: Flask,
        kv_client,
        key_prefix: str = "session:",
        use_signer: bool = False,
        permanent: bool = True,
        sid_length: int = 32,
        serialization_format: str = "json",
    ):
        self.kv = kv_client
        super().__init__(
            app=app,
            key_prefix=key_prefix,
            use_signer=use_signer,
            permanent=permanent,
            sid_length=sid_length,
            serialization_format=serialization_format,
        )

    def _retrieve_session_data(self, store_id: str) -> Optional[dict]:
        try:
            if isinstance(self.kv, dict):
                raw = self.kv.get(store_id)
                if raw is not None:
                    raw_bytes = raw.encode("utf-8") if isinstance(raw, str) else raw
                    return self.serializer.decode(raw_bytes)
                return None

            raw_kv = getattr(self.kv, "_binding", self.kv)
            if hasattr(raw_kv, "get"):
                res = raw_kv.get(store_id)
                if inspect.isawaitable(res) or hasattr(res, "then"):
                    res = run_sync(res) if run_sync is not None else res
                if res is not None:
                    raw_bytes = res.encode("utf-8") if isinstance(res, str) else res
                    return self.serializer.decode(raw_bytes)
        except Exception as e:
            logger.error("KV session retrieve error for %s: %s", store_id, e)
        return None

    def _upsert_session(
        self, session_lifetime: timedelta, session: ServerSideSession, store_id: str
    ) -> None:
        try:
            val_bytes = self.serializer.encode(dict(session))
            val_str = val_bytes.decode("utf-8") if isinstance(val_bytes, bytes) else str(val_bytes)
            ttl = int(session_lifetime.total_seconds()) if session_lifetime else 3600
            if ttl < 60:
                ttl = 60

            if isinstance(self.kv, dict):
                self.kv[store_id] = val_str
                return

            raw_kv = getattr(self.kv, "_binding", self.kv)
            if hasattr(raw_kv, "put"):
                options = to_js({"expirationTtl": ttl}) if to_js is not None else {"expirationTtl": ttl}
                res = raw_kv.put(store_id, val_str, options)
                if inspect.isawaitable(res) or hasattr(res, "then"):
                    if run_sync is not None:
                        run_sync(res)
        except Exception as e:
            logger.error("KV session upsert error for %s: %s", store_id, e)

    def _delete_session(self, store_id: str) -> None:
        try:
            if isinstance(self.kv, dict):
                self.kv.pop(store_id, None)
                return

            raw_kv = getattr(self.kv, "_binding", self.kv)
            if hasattr(raw_kv, "delete"):
                res = raw_kv.delete(store_id)
                if inspect.isawaitable(res) or hasattr(res, "then"):
                    if run_sync is not None:
                        run_sync(res)
        except Exception as e:
            logger.error("KV session delete error for %s: %s", store_id, e)
