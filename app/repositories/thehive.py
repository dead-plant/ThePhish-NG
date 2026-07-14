import logging
from typing import Literal, Optional, TypedDict, Final
from thehive4py import TheHiveApi
from thehive4py.types.case import OutputCase, ImpactStatusValue, CaseStatusValue
from thehive4py.types.case_template import OutputCaseTemplate
from thehive4py.types.cortex import OutputResponderAction, OutputAnalyzerJob, OutputAnalyzer, OutputResponder
from thehive4py.types.observable import OutputObservable
from thehive4py.types.task import OutputTask, InputTask
from app import config

log = logging.getLogger(__name__)

# create thehive4py api client
try:
    url = config.get_app_config()["thehive"]["url"]
    apikey = config.get_app_config()["thehive"]["apikey"]
    tls_verify = config.get_app_config()["thehive"]["tls_verify"]

    if type(tls_verify) != bool:
        raise TypeError("thehive.tls_verify must be a boolean")

    _client: Final = TheHiveApi(url=url, apikey=apikey, verify=tls_verify)
    log.info("Created TheHiveApi instance")
except Exception as exc:
    log.error("Failed to create TheHiveApi instance", exc_info=exc)
    raise exc

# types
TaskStatusValue = Literal[
    "Waiting",
    "InProgress",
    "Completed",
    "Cancel",
]


class AnalyzerJob(TypedDict):
    artifact_id: str
    analyzer_id: str


# exceptions
class TheHiveRequestError(Exception):
    """Thrown when the request to the TheHive api fails"""


# case_template
def find_case_template_by_name(name: str) -> Optional[OutputCaseTemplate]:
    """Find a case template by its exact name.

    Args:
        name: Name of the case template.

    Returns:
        Found case template. None if not found.
    """
    ...


def create_case_template_unless_exists(*, name: str, title_prefix: str, tasks: list[InputTask]) -> OutputCaseTemplate:
    """Create a case template unless a case with this name already exists.

    Args:
        name: Unique name of the case template.
        title_prefix: Prefix of cases created with this template.
        tasks: List of tasks added to the case.

    Returns:
        Created or existing case template.
    """
    ...


# case
def create_case(*, title: str, tlp: int, pap: int, tags: list[str], description: str, template: str, flag: bool = False) -> OutputCase:
    """Create a case.

        Args:
            title: Title of the case.
            tlp: TLP of the case.
            pap: PAP of the case.
            tags: List of tags added to the case.
            description: Description of the case.
            template: Template used to create the case.
            flag: Flag the case. Defaults to False.

        Returns:
            The created case.
    """
    ...


def update_case(case_id: str, *, status: CaseStatusValue) -> None:
    """Update a case.
        Args:
            case_id: Id of the case to update.
            status: New status of the case.

        Returns:
            N/A
    """
    ...


def export_case(case_id: str, misp_id: str) -> None:
    """Export a case to MISP.
        Args:
            case_id: Id of the case to export.
            misp_id: MISP Instance the case gets exported to.

        Returns:
            N/A
    """
    ...


def close_case(*, case_id: str, status: CaseStatusValue, summary: str, impact_status: ImpactStatusValue = "NotApplicable") -> None:
    """Close a case.
        Args:
            case_id: The id of the case.
            status: The status to close the case with.
            summary: The closure summary of the case.
            impact_status: The impact status of the case.

        Returns:
            N/A
    """
    ...


# observables
def create_observable(*, case_id: str, data_type: str, data: str, ioc: bool = False, tags: list[str] | None = None, message: str = "") -> OutputObservable:
    """Create an observable.
        Args:
            case_id: Id of the case the observable will be added to.
            data_type: Data type of the observable.
            data: Data/Vaule of the observable.
            ioc: IoC flag of the observable.
            tags: List of tags added to the observable.
            message: Description of the observable.

        Returns:
            The created observable.
    """
    ...


def create_file_observable(*, case_id: str, file_path: str, ioc: bool = False, tags: list[str] | None = None, message: str = "") -> OutputObservable:
    """Create an observable from a file. Always has the data_type 'file'.
        Args:
            case_id: Id of the case the observable will be added to.
            file_path: File to upload and attach to the observable.
            ioc: IoC flag of the observable.
            tags: List of tags added to the observable.
            message: Description of the observable.

        Returns:
            The created observable.
    """
    ...


