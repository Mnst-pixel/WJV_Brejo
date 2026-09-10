from io import BytesIO

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import MethodNotAllowed, ParseError, ValidationError
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import CanStudy
from core.services.study_state import (
    import_browser,
    record_activity,
    save_panel,
    save_record,
    summary,
)
from core.study_models import (
    BrowserImportReceipt,
    StudyActivity,
    StudyMark,
    StudyPanelState,
    StudyProgress,
)


class StudyJSONParser(JSONParser):
    def parse(self, stream, media_type=None, parser_context=None):
        data = stream.read(300001)
        if len(data) > 300000:
            raise ParseError("Requisição de estudo excede o limite.")
        try:
            return super().parse(
                BytesIO(data), media_type=media_type, parser_context=parser_context
            )
        except RecursionError:
            raise ParseError("Dados excessivamente aninhados.") from None


def represent(obj):
    common = {
        "id": str(obj.pk),
        "created_at": obj.created_at,
        "updated_at": obj.updated_at,
    }
    fields = {
        StudyProgress: ("target_kind", "target_id", "percent", "position", "version"),
        StudyMark: (
            "target_kind",
            "target_id",
            "locator",
            "kind",
            "annotation",
            "version",
        ),
        StudyActivity: ("event_key", "kind", "occurred_at", "duration_seconds"),
        StudyPanelState: (
            "last_panel",
            "pomodoro_status",
            "remaining_seconds",
            "timer_updated_at",
            "study_session_id",
            "version",
        ),
        BrowserImportReceipt: (
            "source_key",
            "source_hash",
            "status",
            "result",
            "provenance",
        ),
    }[type(obj)]
    common.update({field: getattr(obj, field) for field in fields})
    if isinstance(obj, StudyPanelState):
        elapsed = (
            max(0, int((timezone.now() - obj.timer_updated_at).total_seconds()))
            if obj.timer_updated_at and obj.pomodoro_status == "running"
            else 0
        )
        common["effective_remaining_seconds"] = max(0, obj.remaining_seconds - elapsed)
    return common


def page(request, query):
    value = request.query_params.get("offset", "0")
    if not value.isascii() or not value.isdecimal() or len(value) > 8:
        raise ValidationError("Offset inválido.")
    offset = int(value)
    records = list(query.order_by("id")[offset : offset + 51])
    return {
        "results": [represent(item) for item in records[:50]],
        "next_offset": offset + 50 if len(records) > 50 else None,
    }


class StudyView(APIView):
    permission_classes = [CanStudy]
    parser_classes = [StudyJSONParser]

    def finalize_response(self, request, response, *args, **kwargs):
        response = super().finalize_response(request, response, *args, **kwargs)
        response["Cache-Control"] = "no-store"
        return response


class StudyRecordView(StudyView):
    kind = "progress"

    def get(self, request, record_id=None):
        model = {"progress": StudyProgress, "marks": StudyMark}[self.kind]
        query = model.objects.filter(owner=request.user)
        if record_id is not None:
            return Response(represent(get_object_or_404(query, pk=record_id)))
        return Response(page(request, query))

    def put(self, request, record_id=None):
        if record_id is not None:
            raise MethodNotAllowed("PUT")
        return Response(
            represent(save_record(user=request.user, kind=self.kind, data=request.data))
        )


class StudyActivityView(StudyView):
    def get(self, request):
        return Response(page(request, StudyActivity.objects.filter(owner=request.user)))

    def post(self, request):
        return Response(
            represent(record_activity(user=request.user, data=request.data)), status=201
        )


class StudyPanelView(StudyView):
    def get(self, request):
        current = StudyPanelState.objects.filter(owner=request.user).first()
        return Response(
            represent(current)
            if current
            else {
                "version": 0,
                "last_panel": "dashboard",
                "pomodoro_status": "idle",
                "remaining_seconds": 1500,
                "effective_remaining_seconds": 1500,
                "study_session_id": None,
            }
        )

    def put(self, request):
        return Response(represent(save_panel(user=request.user, data=request.data)))


class StudySummaryView(StudyView):
    def get(self, request):
        return Response(summary(request.user))


class BrowserImportView(StudyView):
    def get(self, request, receipt_id=None):
        query = BrowserImportReceipt.objects.filter(owner=request.user)
        if receipt_id is not None:
            receipt = get_object_or_404(query, pk=receipt_id)
            return Response({**represent(receipt), "source_data": receipt.source_data})
        return Response(page(request, query))

    def post(self, request, receipt_id=None):
        if receipt_id is not None:
            raise MethodNotAllowed("POST")
        return Response(
            import_browser(user=request.user, data=request.data, request=request)
        )
