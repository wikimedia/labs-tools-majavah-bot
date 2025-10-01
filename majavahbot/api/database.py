from contextlib import contextmanager

import pymysql
import toolforge


class BaseDatabase:
    def __init__(self):
        self.open = 0
        self.database = None

    def get_connection(self) -> pymysql.Connection:
        raise NotImplementedError()

    def request(self):
        if self.open < 1 or self.database is None:
            self.database = self.get_connection()
        self.open += 1

    def close(self):
        self.open -= 1
        if self.open < 1:
            self.database.close()
            self.database = None

    @contextmanager
    def connected(self):
        self.request()
        yield self.database
        self.close()

    @contextmanager
    def cursor(self):
        with self.connected() as database:
            yield database.cursor()

    def get_one(self, sql: str, params=None):
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchone()

    def get_all(self, sql: str, params=None):
        with self.cursor() as cursor:
            cursor.execute(sql, params)
            return cursor.fetchall()

    def insert(self, sql: str, params=None):
        with self.connected() as database:
            with database.cursor() as cursor:
                cursor.execute(sql, params)
                database.commit()

    def update(self, sql: str, params=None) -> int:
        with self.connected() as database:
            with database.cursor() as cursor:
                cursor.execute(sql, params)
                database.commit()

                return cursor.lastrowid


class ReplicaDatabase(BaseDatabase):
    def __init__(self, db: str):
        super().__init__()
        self.db_name = db

    def get_connection(self) -> pymysql.Connection:
        return toolforge.connect(
            self.db_name,
            cluster="analytics",
            charset="utf8",
            cursorclass=pymysql.cursors.DictCursor,  # type: ignore
        )

    def get_replag(self):
        results = self.get_one("SELECT lag FROM heartbeat_p.heartbeat;")
        return results["lag"]
