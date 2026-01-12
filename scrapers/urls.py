"""
Configuración de URLs para la API de scrapers.

Este módulo define las rutas de la API REST para consultar ejecuciones
de scraping y errores. Todas las operaciones son de solo lectura.

Estructura de URLs:
    /runs/ - Ejecuciones de scraping
    /errors/ - Errores de scraping

Endpoints disponibles por ViewSet:
    ScraperRunViewSet (solo lectura):
        - GET /runs/ - Listar ejecuciones
        - GET /runs/{id}/ - Detalle de ejecución
        - GET /runs/recent/ - Ejecuciones recientes
        - GET /runs/stats/ - Estadísticas globales
        - GET /runs/{id}/errors/ - Errores de una ejecución
    
    ScraperErrorViewSet (solo lectura):
        - GET /errors/ - Listar errores
        - GET /errors/{id}/ - Detalle de error
        - GET /errors/unresolved/ - Errores sin resolver
        - GET /errors/recent/ - Errores recientes
        - GET /errors/by_type/ - Errores agrupados por tipo

Examples:
    Para incluir estas URLs en el proyecto principal:
    
    # En tu urls.py principal:
    from django.urls import path, include
    
    urlpatterns = [
        path('api/v1/scrapers/', include('scrapers.urls')),
    ]
    
    Esto hará que las URLs estén disponibles como:
    - http://localhost:8000/api/v1/scrapers/runs/
    - http://localhost:8000/api/v1/scrapers/errors/
    - etc.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import ScraperErrorViewSet, ScraperRunViewSet

app_name = 'scrapers'

router = DefaultRouter()
router.register(r'runs', ScraperRunViewSet, basename='scraperrun')
router.register(r'errors', ScraperErrorViewSet, basename='scrapererror')

urlpatterns = [
    path('', include(router.urls)),
]