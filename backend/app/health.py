from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.request import urlopen

import redis
import urllib3
from minio import Minio
from neo4j import GraphDatabase
from pymilvus import MilvusClient
from sqlalchemy import create_engine, text

from app.settings import Settings, get_settings

_TIMEOUT_SECONDS = 2
_DEPENDENCIES = ("mysql", "redis", "etcd", "minio", "milvus", "neo4j")


def probe_dependencies(settings: Settings | None = None) -> dict[str, dict[str, bool]]:
    cfg = settings or get_settings()
    probes: dict[str, Callable[[], None]] = {
        "mysql": lambda: _probe_mysql(cfg),
        "redis": lambda: _probe_redis(cfg),
        "etcd": lambda: _probe_etcd(cfg),
        "minio": lambda: _probe_minio(cfg),
        "milvus": lambda: _probe_milvus(cfg),
        "neo4j": lambda: _probe_neo4j(cfg),
    }
    results: dict[str, dict[str, bool]] = {name: {"ok": False} for name in _DEPENDENCIES}
    pool = ThreadPoolExecutor(max_workers=len(probes))
    try:
        futures = {pool.submit(_probe_ok, probe): name for name, probe in probes.items()}
        try:
            for future in as_completed(futures, timeout=_TIMEOUT_SECONDS + 1):
                results[futures[future]] = future.result()
        except TimeoutError:
            pass
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def _probe_ok(probe: Callable[[], None]) -> dict[str, bool]:
    try:
        probe()
        return {"ok": True}
    except Exception:
        return {"ok": False}


def _probe_mysql(settings: Settings) -> None:
    engine = create_engine(
        settings.database_url,
        connect_args={"connect_timeout": _TIMEOUT_SECONDS},
        pool_pre_ping=True,
    )
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    finally:
        engine.dispose()


def _probe_redis(settings: Settings) -> None:
    client = redis.Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=_TIMEOUT_SECONDS,
        socket_timeout=_TIMEOUT_SECONDS,
    )
    try:
        if not client.ping():
            raise RuntimeError("redis ping failed")
    finally:
        client.close()


def _probe_etcd(settings: Settings) -> None:
    with urlopen(f"{settings.etcd_url.rstrip('/')}/health", timeout=_TIMEOUT_SECONDS) as response:
        if response.status != 200:
            raise RuntimeError("etcd health failed")


def _probe_minio(settings: Settings) -> None:
    http_client = urllib3.PoolManager(
        timeout=urllib3.Timeout(connect=_TIMEOUT_SECONDS, read=_TIMEOUT_SECONDS)
    )
    client = Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=settings.minio_secure,
        http_client=http_client,
    )
    client.list_buckets()


def _probe_milvus(settings: Settings) -> None:
    client = MilvusClient(uri=settings.milvus_uri, timeout=_TIMEOUT_SECONDS)
    client.list_collections()


def _probe_neo4j(settings: Settings) -> None:
    driver = GraphDatabase.driver(
        settings.neo4j_uri,
        auth=(settings.neo4j_user, settings.neo4j_password),
        connection_timeout=_TIMEOUT_SECONDS,
    )
    try:
        driver.verify_connectivity()
    finally:
        driver.close()
