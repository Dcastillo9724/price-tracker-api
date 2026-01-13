"""
Views para la API de scrapers.

Este módulo contiene los ViewSets para consultar ejecuciones de scraping
y errores. También expone endpoints para disparar scraping vía Celery.

ViewSets:
    - ScraperRunViewSet: Consulta de ejecuciones de scraping + disparo de tasks
    - ScraperErrorViewSet: Consulta de errores de scraping
"""

from typing import Any, Optional

from django.db.models import Count, Exists, OuterRef, Q, QuerySet, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from products.models import Category, Store
from .models import ScraperError, ScraperRun
from .serializers import (
    ScraperErrorSerializer,
    ScraperRunDetailSerializer,
    ScraperRunSerializer,
)
from .tasks import run_products_task, run_categories_task



class ScraperRunViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ScraperRun.objects.select_related("store").all()
    serializer_class = ScraperRunSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["store", "status", "trigger_type"]
    ordering = ["-started_at"]

    def get_queryset(self) -> QuerySet[ScraperRun]:
        queryset = super().get_queryset()
        if self.action == "retrieve":
            queryset = queryset.prefetch_related("errors")
        return queryset

    def get_serializer_class(self):
        if self.action == "retrieve":
            return ScraperRunDetailSerializer
        return ScraperRunSerializer

    @action(detail=False, methods=["get"])
    def recent(self, request: Request) -> Response:
        limit = min(int(request.query_params.get("limit", 20)), 100)
        recent = self.get_queryset()[:limit]
        serializer = self.get_serializer(recent, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def stats(self, request: Request) -> Response:
        stats = ScraperRun.objects.aggregate(
            total_runs=Count("id"),
            successful=Count("id", filter=Q(status="COMPLETED")),
            failed=Count("id", filter=Q(status="FAILED")),
            total_scraped=Sum("products_scraped"),
            total_errors=Sum("errors_count"),
        )
        return Response(stats)

    @action(detail=True, methods=["get"])
    def errors(self, request: Request, pk: int = None) -> Response:
        scraper_run = self.get_object()
        errors = scraper_run.errors.all()
        serializer = ScraperErrorSerializer(errors, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["post"], url_path="trigger-categories")
    def trigger_categories(self, request: Request) -> Response:
        store_code = (request.data.get("store_code") or "").strip().upper()
        headless = bool(request.data.get("headless", True))
        trigger_type = (request.data.get("trigger_type") or "API").strip()

        if not store_code:
            return Response(
                {"detail": "store_code es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        store: Optional[Store] = Store.objects.filter(code=store_code).first()
        if not store:
            return Response(
                {"detail": f"Tienda no encontrada: {store_code}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        task = run_categories_task.delay(
            store_code=store_code,
            headless=headless,
            trigger_type=trigger_type,
        )

        return Response(
            {
                "task_id": task.id,
                "store_code": store_code,
                "type": "categories",
                "queued_at": timezone.now(),
            },
            status=status.HTTP_202_ACCEPTED,
        )

    @action(detail=False, methods=["post"], url_path="trigger-products")
    def trigger_products(self, request: Request) -> Response:
        store_code = (request.data.get("store_code") or "").strip().upper()
        headless = bool(request.data.get("headless", True))
        trigger_type = (request.data.get("trigger_type") or "API").strip()

        category_ids = request.data.get("category_ids", None)
        limit_categories = request.data.get("limit_categories", None)

        if not store_code:
            return Response(
                {"detail": "store_code es requerido"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        store: Optional[Store] = Store.objects.filter(code=store_code).first()
        if not store:
            return Response(
                {"detail": f"Tienda no encontrada: {store_code}"},
                status=status.HTTP_404_NOT_FOUND,
            )

        if category_ids is not None and not isinstance(category_ids, list):
            return Response(
                {"detail": "category_ids debe ser una lista de IDs o null"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if limit_categories is not None:
            try:
                limit_categories = int(limit_categories)
                if limit_categories <= 0:
                    limit_categories = None
            except Exception:
                return Response(
                    {"detail": "limit_categories debe ser un entero o null"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        task = run_products_task.delay(
            store_code=store_code,
            headless=headless,
            trigger_type=trigger_type,
            limit_categories=limit_categories,
        )


        return Response(
            {
                "task_id": task.id,
                "store_code": store_code,
                "type": "products",
                "queued_at": timezone.now(),
                "category_ids": category_ids,
                "limit_categories": limit_categories,
            },
            status=status.HTTP_202_ACCEPTED,
        )


class ScraperErrorViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ScraperError.objects.select_related(
        "scraper_run__store",
        "listing__product",
    ).all()
    serializer_class = ScraperErrorSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["error_type", "is_resolved", "scraper_run"]
    ordering = ["-occurred_at"]

    @action(detail=False, methods=["get"])
    def unresolved(self, request: Request) -> Response:
        limit = int(request.query_params.get("limit", 50))
        unresolved = self.get_queryset().filter(is_resolved=False)[:limit]
        serializer = self.get_serializer(unresolved, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def recent(self, request: Request) -> Response:
        from datetime import timedelta

        limit = min(int(request.query_params.get("limit", 20)), 100)
        hours = int(request.query_params.get("hours", 24))

        since = timezone.now() - timedelta(hours=hours)
        recent = self.get_queryset().filter(occurred_at__gte=since)[:limit]

        serializer = self.get_serializer(recent, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def by_type(self, request: Request) -> Response:
        stats = {}
        for error_type, _ in ScraperError.ErrorType.choices:
            count = self.get_queryset().filter(error_type=error_type).count()
            if count > 0:
                stats[error_type] = count
        return Response(stats)