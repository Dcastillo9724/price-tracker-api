"""
Views para la API de scrapers.

Este módulo contiene los ViewSets para consultar ejecuciones de scraping
y errores. Solo permite lectura ya que las ejecuciones se crean desde
comandos de management o tareas de Celery.

ViewSets:
    - ScraperRunViewSet: Consulta de ejecuciones de scraping
    - ScraperErrorViewSet: Consulta de errores de scraping
"""

from typing import Any

from django.db.models import Count, Q, QuerySet, Sum
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from .models import ScraperError, ScraperRun
from .serializers import (
    ScraperErrorSerializer,
    ScraperRunDetailSerializer,
    ScraperRunSerializer,
)


class ScraperRunViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo lectura para ejecuciones de scraping.
    
    Las ejecuciones se crean automáticamente desde comandos de management
    o tareas de Celery, no se pueden crear manualmente desde la API.
    
    Endpoints:
        - GET /runs/ - Lista todas las ejecuciones
        - GET /runs/{id}/ - Detalle de una ejecución
        - GET /runs/recent/ - Últimas ejecuciones
        - GET /runs/stats/ - Estadísticas globales
    
    Filters:
        - store: ID de tienda
        - status: Estado de la ejecución
        - trigger_type: Tipo de trigger
    
    Ordering:
        - started_at: Ordenar por fecha de inicio (default: descendente)
    
    Examples:
        GET /api/scrapers/runs/?store=1&status=COMPLETED
        GET /api/scrapers/runs/recent/?limit=10
        GET /api/scrapers/runs/stats/
    """
    
    queryset = ScraperRun.objects.select_related('store').all()
    serializer_class = ScraperRunSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['store', 'status', 'trigger_type']
    ordering = ['-started_at']
    
    def get_queryset(self) -> QuerySet[ScraperRun]:
        """
        Retorna el queryset con optimizaciones.
        
        Returns:
            QuerySet de ScraperRun con prefetch de relaciones
        """
        queryset = super().get_queryset()
        
        if self.action == 'retrieve':
            queryset = queryset.prefetch_related('errors')
        
        return queryset
    
    def get_serializer_class(self):
        """
        Retorna el serializer apropiado según la acción.
        
        Returns:
            Clase de serializer correspondiente
        """
        if self.action == 'retrieve':
            return ScraperRunDetailSerializer
        return ScraperRunSerializer
    
    @action(detail=False, methods=['get'])
    def recent(self, request: Request) -> Response:
        """
        Retorna las ejecuciones más recientes.
        
        Args:
            request: Request de DRF
        
        Query Params:
            limit: Número de resultados (default: 20, max: 100)
        
        Returns:
            Response con lista de ejecuciones recientes
        
        Examples:
            GET /api/scrapers/runs/recent/
            GET /api/scrapers/runs/recent/?limit=50
        """
        limit = min(int(request.query_params.get('limit', 20)), 100)
        recent = self.get_queryset()[:limit]
        serializer = self.get_serializer(recent, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request: Request) -> Response:
        """
        Retorna estadísticas globales de scraping.
        
        Calcula métricas agregadas sobre todas las ejecuciones:
        - Total de ejecuciones
        - Ejecuciones exitosas y fallidas
        - Total de productos scrapeados
        - Total de errores
        
        Args:
            request: Request de DRF
        
        Returns:
            Response con estadísticas agregadas
        
        Examples:
            GET /api/scrapers/runs/stats/
            
            Response:
            {
                "total_runs": 150,
                "successful": 140,
                "failed": 10,
                "total_scraped": 15000,
                "total_errors": 50
            }
        """
        stats = ScraperRun.objects.aggregate(
            total_runs=Count('id'),
            successful=Count('id', filter=Q(status='COMPLETED')),
            failed=Count('id', filter=Q(status='FAILED')),
            total_scraped=Sum('products_scraped'),
            total_errors=Sum('errors_count')
        )
        return Response(stats)
    
    @action(detail=True, methods=['get'])
    def errors(self, request: Request, pk: int = None) -> Response:
        """
        Retorna los errores de una ejecución específica.
        
        Args:
            request: Request de DRF
            pk: ID de la ejecución
        
        Returns:
            Response con lista de errores
        
        Examples:
            GET /api/scrapers/runs/123/errors/
        """
        scraper_run = self.get_object()
        errors = scraper_run.errors.all()
        serializer = ScraperErrorSerializer(errors, many=True)
        return Response(serializer.data)


class ScraperErrorViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo lectura para errores de scraping.
    
    Permite consultar errores ocurridos durante las ejecuciones
    de scraping para análisis y debugging.
    
    Endpoints:
        - GET /errors/ - Lista todos los errores
        - GET /errors/{id}/ - Detalle de un error
        - GET /errors/unresolved/ - Errores sin resolver
        - GET /errors/recent/ - Errores recientes
    
    Filters:
        - error_type: Tipo de error
        - is_resolved: Si está resuelto o no
        - scraper_run: ID de la ejecución
    
    Ordering:
        - occurred_at: Ordenar por fecha (default: descendente)
    
    Examples:
        GET /api/scrapers/errors/?error_type=CONNECTION
        GET /api/scrapers/errors/unresolved/
    """
    
    queryset = ScraperError.objects.select_related(
        'scraper_run__store',
        'listing__product'
    ).all()
    serializer_class = ScraperErrorSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['error_type', 'is_resolved', 'scraper_run']
    ordering = ['-occurred_at']
    
    @action(detail=False, methods=['get'])
    def unresolved(self, request: Request) -> Response:
        """
        Retorna errores que no han sido resueltos.
        
        Útil para identificar problemas pendientes que requieren atención.
        
        Args:
            request: Request de DRF
        
        Query Params:
            limit: Número de resultados (default: 50)
        
        Returns:
            Response con lista de errores sin resolver
        
        Examples:
            GET /api/scrapers/errors/unresolved/
            GET /api/scrapers/errors/unresolved/?limit=100
        """
        limit = int(request.query_params.get('limit', 50))
        unresolved = self.get_queryset().filter(is_resolved=False)[:limit]
        serializer = self.get_serializer(unresolved, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def recent(self, request: Request) -> Response:
        """
        Retorna los errores más recientes.
        
        Args:
            request: Request de DRF
        
        Query Params:
            limit: Número de resultados (default: 20, max: 100)
            hours: Horas hacia atrás (default: 24)
        
        Returns:
            Response con errores recientes
        
        Examples:
            GET /api/scrapers/errors/recent/
            GET /api/scrapers/errors/recent/?hours=12&limit=50
        """
        from datetime import timedelta
        from django.utils import timezone
        
        limit = min(int(request.query_params.get('limit', 20)), 100)
        hours = int(request.query_params.get('hours', 24))
        
        since = timezone.now() - timedelta(hours=hours)
        recent = self.get_queryset().filter(occurred_at__gte=since)[:limit]
        
        serializer = self.get_serializer(recent, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def by_type(self, request: Request) -> Response:
        """
        Retorna estadísticas de errores agrupados por tipo.
        
        Args:
            request: Request de DRF
        
        Returns:
            Response con conteo de errores por tipo
        
        Examples:
            GET /api/scrapers/errors/by_type/
            
            Response:
            {
                "CONNECTION": 25,
                "TIMEOUT": 15,
                "PARSE": 10,
                ...
            }
        """
        stats = {}
        for error_type, _ in ScraperError.ErrorType.choices:
            count = self.get_queryset().filter(error_type=error_type).count()
            if count > 0:
                stats[error_type] = count
        
        return Response(stats)