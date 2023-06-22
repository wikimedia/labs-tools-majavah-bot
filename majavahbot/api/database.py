from contextlib import contextmanager
from datetime import datetime

import pymysql
import toolforge

from majavahbot.api.consts import JOB_STATUS_RUNNING
from majavahbot.config import own_db_database


class BaseDatabase:
    def __init__(self):
        self.open = 0
        self.database = None

    def get_connection(self) -> pymysql.Connection:
        raise NotImplemented()

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
        super.__init__()
        self.db_name = db

    def get_connection(self) -> pymysql.Connection:
        return toolforge.connect(
            self.db_name,
            cluster="analytics",
            cursorclass=pymysql.cursors.DictCursor,
        )

    def get_replag(self):
        results = self.get_one("SELECT lag FROM heartbeat_p.heartbeat;")
        return results["lag"]


class TaskDatabase(BaseDatabase):
    def get_connection(self) -> pymysql.Connection:
        return toolforge.toolsdb(
            own_db_database, cursorclass=pymysql.cursors.DictCursor
        )

    def init(self):
        with self.connected():
            self.update(
                "create table if not exists tasks (id integer primary key not null, name varchar(255) not null,"
                "approved tinyint(1) default 0 not null);"
            )
            self.update(
                "create table if not exists task_trials (id integer primary key auto_increment not null,"
                "task_id integer not null, created_at timestamp default current_timestamp not null,"
                "max_days integer default 0 not null, max_edits integer default 0 not null,"
                "edits_done integer default 0 not null, closed tinyint(1) default 0 not null);"
            )
            self.update(
                "create table if not exists jobs (id integer primary key auto_increment not null,"
                "status varchar(16) not null, job_name varchar(64) not null,"
                "task_id integer not null, task_wiki varchar(16) not null,"
                "started_at timestamp not null default now(), ended_at timestamp default 0);"
            )

    def insert_task(self, number, name):
        self.update(
            "insert into tasks(id, name) values (%s, %s) on duplicate key update name = %s;",
            (number, name, name),
        )

    def is_approved(self, number) -> bool:
        results = self.get_one(
            "select approved from tasks where id = %s limit 1;", (number,)
        )
        return bool(results["approved"])

    def get_trial(self, number):
        results = self.get_one(
            "select * from task_trials where task_id = %s "
            "order by created_at desc limit 1",
            (number,),
        )

        if results is None:
            return None

        results = {
            "id": results["id"],
            "task_id": results["task_id"],
            "created_at": results["created_at"],
            "max_days": results["max_days"],
            "max_edits": results["max_edits"],
            "edits_done": results["edits_done"],
            "closed": results["closed"] == 1,
        }

        if results["max_days"] >= 0 and (
            datetime.now() - results["created_at"]
        ).total_seconds() > (results["max_days"] * 86400):
            return None

        if results["max_edits"] and results["edits_done"] >= results["max_edits"]:
            return None

        return results

    def record_trial_edit(self, trial_id: int):
        self.update(
            "update task_trials set edits_done = edits_done + 1 where id = %s;",
            (trial_id,),
        )

    def start_job(self, job_name: str, task_id: int, task_wiki: str):
        return self.insert(
            "insert into jobs (job_name, task_id, task_wiki, status, started_at) values (%s, %s, %s, %s, CURRENT_TIMESTAMP())",
            (
                job_name,
                task_id,
                task_wiki,
                JOB_STATUS_RUNNING,
            ),
        )

    def stop_job(self, job_id: str, status: str):
        self.update(
            "update jobs set ended_at=current_timestamp(), status = %s where id = %s",
            (
                status,
                job_id,
            ),
        )
