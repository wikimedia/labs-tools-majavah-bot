from flask import Blueprint, render_template

from majavahbot.api.consts import *
from majavahbot.api.database import TaskDatabase
from majavahbot.api.utils import get_revision
from majavahbot.tasks import task_registry

blueprint = Blueprint("majavah-bot", __name__)


def map_task(db_row):
    registry_task = task_registry.get_task_by_number(db_row["id"])
    return {
        "number": db_row["id"],
        "name": db_row["name"],
        "is_continuous": registry_task.is_continuous,
        "site": registry_task.site,
        "family": registry_task.family,
        "approved": db_row["approved"] == 1,
        "trial": db_row["in_trial"] == 1,
    }


# utils to be used in tempale
def get_badge_color_for_status(status):
    return {
        JOB_STATUS_RUNNING: "badge-info",
        JOB_STATUS_DONE: "badge-success",
        JOB_STATUS_FAIL: "badge-danger",
    }[status]


def format_duration(job):
    started_at = job["started_at"]
    ended_at = job["ended_at"]
    duration = ended_at - started_at
    hours, remainder = divmod(duration.total_seconds(), 3600)
    minutes, seconds = divmod(remainder, 60)
    return "{:02.0f}:{:02.0f}:{:02.0f}".format(hours, minutes, seconds)


@blueprint.context_processor
def inject_base_variables():
    return {
        "revision": get_revision(),
    }


@blueprint.route("/")
def index():
    db = TaskDatabase()
    db.request()
    db.init()
    task_registry.add_all_tasks()
    jobs = db.get_all(
        "select id, status, job_name, task_id, task_wiki, started_at, ended_at from jobs order by `started_at` desc limit 20;"
    )
    tasks = db.get_all(
        """
    select
    id, name, approved,
    exists(select id from task_trials where task_id = tasks.id and closed != 1) as in_trial
    from tasks
    order by `id`
    """
    )
    db.close()

    return render_template(
        "index.html",
        jobs=jobs,
        tasks=map(map_task, tasks),
        get_badge_color_for_status=get_badge_color_for_status,
        format_duration=format_duration,
    )


@blueprint.route("/jobs/wiki/<wiki>")
def jobs_per_wiki(wiki):
    db = TaskDatabase()
    db.request()
    db.init()
    task_registry.add_all_tasks()
    jobs = db.get_all(
        "select id, status, job_name, task_id, task_wiki, started_at, ended_at from jobs where task_wiki = %s order by `started_at` desc limit 20",
        (wiki,),
    )
    db.close()

    return render_template(
        "per_wiki.html",
        wiki=wiki,
        jobs=jobs,
        get_badge_color_for_status=get_badge_color_for_status,
        format_duration=format_duration,
    )
