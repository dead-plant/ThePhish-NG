import logging
from typing import Literal
import thehive4py
from thehive4py.types.case_template import OutputCaseTemplate
from thehive4py.types.case import OutputCase, ImpactStatusValue, CaseStatusValue
from thehive4py.types.observable import OutputObservable
from thehive4py.types.task import OutputTask
from thehive4py.types.cortex import OutputResponderAction, OutputAnalyzerJob
from app import config

log = logging.getLogger(__name__)


TaskStatusValue = Literal[
    "Waiting",
    "InProgress",
    "Completed",
    "Cancel",
]

# case_templates
def find_case_template_by_name(name: str) -> list[OutputCaseTemplate]:
    ...

def create_case_template(*, name: str, title_prefix: str, tasks: list[thehive4py.types.task.InputTask]) -> OutputCaseTemplate:
    ...

#case
def create_case(*, title: str, tlp: int, pap: int, flag: bool, tags: list[str], description: str, template: str) -> OutputCase:
    ...

def update_case(case_id: str, *, status: CaseStatusValue) -> None:
    ...

def export_case(case_id: str, misp_id: str) -> None:
    ...

def close_case(*, case_id: str, resolution_status: CaseStatusValue, impact_status: ImpactStatusValue, summary: str) -> None:
    ...

# observables
def create_observable(*, case_id: str, data_type: str, data: str, ioc: bool = False, tags: list[str] | None = None, message: str = "") -> list[OutputObservable]:
    ...

def create_file_observable(*, case_id: str, file_path: str, ioc: bool = False, tags: list[str] | None = None, message: str = "") -> list[OutputObservable]:
    ...

def find_all_observables(case_id: str) -> list[OutputObservable]:
    ...

def get_observable(observable_id: str) -> OutputObservable:
    ...

def update_observable(observable_id: str, *, ioc: bool) -> None:
    ...

# tasks
def update_task(task_id: str, *, description: str | None = None, status: TaskStatusValue | None = None) -> None:
    ...

def find_all_tasks(case_id: str) -> list[OutputTask]:
    ...

# jobs
def create_responder_action(*, responder_id: str, object_type: str, object_id: str) -> OutputResponderAction:
    ...

def create_analyzer_job(*, cortex_id: str, artifact_id: str, analyzer_id: str, parameters: dict | None = None) -> OutputAnalyzerJob:
    ...
