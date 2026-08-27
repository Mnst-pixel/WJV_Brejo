import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "kairos.settings")

app = Celery("kairos")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
