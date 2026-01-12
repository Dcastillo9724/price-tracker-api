"""
Configuración de URLs para la API de productos.

Este módulo define las rutas de la API REST usando Django REST Framework routers.
Todos los endpoints están bajo el prefijo definido en el archivo de URLs principal.

Estructura de URLs:
    /stores/ - CRUD de tiendas
    /categories/ - CRUD de categorías
    /products/ - CRUD de productos
    /listings/ - CRUD de listings
    /prices/ - Lectura de historial de precios

Endpoints disponibles por ViewSet:
    StoreViewSet:
        - GET /stores/ - Listar tiendas
        - POST /stores/ - Crear tienda
        - GET /stores/{id}/ - Detalle de tienda
        - PUT /stores/{id}/ - Actualizar tienda
        - PATCH /stores/{id}/ - Actualización parcial
        - DELETE /stores/{id}/ - Eliminar tienda
        - GET /stores/{id}/listings/ - Listings de la tienda
        - POST /stores/{id}/toggle_scraping/ - Toggle scraping
    
    CategoryViewSet:
        - GET /categories/ - Listar categorías
        - POST /categories/ - Crear categoría
        - GET /categories/{id}/ - Detalle de categoría
        - PUT /categories/{id}/ - Actualizar categoría
        - PATCH /categories/{id}/ - Actualización parcial
        - DELETE /categories/{id}/ - Eliminar categoría
        - GET /categories/{id}/products/ - Productos de categoría
        - GET /categories/tree/ - Árbol de categorías
    
    ProductViewSet:
        - GET /products/ - Listar productos
        - POST /products/ - Crear producto
        - GET /products/{id}/ - Detalle de producto
        - PUT /products/{id}/ - Actualizar producto
        - PATCH /products/{id}/ - Actualización parcial
        - DELETE /products/{id}/ - Eliminar producto
        - GET /products/best_deals/ - Mejores descuentos
        - GET /products/trending/ - Productos con precios volátiles
    
    ProductListingViewSet:
        - GET /listings/ - Listar listings
        - POST /listings/ - Crear listing
        - GET /listings/{id}/ - Detalle de listing
        - PUT /listings/{id}/ - Actualizar listing
        - PATCH /listings/{id}/ - Actualización parcial
        - DELETE /listings/{id}/ - Eliminar listing
        - GET /listings/{id}/price_history/ - Historial de precios
        - POST /listings/{id}/update_availability/ - Actualizar disponibilidad
    
    PriceViewSet (solo lectura):
        - GET /prices/ - Listar precios
        - GET /prices/{id}/ - Detalle de precio
        - GET /prices/recent/ - Precios recientes
        - GET /prices/statistics/ - Estadísticas de precios

Examples:
    Para incluir estas URLs en el proyecto principal:
    
    # En tu urls.py principal:
    from django.urls import path, include
    
    urlpatterns = [
        path('api/v1/', include('products.urls')),
    ]
    
    Esto hará que las URLs estén disponibles como:
    - http://localhost:8000/api/v1/products/
    - http://localhost:8000/api/v1/stores/
    - etc.
"""

from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .views import (
    CategoryViewSet,
    PriceViewSet,
    ProductListingViewSet,
    ProductViewSet,
    StoreViewSet,
)

app_name = 'products'

router = DefaultRouter()
router.register(r'stores', StoreViewSet, basename='store')
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'listings', ProductListingViewSet, basename='listing')
router.register(r'prices', PriceViewSet, basename='price')

urlpatterns = [
    path('', include(router.urls)),
]