def find_all_observables(case_id: str) -> list[OutputObservable]:
    """Find all observables in a case.
        Args:
            case_id: Id of the case.

        Returns:
            List containing all observables in the case.
    """
    ...


def get_observable(observable_id: str) -> OutputObservable:
    """Get a specific observable.
        Args:
            observable_id: Id of the observable.

        Returns:
            The observable.
    """
    ...


def update_observable(observable_id: str, *, ioc: bool) -> None:
    """Update an observable.
        Args:
            observable_id: Id of the observable.
            ioc: IoC flag of the observable.

        Returns:
            N/A
    """
    ...


def bulk_update_observables(observable_ids: list[str], *, ioc: bool) -> None:
    """Bulk update multiple observables.
        Args:
            observable_ids: List of the observables to update.
            ioc: IoC flag of the observables.

        Returns:
            N/A
    """
    ...


# tasks
def update_task(task_id: str, *, description: str | None = None, status: TaskStatusValue | None = None) -> None:
    """Update a task.
        Args:
            task_id: Id of the task.
            description: New description of the task.
            status: New status of the task.

        Returns:
            N/A
    """
    ...


def bulk_update_tasks(task_ids: list[str], *, description: str | None = None, status: TaskStatusValue | None = None) -> None:
    """Bulk update multiple tasks.
        Args:
            task_ids: List of the tasks to update.
            description: New description of the tasks.
            status: New status of the tasks.

        Returns:
            N/A
    """
    ...


def find_all_tasks(case_id: str) -> list[OutputTask]:
    """Find all tasks in a case.
        Args:
            case_id: Id of the case.

        Returns:
            List containing all tasks in the case.
    """
    ...


# responders
def create_responder_action(*, responder_id: str, object_type: str, object_id: str) -> OutputResponderAction:
    """Create a responder action.
        Args:
            responder_id: Id of the responder.
            object_type: TheHive entity type the responder runs on ("case", "case_task", ...).
            object_id: _id of that entity.

        Returns:
            The created responder action.
    """
    ...


def list_responders_for_entity(entity_type: str, entity_id: str = "") -> list[OutputResponder]:
    """List all responders compatible with a given entity type.
    Args:
        entity_type: The entity type to list responders for.
        entity_id: [Optional] The entity id to list responders for.

    Returns:
            List containing all the applicable responders.
    """
    ...


def get_responder_action(entity_type: str, entity_id: str) -> OutputResponderAction:
    """Get a responder action.
        Args:
            entity_type: The entity type.
            entity_id: The entity id.

        Returns:
            The Responder action.

        Implemented using manual api request: https://docs.strangebee.com/thehive/api-docs/#tag/Cortex/operation/Get%20action%20by%20entity
    """
    ...


# analyzers
def create_analyzer_job(cortex_id: str, analyzer_job: AnalyzerJob) -> OutputAnalyzerJob:
    """Create an analyzer job.
        Args:
            cortex_id: ID of the cortex server to run the job on.
            analyzer_job: AnalyzerJob dict containing information about the job to create.

        Returns:
            The created analyzer job.
    """
    ...


def bulk_create_analyzer_jobs(cortex_id: str, analyzer_jobs: list[AnalyzerJob]) -> list[OutputAnalyzerJob]:
    """Create multiple analyzer jobs.
        Args:
            cortex_id: ID of the cortex server to run the job on.
            analyzer_jobs: List of analyzerJob dicts containing information about the job to create.

        Returns:
            The created analyzer job.
    """
    ...


def list_analyzers_by_type(data_type: str) -> list[OutputAnalyzer]:
    """List all analyzers compatible with a given data type.
        Args:
            data_type: The data type to list analyzers for.

        Returns:
            List containing all the applicable analyzers.
    """
    ...


def get_analyzer_job(job_id: str) -> OutputAnalyzerJob:
    """Get an analyzer job by id.
        Args:
            job_id: The id of the analyzer job to get.

        Returns:
            The analyzer job specified by the id.
        """
    ...
