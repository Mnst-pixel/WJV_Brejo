"""Student-only projections of second-phase packages and owned submissions."""
from django.shortcuts import get_object_or_404
from rest_framework import serializers
from rest_framework.exceptions import MethodNotAllowed
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from core.permissions import CanStudy
from core.second_phase_models import WrittenSubmission
from core.services.written_submissions import public_case, public_submission, published_cases, save_written, start_written, submit_written


class CaseCatalogView(APIView):
    permission_classes = [CanStudy]

    def get(self, request):
        query = published_cases().order_by("educational_metadata__title", "pk")
        if request.query_params.get("area"):
            area_id = serializers.UUIDField().run_validation(request.query_params["area"])
            query = query.filter(educational_metadata__area_id=area_id)
        pagination = PageNumberPagination()
        page = pagination.paginate_queryset(query, request)
        return pagination.get_paginated_response([public_case(row) for row in page])


class WrittenSubmissionView(APIView):
    permission_classes = [CanStudy]

    def get(self, request, submission_id=None):
        query = WrittenSubmission.objects.filter(owner=request.user).prefetch_related("responses").order_by("-started_at", "pk")
        if submission_id:
            return Response(public_submission(get_object_or_404(query, pk=submission_id)))
        pagination = PageNumberPagination()
        page = pagination.paginate_queryset(query, request)
        return pagination.get_paginated_response([public_submission(row) for row in page])

    def post(self, request, submission_id=None):
        if submission_id:
            raise MethodNotAllowed("POST")
        return Response(public_submission(start_written(owner=request.user, data=request.data)), status=201)


class WrittenSaveView(APIView):
    permission_classes = [CanStudy]

    def post(self, request, submission_id):
        return Response(public_submission(save_written(owner=request.user, submission_id=submission_id, data=request.data)))


class WrittenSubmitView(APIView):
    permission_classes = [CanStudy]

    def post(self, request, submission_id):
        return Response(public_submission(submit_written(owner=request.user, submission_id=submission_id)))
