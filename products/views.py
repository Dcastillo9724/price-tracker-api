"""
Views para la API de productos y tracking de precios.

Este módulo contiene los ViewSets de DRF para manejar las operaciones
CRUD y acciones personalizadas sobre productos, tiendas, categorías,
listings y precios.

ViewSets:
    - StoreViewSet: Gestión de tiendas
    - CategoryViewSet: Gestión de categorías jerárquicas
    - ProductViewSet: Gestión de productos con búsqueda y filtros
    - ProductListingViewSet: Gestión de listings de productos
    - PriceViewSet: Consulta de historial de precios (read-only)
"""

from datetime import timedelta

from django.db.models import Avg, Count, F, Max, Min, OuterRef, Q, QuerySet, Subquery
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response

from .models import Category, Price, Product, ProductListing, Store
from .serializers import (
    CategorySerializer,
    CategoryTreeSerializer,
    ListingCreateSerializer,
    ListingDetailSerializer,
    ListingListSerializer,
    PriceSerializer,
    ProductCreateSerializer,
    ProductDetailSerializer,
    ProductListSerializer,
    StoreSerializer,
)


class StoreViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de tiendas.
    
    Proporciona operaciones CRUD completas para el modelo Store,
    con filtrado por estado y búsqueda por nombre.
    
    Endpoints:
        - GET /stores/ - Lista todas las tiendas
        - POST /stores/ - Crea una nueva tienda
        - GET /stores/{id}/ - Detalle de una tienda
        - PUT /stores/{id}/ - Actualiza una tienda
        - PATCH /stores/{id}/ - Actualización parcial
        - DELETE /stores/{id}/ - Elimina una tienda
        - GET /stores/{id}/listings/ - Listings de la tienda
    
    Filters:
        - is_active: Filtrar por estado activo/inactivo
        - scraping_enabled: Filtrar por scraping habilitado
        - code: Filtrar por código de tienda
    
    Search:
        - name: Buscar por nombre de tienda
    
    Examples:
        GET /api/stores/?is_active=true
        GET /api/stores/?search=mercado
        GET /api/stores/1/listings/
    """
    
    queryset = Store.objects.all()
    serializer_class = StoreSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['is_active', 'scraping_enabled', 'code']
    search_fields = ['name']
    
    def get_queryset(self) -> QuerySet[Store]:
        """
        Retorna el queryset con prefetch optimizado.
        
        Returns:
            QuerySet de Store con optimizaciones
        """
        queryset = super().get_queryset()
        
        if self.action == 'list':
            queryset = queryset.prefetch_related('listings')
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def listings(self, request: Request, pk: int = None) -> Response:
        """
        Retorna los listings activos de una tienda.
        
        Args:
            request: Request de DRF
            pk: ID de la tienda
        
        Returns:
            Response con lista de listings activos
        
        Examples:
            GET /api/stores/1/listings/
            GET /api/stores/1/listings/?limit=10
        """
        store = self.get_object()
        listings = store.listings.filter(is_active=True).select_related(
            'product', 'product__category'
        ).prefetch_related('price_history')
        
        # Paginación opcional
        limit = request.query_params.get('limit')
        if limit:
            try:
                listings = listings[:int(limit)]
            except (ValueError, TypeError):
                pass
        
        serializer = ListingListSerializer(listings, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def toggle_scraping(self, request: Request, pk: int = None) -> Response:
        """
        Activa/desactiva el scraping para una tienda.
        
        Args:
            request: Request de DRF
            pk: ID de la tienda
        
        Returns:
            Response con estado actualizado de la tienda
        
        Examples:
            POST /api/stores/1/toggle_scraping/
        """
        store = self.get_object()
        store.scraping_enabled = not store.scraping_enabled
        store.save(update_fields=['scraping_enabled'])
        
        serializer = self.get_serializer(store)
        return Response(serializer.data)


class CategoryViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de categorías.
    
    Maneja categorías jerárquicas con soporte para árbol de categorías
    y listado de productos por categoría.
    
    Endpoints:
        - GET /categories/ - Lista todas las categorías activas
        - POST /categories/ - Crea una nueva categoría
        - GET /categories/{id}/ - Detalle de una categoría
        - PUT /categories/{id}/ - Actualiza una categoría
        - PATCH /categories/{id}/ - Actualización parcial
        - DELETE /categories/{id}/ - Elimina una categoría
        - GET /categories/{id}/products/ - Productos de la categoría
        - GET /categories/tree/ - Árbol completo de categorías
    
    Filters:
        - parent: Filtrar por categoría padre
    
    Search:
        - name: Buscar por nombre de categoría
    
    Examples:
        GET /api/categories/?parent__isnull=true  # Categorías raíz
        GET /api/categories/1/products/
        GET /api/categories/tree/
    """
    
    queryset = Category.objects.filter(is_active=True)
    serializer_class = CategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ['parent']
    search_fields = ['name']
    
    def get_queryset(self) -> QuerySet[Category]:
        """
        Retorna el queryset con optimizaciones.
        
        Returns:
            QuerySet de Category con prefetch de relaciones
        """
        queryset = super().get_queryset()
        
        if self.action == 'list':
            queryset = queryset.select_related('parent').prefetch_related('products')
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def products(self, request: Request, pk: int = None) -> Response:
        """
        Retorna los productos de una categoría.
        
        Incluye productos de subcategorías si se especifica el parámetro
        include_children=true.
        
        Args:
            request: Request de DRF
            pk: ID de la categoría
        
        Query Params:
            include_children: Incluir productos de subcategorías
        
        Returns:
            Response con lista de productos
        
        Examples:
            GET /api/categories/1/products/
            GET /api/categories/1/products/?include_children=true
        """
        category = self.get_object()
        
        # Opción para incluir subcategorías
        include_children = request.query_params.get('include_children', 'false').lower() == 'true'
        
        if include_children:
            # Obtener todas las subcategorías
            all_categories = [category] + category.get_all_children()
            products = Product.objects.filter(
                category__in=all_categories,
                is_active=True
            )
        else:
            products = category.products.filter(is_active=True)
        
        products = products.select_related('category').prefetch_related('listings')
        
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def tree(self, request: Request) -> Response:
        """
        Retorna el árbol completo de categorías.
        
        Solo incluye categorías raíz con sus hijos anidados.
        
        Args:
            request: Request de DRF
        
        Returns:
            Response con árbol de categorías
        
        Examples:
            GET /api/categories/tree/
        """
        root_categories = self.get_queryset().filter(parent__isnull=True)
        serializer = CategoryTreeSerializer(root_categories, many=True)
        return Response(serializer.data)


class ProductViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de productos.
    
    Proporciona operaciones CRUD con búsqueda avanzada,
    filtros por categoría/marca/precio y acciones especiales.
    
    Endpoints:
        - GET /products/ - Lista productos con filtros
        - POST /products/ - Crea un producto
        - GET /products/{id}/ - Detalle de producto
        - PUT /products/{id}/ - Actualiza producto
        - PATCH /products/{id}/ - Actualización parcial
        - DELETE /products/{id}/ - Elimina producto
        - GET /products/best_deals/ - Mejores descuentos
        - GET /products/price_alerts/ - Productos con alertas de precio
    
    Filters:
        - category: ID de categoría
        - is_active: Activo/inactivo
        - brand: Marca del producto
        - min_price: Precio mínimo
        - max_price: Precio máximo
    
    Search:
        - name, brand, model: Búsqueda por nombre, marca o modelo
    
    Ordering:
        - name: Ordenar por nombre
        - created_at: Ordenar por fecha de creación
    
    Examples:
        GET /api/products/?category=1&brand=HP
        GET /api/products/?min_price=1000000&max_price=3000000
        GET /api/products/?search=laptop&ordering=-created_at
        GET /api/products/best_deals/?limit=20
    """
    
    queryset = Product.objects.select_related('category').all()
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_active', 'brand']
    search_fields = ['name', 'brand', 'model']
    ordering_fields = ['name', 'created_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """
        Retorna el serializer apropiado según la acción.
        
        Returns:
            Clase de serializer correspondiente
        """
        if self.action == 'list':
            return ProductListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ProductCreateSerializer
        return ProductDetailSerializer
    
    def get_queryset(self) -> QuerySet[Product]:
        """
        Retorna el queryset con filtros adicionales y optimizaciones.
        
        Aplica filtros de precio si se proporcionan en query params.
        
        Returns:
            QuerySet filtrado y optimizado
        """
        queryset = super().get_queryset()
        
        # Optimizaciones según acción
        if self.action == 'list':
            queryset = queryset.prefetch_related('listings', 'listings__price_history')
        elif self.action == 'retrieve':
            queryset = queryset.prefetch_related(
                'listings__store',
                'listings__price_history'
            )
        
        # Filtro por rango de precio
        min_price = self.request.query_params.get('min_price')
        max_price = self.request.query_params.get('max_price')
        
        if min_price or max_price:
            latest_prices = Price.objects.filter(
                listing=OuterRef('listings'),
                is_available=True
            ).order_by('-recorded_at')
            
            queryset = queryset.annotate(
                latest_price=Subquery(latest_prices.values('price')[:1])
            )
            
            if min_price:
                queryset = queryset.filter(latest_price__gte=min_price)
            if max_price:
                queryset = queryset.filter(latest_price__lte=max_price)
            
            queryset = queryset.distinct()
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def best_deals(self, request: Request) -> Response:
        """
        Retorna los productos con mejores descuentos.
        
        Ordena por diferencia entre precio original y precio actual,
        mostrando los mayores descuentos primero.
        
        Args:
            request: Request de DRF
        
        Query Params:
            limit: Número de resultados (default: 20, max: 100)
            min_discount: Porcentaje mínimo de descuento
        
        Returns:
            Response con lista de listings con descuento
        
        Examples:
            GET /api/products/best_deals/
            GET /api/products/best_deals/?limit=50&min_discount=20
        """
        limit = min(int(request.query_params.get('limit', 20)), 100)
        min_discount = request.query_params.get('min_discount')
        
        # Subquery para obtener el último precio con descuento
        latest_price_subquery = Price.objects.filter(
            listing=OuterRef('pk'),
            original_price__isnull=False,
            original_price__gt=F('price'),
            is_available=True
        ).order_by('-recorded_at')
        
        listings = ProductListing.objects.filter(
            is_active=True,
            is_available=True,
        ).annotate(
            latest_price=Subquery(latest_price_subquery.values('price')[:1]),
            latest_original=Subquery(latest_price_subquery.values('original_price')[:1])
        ).filter(
            latest_price__isnull=False,
            latest_original__isnull=False
        ).select_related('product', 'store')
        
        # Filtrar por porcentaje mínimo si se especifica
        if min_discount:
            try:
                min_discount_decimal = float(min_discount) / 100
                listings = listings.filter(
                    latest_price__lte=F('latest_original') * (1 - min_discount_decimal)
                )
            except (ValueError, TypeError):
                pass
        
        # Ordenar por monto de descuento
        listings = listings.order_by(
            F('latest_original') - F('latest_price')
        ).reverse()[:limit]
        
        serializer = ListingListSerializer(listings, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def trending(self, request: Request) -> Response:
        """
        Retorna productos con más cambios de precio recientes.
        
        Útil para identificar productos con precios volátiles o
        promociones activas.
        
        Args:
            request: Request de DRF
        
        Query Params:
            days: Días a considerar (default: 7)
            limit: Número de resultados (default: 20)
        
        Returns:
            Response con productos ordenados por actividad de precio
        
        Examples:
            GET /api/products/trending/
            GET /api/products/trending/?days=14&limit=30
        """
        days = int(request.query_params.get('days', 7))
        limit = int(request.query_params.get('limit', 20))
        
        since_date = timezone.now() - timedelta(days=days)
        
        products_with_changes = Product.objects.filter(
            listings__price_history__recorded_at__gte=since_date
        ).annotate(
            price_changes=Count('listings__price_history')
        ).filter(
            price_changes__gt=1,
            is_active=True
        ).order_by('-price_changes').select_related('category')[:limit]
        
        serializer = ProductListSerializer(products_with_changes, many=True)
        return Response(serializer.data)


class ProductListingViewSet(viewsets.ModelViewSet):
    """
    ViewSet para gestión de listings de productos.
    
    Maneja los listings de productos en tiendas específicas,
    con historial de precios y actualización de scraping.
    
    Endpoints:
        - GET /listings/ - Lista todos los listings
        - POST /listings/ - Crea un listing
        - GET /listings/{id}/ - Detalle de listing
        - PUT /listings/{id}/ - Actualiza listing
        - PATCH /listings/{id}/ - Actualización parcial
        - DELETE /listings/{id}/ - Elimina listing
        - GET /listings/{id}/price_history/ - Historial de precios
        - POST /listings/{id}/update_availability/ - Actualiza disponibilidad
    
    Filters:
        - store: ID de tienda
        - product: ID de producto
        - is_available: Disponible/no disponible
        - is_active: Activo/inactivo
    
    Ordering:
        - current_price: Ordenar por precio actual
        - last_scraped_at: Ordenar por última actualización
    
    Examples:
        GET /api/listings/?store=1&is_available=true
        GET /api/listings/1/price_history/?days=30
        POST /api/listings/1/update_availability/
    """
    
    queryset = ProductListing.objects.select_related('product', 'store').all()
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['store', 'product', 'is_available', 'is_active']
    ordering_fields = ['last_scraped_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Retorna el serializer apropiado según la acción."""
        if self.action == 'list':
            return ListingListSerializer
        elif self.action in ['create', 'update', 'partial_update']:
            return ListingCreateSerializer
        return ListingDetailSerializer
    
    def get_queryset(self) -> QuerySet[ProductListing]:
        """Retorna el queryset con optimizaciones."""
        queryset = super().get_queryset()
        
        if self.action in ['list', 'retrieve']:
            queryset = queryset.prefetch_related('price_history')
        
        return queryset
    
    @action(detail=True, methods=['get'])
    def price_history(self, request: Request, pk: int = None) -> Response:
        """
        Retorna el historial de precios del listing.
        
        Args:
            request: Request de DRF
            pk: ID del listing
        
        Query Params:
            days: Días a consultar (default: 30)
            limit: Máximo de registros (default: 100)
        
        Returns:
            Response con historial de precios
        
        Examples:
            GET /api/listings/1/price_history/
            GET /api/listings/1/price_history/?days=60&limit=200
        """
        listing = self.get_object()
        days = int(request.query_params.get('days', 30))
        limit = int(request.query_params.get('limit', 100))
        
        start_date = timezone.now() - timedelta(days=days)
        prices = listing.price_history.filter(
            recorded_at__gte=start_date
        )[:limit]
        
        serializer = PriceSerializer(prices, many=True)
        return Response(serializer.data)
    
    @action(detail=True, methods=['post'])
    def update_availability(self, request: Request, pk: int = None) -> Response:
        """
        Actualiza la disponibilidad del listing.
        
        Args:
            request: Request de DRF con datos de disponibilidad
            pk: ID del listing
        
        Body:
            is_available: bool
            stock_status: str (opcional)
        
        Returns:
            Response con listing actualizado
        
        Examples:
            POST /api/listings/1/update_availability/
            {
                "is_available": false,
                "stock_status": "Agotado"
            }
        """
        listing = self.get_object()
        
        is_available = request.data.get('is_available')
        stock_status = request.data.get('stock_status', '')
        
        if is_available is not None:
            listing.is_available = is_available
            listing.stock_status = stock_status
            listing.update_scrape_timestamp()
            
            serializer = self.get_serializer(listing)
            return Response(serializer.data)
        
        return Response(
            {'error': 'Se requiere el campo is_available'},
            status=status.HTTP_400_BAD_REQUEST
        )


class PriceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    ViewSet de solo lectura para precios.
    
    Permite consultar el historial de precios registrados
    en el sistema. No permite crear/editar/eliminar precios
    directamente (se crean mediante procesos de scraping).
    
    Endpoints:
        - GET /prices/ - Lista precios recientes
        - GET /prices/{id}/ - Detalle de un precio
        - GET /prices/recent/ - Precios más recientes
        - GET /prices/statistics/ - Estadísticas de precios
    
    Filters:
        - listing: ID del listing
        - is_available: Disponible/no disponible
    
    Ordering:
        - recorded_at: Ordenar por fecha de registro (default: desc)
    
    Examples:
        GET /api/prices/?listing=1
        GET /api/prices/recent/?limit=100
        GET /api/prices/statistics/?days=30
    """
    
    queryset = Price.objects.select_related(
        'listing__product',
        'listing__store'
    ).all()
    serializer_class = PriceSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['listing', 'is_available']
    ordering = ['-recorded_at']
    
    @action(detail=False, methods=['get'])
    def recent(self, request: Request) -> Response:
        """
        Retorna los precios registrados más recientemente.
        
        Args:
            request: Request de DRF
        
        Query Params:
            limit: Número de resultados (default: 50, max: 200)
            hours: Horas a consultar (default: 24)
        
        Returns:
            Response con precios recientes
        
        Examples:
            GET /api/prices/recent/
            GET /api/prices/recent/?limit=100&hours=12
        """
        limit = min(int(request.query_params.get('limit', 50)), 200)
        hours = int(request.query_params.get('hours', 24))
        
        since = timezone.now() - timedelta(hours=hours)
        recent = self.get_queryset().filter(recorded_at__gte=since)[:limit]
        
        serializer = self.get_serializer(recent, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def statistics(self, request: Request) -> Response:
        """
        Retorna estadísticas globales de precios.
        
        Args:
            request: Request de DRF
        
        Query Params:
            days: Días a considerar (default: 30)
        
        Returns:
            Response con estadísticas de precios
        
        Examples:
            GET /api/prices/statistics/
            GET /api/prices/statistics/?days=7
        """
        days = int(request.query_params.get('days', 30))
        since = timezone.now() - timedelta(days=days)
        
        stats = self.get_queryset().filter(
            recorded_at__gte=since,
            is_available=True
        ).aggregate(
            total_records=Count('id'),
            avg_price=Avg('price'),
            min_price=Min('price'),
            max_price=Max('price'),
            unique_listings=Count('listing', distinct=True)
        )
        
        return Response(stats)