from celery import shared_task
from django.utils import timezone

from .audit import record_audit
from .models import IngestionRun, User
from .services.uploads import process_upload, recover_uploads


@shared_task(acks_late=True, reject_on_worker_lost=True)
def scan_and_process_file(asset_id: str):
    process_upload(asset_id)


@shared_task
def recover_pending_uploads():
    recover_uploads()


@shared_task
def run_ingestion(ingestion_run_id: str):
    run = IngestionRun.objects.get(pk=ingestion_run_id)
    run.status = "running"
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at", "updated_at"])
    # Discovery adapters are deliberately source-specific and never publish here.
    run.status = "awaiting_source_adapters"
    run.report = {
        "automatic_publication": False,
        "message": "A execução foi registrada; somente adaptadores oficiais aprovados podem descobrir documentos.",
    }
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "report", "finished_at", "updated_at"])
    record_audit(
        "corpus.ingestion.finished",
        actor=User.objects.only("id").get(pk=run.requested_by_id)
        if run.requested_by_id
        else None,
        target=run,
        metadata={"run_type": run.run_type},
    )
