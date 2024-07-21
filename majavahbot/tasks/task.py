import json
import os
from datetime import datetime
from importlib import import_module
from typing import Any

from majavahbot.api import MediawikiApi, get_mediawiki_api
from majavahbot.api.utils import remove_comments


class Task:
    def __init__(self, task_id: str, name: str, site: str, family: str) -> None:
        self.task_id = task_id
        self.name = name
        self.site = site
        self.family = family

        self.param = ""

        self.is_continuous = False
        self.supports_manual_run = False
        self.is_manual_run = False

        self.task_configuration: dict[str, Any] = {}
        self.base_task_configuration: dict[str, Any] = {}
        self.task_configuration_page: str | None = None
        self.task_configuration_last_loaded: datetime | None = None

    def __repr__(self) -> str:
        return "Task(task_id=" + self.task_id + ",name=" + self.name + ")"

    def run(self) -> None:
        raise Exception("Not implemented yet")

    def do_manual_run(self) -> None:
        self.is_manual_run = True

        if self.supports_manual_run:
            self.run()
            return
        raise Exception("This task does not support manual runs")

    def should_use_bot_flag(self) -> bool:
        return True

    def get_mediawiki_api(self) -> MediawikiApi:
        return get_mediawiki_api(self.site, self.family)

    def task_configuration_reloaded(
        self, old: dict[str, Any], new: dict[str, Any]
    ) -> None:
        pass

    def _load_task_configuration(self, contents: str) -> None:
        config_text = remove_comments(contents)

        if len(config_text) == 0:
            config_text = "{}"

        config = json.loads(config_text)

        self.task_configuration = config
        self._merge_task_configuration()

        self.task_configuration_reloaded(self.task_configuration, config)
        self.task_configuration_last_loaded = datetime.now()

    def register_task_configuration(self, config_page_name: str) -> None:
        self.task_configuration_page = config_page_name

    def get_task_configuration(self, key: str = "") -> Any:
        if not self.task_configuration_page:
            raise RuntimeError("No task configuration registered")
        if (
            self.task_configuration_last_loaded is None
            or (datetime.now() - self.task_configuration_last_loaded).total_seconds()
            > 60 * 15
        ):
            api = self.get_mediawiki_api()
            page = api.get_page(self.task_configuration_page)
            self._load_task_configuration(page.text)

        if len(key) == 0:
            return self.task_configuration

        # TODO: support for nested keys
        return self.task_configuration[key]

    def merge_task_configuration(self, **fill: Any) -> None:
        self.base_task_configuration = fill
        self._merge_task_configuration()

    def _merge_task_configuration(self) -> None:
        for key in self.base_task_configuration:
            value = self.base_task_configuration[key]
            if key not in self.task_configuration:
                self.task_configuration[key] = value


class TaskRegistry:
    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def add_task(self, task: Task) -> None:
        self.tasks.append(task)

    def get_tasks(self) -> list[Task]:
        tasks = list(self.tasks)
        tasks.sort(key=(lambda task: task.task_id))
        return tasks

    def get_task_by_id(self, task_id: str) -> Task | None:
        for task in self.get_tasks():
            if task.task_id == task_id:
                return task
        return None

    def add_all_tasks(self) -> None:
        for module in os.listdir(os.path.dirname(__file__)):
            if (
                module == "__init__.py"
                or module == "task.py"
                or module[-3:] != ".py"
                or module.endswith("_test.py")
            ):
                continue
            name = "majavahbot.tasks." + module[:-3]
            import_module(name)


task_registry = TaskRegistry()
