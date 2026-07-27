import functools
import logging
import os
import threading
from typing import Literal, Optional, TypedDict, Final, get_args

import requests
from thehive4py import TheHiveApi
from thehive4py.errors import TheHiveError
from thehive4py.query.filters import Eq
from thehive4py.query.sort import Desc
from thehive4py.types.case import InputCase, InputUpdateCase, OutputCase, ImpactStatusValue, CaseStatusValue
from thehive4py.types.case_template import InputCaseTemplate, OutputCaseTemplate
from thehive4py.types.cortex import InputAnalyzerJob, InputResponderAction, OutputResponderAction, OutputAnalyzerJob, OutputAnalyzer, OutputResponder
from thehive4py.types.observable import InputBulkUpdateObservable, InputObservable, InputUpdateObservable, OutputObservable
from thehive4py.types.task import InputBulkUpdateTask, InputUpdateTask, OutputTask, InputTask
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
class TheHiveApiError(Exception):
    """Thrown when the request to the TheHive api fails"""


# locks
# guards the check-then-create in create_case_template_unless_exists
_case_template_lock: Final = threading.Lock()


# internal helpers
def _wrap_api_errors(func):
    """Wrap errors raised by the TheHive api in a custom exception."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (TheHiveError, requests.RequestException) as exc:
            raise TheHiveApiError(f"TheHive request '{func.__name__}' failed: {exc}") from exc

    return wrapper


def _require_str(**fields: str) -> None:
    """Validate that every given keyword argument is a non-empty string.

    Raises:
        ValueError: If a field is not a non-empty string.
    """
    for name, value in fields.items():
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} must be a non-empty string")


def _require_literal(value: str, literal_type, name: str) -> None:
    """Validate that value is one of the allowed values of a Literal type.

    Raises:
        ValueError: If the value is not allowed.
    """
    allowed = get_args(literal_type)
    if value not in allowed:
        raise ValueError(f"{name} must be one of {allowed}, got {value!r}")


# case_template
@_wrap_api_errors
def find_case_template_by_name(name: str) -> Optional[OutputCaseTemplate]:
    """Find a case template by its exact name.

    Args:
        name: Name of the case template.

    Returns:
        Found case template. None if not found.
    """
    _require_str(name=name)

    templates = _client.case_template.find(filters=Eq("name", name))
    log.debug("Found %d case template(s) with name %r", len(templates), name)
    return templates[0] if templates else None


@_wrap_api_errors
def create_case_template_unless_exists(*, name: str, title_prefix: str, tasks: list[InputTask]) -> OutputCaseTemplate:
    """Create a case template unless a case with this name already exists.

    Args:
        name: Unique name of the case template.
        title_prefix: Prefix of cases created with this template.
        tasks: List of tasks added to the case.

    Returns:
        Created or existing case template.
    """
    _require_str(name=name, title_prefix=title_prefix)
    if not isinstance(tasks, list):
        raise ValueError("tasks must be a list of tasks")

    # serialize the check-then-create to prevent two threads from both seeing "not found" and sending the create request twice
    with _case_template_lock:
        existing = find_case_template_by_name(name)
        if existing is not None:
            log.debug("Case template %r already exists with id %s", name, existing["_id"])
            return existing

        case_template: InputCaseTemplate = {
            "name": name,
            "titlePrefix": title_prefix,
            "tasks": tasks,
        }
        created = _client.case_template.create(case_template)
        log.debug("Created case template %r with id %s", name, created["_id"])
        return created


# case
@_wrap_api_errors
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
    _require_str(title=title, description=description, template=template)
    if not isinstance(tlp, int) or not 0 <= tlp <= 4:
        raise ValueError("tlp must be an integer between 0 and 4")
    if not isinstance(pap, int) or not 0 <= pap <= 3:
        raise ValueError("pap must be an integer between 0 and 3")

    if not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags):
        raise ValueError("tags must be a list of non-empty strings")

    if not isinstance(flag, bool):
        raise ValueError("flag must be a boolean")

    case: InputCase = {
        "title": title,
        "description": description,
        "tlp": tlp,
        "pap": pap,
        "tags": tags,
        "caseTemplate": template,
        "flag": flag,
    }
    created = _client.case.create(case)
    log.debug("Created case %r with id %s", title, created["_id"])
    return created


@_wrap_api_errors
def get_case(case_id: str) -> OutputCase:
    """Get a specific case.
        Args:
            case_id: Id of the case.

        Returns:
            The case.
    """
    _require_str(case_id=case_id)

    return _client.case.get(case_id)


@_wrap_api_errors
def find_case(*, status: CaseStatusValue | None = None, tags: list[str] | None = None) -> list[OutputCase]:
    """Find a case by search parameters, sorted: newest -> oldest.

    Args:
        status: Filter for status of the cases.
        tags: Each case has to contain all of these tags.

    Returns:
        List of found cases. Empty if none found.
    """
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) and tag.strip() for tag in tags)):
        raise ValueError("tags must be a list of non-empty strings")

    filter_exprs = []
    if status is not None:
        _require_literal(status, CaseStatusValue, "status")
        filter_exprs.append(Eq("status", status))
    # one Eq per tag, combined with "and", so a case must contain all of them
    filter_exprs.extend(Eq("tags", tag) for tag in (tags or []))

    filters = functools.reduce(lambda left, right: left & right, filter_exprs) if filter_exprs else None
    cases = _client.case.find(filters=filters, sortby=Desc("_createdAt"))
    log.debug("Found %d case(s) for status=%s tags=%s", len(cases), status, tags)
    return cases

@_wrap_api_errors
def update_case(case_id: str, *, status: CaseStatusValue) -> None:
    """Update a case.
        Args:
            case_id: Id of the case to update.
            status: New status of the case.

        Returns:
            N/A
    """
    _require_str(case_id=case_id)
    _require_literal(status, CaseStatusValue, "status")

    fields: InputUpdateCase = {"status": status}
    _client.case.update(case_id, fields=fields)
    log.debug("Updated case %s to status %s", case_id, status)


@_wrap_api_errors
def export_case(case_id: str, misp_id: str) -> None:
    """Export a case to MISP.
        Args:
            case_id: Id of the case to export.
            misp_id: MISP Instance the case gets exported to.

        Returns:
            N/A
    """
    _require_str(case_id=case_id, misp_id=misp_id)

    _client.misp.export_case(case_id=case_id, misp_name=misp_id)
    log.debug("Exported case %s to MISP instance %s", case_id, misp_id)


@_wrap_api_errors
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
    _require_str(case_id=case_id, summary=summary)
    _require_literal(status, CaseStatusValue, "status")
    _require_literal(impact_status, ImpactStatusValue, "impact_status")

    _client.case.close(case_id, status=status, summary=summary, impact_status=impact_status)
    log.debug("Closed case %s with status %s", case_id, status)


# observables
@_wrap_api_errors
def create_observable(*, case_id: str, data_type: str, data: list[str], ioc: bool = False, tags: list[str] | None = None, message: str = "") -> list[OutputObservable]:
    """Create one or more observables of the same data type.
        Args:
            case_id: Id of the case the observables will be added to.
            data_type: Data type of the observables.
            data: List of single line data/values, one observable is created per entry.
            ioc: IoC flag of the observables.
            tags: List of tags added to the observables.
            message: Description of the observables.

        Returns:
            The created observables.
    """
    _require_str(case_id=case_id, data_type=data_type)
    if not isinstance(data, list) or not data or not all(isinstance(entry, str) and entry.strip() for entry in data):
        raise ValueError("data must be a non-empty list of non-empty strings")
    if not isinstance(ioc, bool):
        raise ValueError("ioc must be a boolean")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
        raise ValueError("tags must be a list of strings")
    if not isinstance(message, str):
        raise ValueError("message must be a string")

    observable: InputObservable = {
        "dataType": data_type,
        "data": data,
        "ioc": ioc,
        "tags": tags or [],
        "message": message,
    }
    # thehive creates one observable per data entry in a single request
    created = _client.observable.create_in_case(case_id, observable)
    log.debug("Created %d observable(s) of type %s in case %s", len(created), data_type, case_id)
    return created


@_wrap_api_errors
def create_file_observable(*, case_id: str, file_path: str, ioc: bool = False, tags: list[str] | None = None, message: str = "", is_zip: bool = False) -> OutputObservable:
    """Create an observable from a file. Always has the data_type 'file'.
        Args:
            case_id: Id of the case the observable will be added to.
            file_path: File to upload and attach to the observable.
            ioc: IoC flag of the observable.
            tags: List of tags added to the observable.
            message: Description of the observable.
            is_zip: Let thehive unpack the uploaded file as a zip archive.

        Returns:
            The created observable.
    """
    _require_str(case_id=case_id, file_path=file_path)
    if not os.path.isfile(file_path):
        raise ValueError(f"file_path does not point to an existing file: {file_path}")
    if not isinstance(ioc, bool):
        raise ValueError("ioc must be a boolean")
    if tags is not None and (not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags)):
        raise ValueError("tags must be a list of strings")
    if not isinstance(message, str):
        raise ValueError("message must be a string")
    if not isinstance(is_zip, bool):
        raise ValueError("is_zip must be a boolean")

    observable: InputObservable = {
        "dataType": "file",
        "ioc": ioc,
        "tags": tags or [],
        "message": message,
        "isZip": is_zip,
    }
    created = _client.observable.create_in_case(case_id, observable, observable_path=file_path)
    log.debug("Created file observable from %s in case %s (is_zip=%s)", file_path, case_id, is_zip)

    return created[0]


@_wrap_api_errors
def find_all_observables(case_id: str) -> list[OutputObservable]:
    """Find all observables in a case.
        Args:
            case_id: Id of the case.

        Returns:
            List containing all observables in the case.
    """
    _require_str(case_id=case_id)

    observables = _client.case.find_observables(case_id)
    log.debug("Found %d observable(s) in case %s", len(observables), case_id)
    return observables


@_wrap_api_errors
def get_observable(observable_id: str) -> OutputObservable:
    """Get a specific observable.
        Args:
            observable_id: Id of the observable.

        Returns:
            The observable.
    """
    _require_str(observable_id=observable_id)

    return _client.observable.get(observable_id)


@_wrap_api_errors
def update_observable(observable_id: str, *, ioc: bool) -> None:
    """Update an observable.
        Args:
            observable_id: Id of the observable.
            ioc: IoC flag of the observable.

        Returns:
            N/A
    """
    _require_str(observable_id=observable_id)
    if not isinstance(ioc, bool):
        raise ValueError("ioc must be a boolean")

    fields: InputUpdateObservable = {"ioc": ioc}
    _client.observable.update(observable_id, fields)
    log.debug("Updated observable %s (ioc=%s)", observable_id, ioc)


@_wrap_api_errors
def bulk_update_observables(observable_ids: list[str], *, ioc: bool) -> None:
    """Bulk update multiple observables.
        Args:
            observable_ids: List of the observables to update.
            ioc: IoC flag of the observables.

        Returns:
            N/A
    """
    if not isinstance(observable_ids, list) or not observable_ids or not all(isinstance(oid, str) and oid.strip() for oid in observable_ids):
        raise ValueError("observable_ids must be a non-empty list of non-empty strings")
    if not isinstance(ioc, bool):
        raise ValueError("ioc must be a boolean")

    fields: InputBulkUpdateObservable = {"ids": observable_ids, "ioc": ioc}
    _client.observable.bulk_update(fields)
    log.debug("Bulk updated %d observable(s) (ioc=%s)", len(observable_ids), ioc)


# tasks
@_wrap_api_errors
def update_task(task_id: str, *, description: str | None = None, status: TaskStatusValue | None = None) -> None:
    """Update a task.
        Args:
            task_id: Id of the task.
            description: New description of the task.
            status: New status of the task.

        Returns:
            N/A
    """
    _require_str(task_id=task_id)
    if description is None and status is None:
        raise ValueError("at least one of description or status must be given")

    fields: InputUpdateTask = {}
    if description is not None:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        fields["description"] = description
    if status is not None:
        _require_literal(status, TaskStatusValue, "status")
        fields["status"] = status

    _client.task.update(task_id, fields)
    log.debug("Updated task %s with fields %s", task_id, list(fields.keys()))


@_wrap_api_errors
def bulk_update_tasks(task_ids: list[str], *, description: str | None = None, status: TaskStatusValue | None = None) -> None:
    """Bulk update multiple tasks.
        Args:
            task_ids: List of the tasks to update.
            description: New description of the tasks.
            status: New status of the tasks.

        Returns:
            N/A
    """
    if not isinstance(task_ids, list) or not task_ids or not all(isinstance(tid, str) and tid.strip() for tid in task_ids):
        raise ValueError("task_ids must be a non-empty list of non-empty strings")
    if description is None and status is None:
        raise ValueError("at least one of description or status must be given")

    fields: InputBulkUpdateTask = {"ids": task_ids}
    if description is not None:
        if not isinstance(description, str):
            raise ValueError("description must be a string")
        fields["description"] = description
    if status is not None:
        _require_literal(status, TaskStatusValue, "status")
        fields["status"] = status

    _client.task.bulk_update(fields)
    log.debug("Bulk updated %d task(s)", len(task_ids))


@_wrap_api_errors
def find_all_tasks(case_id: str) -> list[OutputTask]:
    """Find all tasks in a case.
        Args:
            case_id: Id of the case.

        Returns:
            List containing all tasks in the case.
    """
    _require_str(case_id=case_id)

    tasks = _client.case.find_tasks(case_id)
    log.debug("Found %d task(s) in case %s", len(tasks), case_id)
    return tasks


# responders
@_wrap_api_errors
def create_responder_action(*, responder_id: str, object_type: str, object_id: str) -> OutputResponderAction:
    """Create a responder action.
        Args:
            responder_id: Id of the responder.
            object_type: TheHive entity type the responder runs on ("case", "case_task", ...).
            object_id: _id of that entity.

        Returns:
            The created responder action.
    """
    _require_str(responder_id=responder_id, object_type=object_type, object_id=object_id)

    action: InputResponderAction = {
        "responderId": responder_id,
        "objectType": object_type,
        "objectId": object_id,
    }
    created = _client.cortex.create_responder_action(action)
    log.debug("Created responder action %s on %s %s", responder_id, object_type, object_id)
    return created


@_wrap_api_errors
def list_responders_for_entity(entity_type: str, entity_id: str) -> list[OutputResponder]:
    """List all responders compatible with a given entity.

    Note: thehive resolves the concrete entity (and its TLP/PAP) before listing
    applicable responders, so the entity id is required by the api.

    Args:
        entity_type: The entity type to list responders for.
        entity_id: The entity id to list responders for.

    Returns:
            List containing all the applicable responders.
    """
    _require_str(entity_type=entity_type, entity_id=entity_id)

    return _client.cortex.list_responders(entity_type, entity_id)


@_wrap_api_errors
def get_responder_action(entity_type: str, entity_id: str) -> OutputResponderAction:
    """Get a responder action.
        Args:
            entity_type: The entity type.
            entity_id: The entity id.

        Returns:
            The Responder action.

        Implemented using manual api request: https://docs.strangebee.com/thehive/api-docs/#tag/Cortex/operation/Get%20action%20by%20entity
    """
    _require_str(entity_type=entity_type, entity_id=entity_id)

    log.debug("Fetching responder action for %s %s via manual request", entity_type, entity_id)
    response = _client.session.make_request(
        "GET", path=f"/api/connector/cortex/action/{entity_type}/{entity_id}"
    )

    # the endpoint returns a list of actions for the entity; the most recent
    # action comes first, so return that one to match the declared return type
    if isinstance(response, list):
        if not response:
            raise TheHiveApiError(f"No responder action found for {entity_type} {entity_id}")
        return response[0]
    return response


# analyzers
@_wrap_api_errors
def create_analyzer_job(cortex_id: str, analyzer_job: AnalyzerJob) -> OutputAnalyzerJob:
    """Create an analyzer job.
        Args:
            cortex_id: ID of the cortex server to run the job on.
            analyzer_job: AnalyzerJob dict containing information about the job to create.

        Returns:
            The created analyzer job.
    """
    _require_str(cortex_id=cortex_id)
    if not isinstance(analyzer_job, dict):
        raise ValueError("analyzer_job must be a dict")
    _require_str(
        artifact_id=analyzer_job.get("artifact_id"),
        analyzer_id=analyzer_job.get("analyzer_id"),
    )

    job: InputAnalyzerJob = {
        "cortexId": cortex_id,
        "analyzerId": analyzer_job["analyzer_id"],
        "artifactId": analyzer_job["artifact_id"],
    }
    created = _client.cortex.create_analyzer_job(job)
    log.debug("Created analyzer job %s for artifact %s on cortex %s", analyzer_job["analyzer_id"], analyzer_job["artifact_id"], cortex_id)
    return created


@_wrap_api_errors
def bulk_create_analyzer_jobs(cortex_id: str, analyzer_jobs: list[AnalyzerJob]) -> list[OutputAnalyzerJob]:
    """Create multiple analyzer jobs.
        Args:
            cortex_id: ID of the cortex server to run the job on.
            analyzer_jobs: List of analyzerJob dicts containing information about the job to create.

        Returns:
            The created analyzer job.
    """
    _require_str(cortex_id=cortex_id)
    if not isinstance(analyzer_jobs, list) or not analyzer_jobs:
        raise ValueError("analyzer_jobs must be a non-empty list")
    for analyzer_job in analyzer_jobs:
        if not isinstance(analyzer_job, dict):
            raise ValueError("analyzer_jobs must only contain dicts")
        _require_str(
            artifact_id=analyzer_job.get("artifact_id"),
            analyzer_id=analyzer_job.get("analyzer_id"),
        )

    jobs: list[InputAnalyzerJob] = [
        {
            "cortexId": cortex_id,
            "analyzerId": analyzer_job["analyzer_id"],
            "artifactId": analyzer_job["artifact_id"],
        }
        for analyzer_job in analyzer_jobs
    ]
    created = _client.cortex.bulk_create_analyzer_jobs(jobs)
    log.debug("Created %d analyzer job(s) on cortex %s", len(jobs), cortex_id)
    return created


@_wrap_api_errors
def list_analyzers_by_type(data_type: str) -> list[OutputAnalyzer]:
    """List all analyzers compatible with a given data type.
        Args:
            data_type: The data type to list analyzers for.

        Returns:
            List containing all the applicable analyzers.
    """
    _require_str(data_type=data_type)

    return _client.cortex.list_analyzers_by_type(data_type)


@_wrap_api_errors
def get_analyzer_job(job_id: str) -> OutputAnalyzerJob:
    """Get an analyzer job by id.
        Args:
            job_id: The id of the analyzer job to get.

        Returns:
            The analyzer job specified by the id.
        """
    _require_str(job_id=job_id)

    return _client.cortex.get_analyzer_job(job_id)
