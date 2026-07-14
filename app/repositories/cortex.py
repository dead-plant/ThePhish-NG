import logging
import cortex4py
from cortex4py.models import Responder, Analyzer, Job

from app import config

log = logging.getLogger(__name__)


# responders
def get_responder_by_name(name: str) -> Responder:
    ...

# analyzers
def get_analyzers_by_type(data_type: str) -> list[Analyzer]:
    ...

# jobs
def get_job_by_id(job_id: str) -> Job:
    ...

def get_job_report(job_id: str) -> Job:
    ...
