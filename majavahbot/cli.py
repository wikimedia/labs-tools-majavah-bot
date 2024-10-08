import argparse
import json
import logging
from sys import exit

import toolforge

from majavahbot.api import ReplicaDatabase, get_mediawiki_api
from majavahbot.tasks import task_registry

task_registry.add_all_tasks()


LOGGER = logging.getLogger(__name__)


def cli_whoami():
    api = get_mediawiki_api()
    LOGGER.info("I am %s", api)


def cli_task_list():
    for task in task_registry.get_tasks():
        LOGGER.info(
            "Task %s (%s) on wiki %s.%s",
            task.task_id,
            task.name,
            task.site,
            task.family,
        )


def cli_check_replica(name: str):
    db = ReplicaDatabase(name)
    LOGGER.info(
        "Successfully connected to %s. Replag is %s seconds.",
        db.db_name,
        str(db.get_replag()),
    )


def cli_task(task_id: str, run: bool, manual: bool, config: bool, param=""):
    task = task_registry.get_task_by_id(task_id)
    if task is None:
        LOGGER.error("Task not found")
        exit(1)

    task.param = param

    if config:
        LOGGER.info("Task configuration for task %s", task.task_id)
        LOGGER.info(json.dumps(task.get_task_configuration()))
        exit(0)

    if run:
        LOGGER.info("Starting task %s", task.task_id)
        task.run()
    elif manual:
        LOGGER.info("Manually running task %s", task.task_id)
        task.do_manual_run()
    else:
        LOGGER.error("Unknown action")
        exit(1)


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(name)-32s %(levelname)-8s: %(message)s",
    )

    toolforge.set_user_agent("majavah-bot")

    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="subparser", required=True)

    subparsers.add_parser("whoami")
    subparsers.add_parser("task_list")

    replica_parser = subparsers.add_parser("check_replica")
    replica_parser.add_argument(
        "name", metavar="name", help="Database name to check connectivity to", type=str
    )

    task_parser = subparsers.add_parser("task")
    task_parser.add_argument("task_id", help="Task ID")
    task_parser.add_argument(
        "--run",
        dest="run",
        action="store_true",
        default=False,
        help="Run the task",
    )
    task_parser.add_argument(
        "--manual",
        dest="manual",
        action="store_true",
        default=False,
        help="Manually runs the task",
    )
    task_parser.add_argument(
        "--config",
        dest="config",
        action="store_true",
        default=False,
        help="Shows the task configuration",
    )
    task_parser.add_argument(
        "--param",
        dest="param",
        default="",
        help="Additional param passed to the job",
    )

    kwargs = vars(parser.parse_args())
    subparser = kwargs.pop("subparser")

    globals()["cli_" + subparser](**kwargs)
