"""
Views para la API de productos y tracking de precios.

Enfoque:
- QuerySets optimizados (select_related / prefetch / annotate cuando aplica).
- Validación defensiva de query params (sin “try/except pass” silencioso).
- Acciones custom usando paginación DRF (paginate_queryset) en vez de slices “a mano”.
- Evitar N+1: serializers dependen de relaciones precargadas en list/retrieve.

ViewSets:
    - StoreViewSet: Gestión de tiendas
    - CategoryViewSet: Gestión de categorías jerárquicas
    - ProductViewSet: Gestión de productos con búsqueda y filtros
    - ProductListingViewSet: Gestión de listings de productos
    - PriceViewSet: Consulta de historial de precios (read-only)
"""

from __future__ import annotations

from datetime import timedelta
from typing import Optional

from django.db.models import (
    Avg,
    Count,
    Exists,
    F,
    Max,
    Min,
    OuterRef,
    Q,
    QuerySet,
    Subquery,
)
from django.db.models.functions import Coalesce
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


def _parse_int(
    request: Request,
    name: str,
    default: int,
    *,
    minimum: Optional[int] = None,
    maximum: Optional[int] = None,
) -> int:
    raw = request.query_params.get(name, None)
    if raw is None or raw == "":
        value = default
    else:
        try:
            value = int(raw)
        except (ValueError, TypeError):
            raise ValueError(f"'{name}' debe ser un entero válido.")

    if minimum is not None and value < minimum:
        value = minimum
    if maximum is not None and value > maximum:
        value = maximum
    return value


def _parse_bool(request: Request, name: str, default: bool = False) -> bool:
    raw = request.query_params.get(name, None)
    if raw is None:
        return default
    return str(raw).strip().lower() in {"1", "true", "t", "yes", "y", "si", "sí"}


def _latest_price_subquery(*, only_available: bool = True) -> Subquery:
    """
    Subquery para obtener el último precio (price) de un ProductListing.

    Nota: Esto NO trae el objeto Price, sino el valor del campo solicitado.
    """
    qs = Price.objects.filter(listing=OuterRef("pk")).order_by("-recorded_at")
    if only_available:
        qs = qs.filter(is_available=True)
    return Subquery(qs.values("price")[:1])


def _latest_original_subquery(*, only_discounted: bool = False) -> Subquery:
    """
    Subquery para obtener el último original_price de un ProductListing.

    only_discounted:
        - True: solo considera registros con original_price > price.
    """
    qs = Price.objects.filter(listing=OuterRef("pk")).order_by("-recorded_at")
    if only_discounted:
        qs = qs.filter(original_price__isnull=False, original_price__gt=F("price"), is_available=True)
    return Subquery(qs.values("original_price")[:1])


class StoreViewSet(viewsets.ModelViewSet):
    """
    CRUD de Store + acciones útiles.

    Acciones:
    - GET /stores/{id}/listings/
    - POST /stores/{id}/toggle_scraping/
    """

    serializer_class = StoreSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["is_active", "scraping_enabled", "code"]
    search_fields = ["name"]

    def get_queryset(self) -> QuerySet[Store]:
        qs = Store.objects.all()

        # Soporta StoreSerializer.listings_count sin N+1
        qs = qs.annotate(
            listings_count=Count("listings", filter=Q(listings__is_active=True), distinct=True)
        )

        return qs

    @action(detail=True, methods=["get"])
    def listings(self, request: Request, pk: Optional[int] = None) -> Response:
        """
        Listings activos de una tienda.

        Query params:
        - limit (opcional): limite duro (si no usas paginación global)
        """
        store = self.get_object()

        listings_qs = (
            store.listings.filter(is_active=True)
            .select_related("product", "product__category", "store")
            .prefetch_related("price_history")
        )

        # Si tienes paginación configurada globalmente, esto funciona perfecto.
        page = self.paginate_queryset(listings_qs)
        if page is not None:
            serializer = ListingListSerializer(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)

        # Fallback si no hay paginación configurada
        try:
            limit = _parse_int(request, "limit", default=0, minimum=0, maximum=500)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if limit:
            listings_qs = listings_qs[:limit]

        serializer = ListingListSerializer(listings_qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def toggle_scraping(self, request: Request, pk: Optional[int] = None) -> Response:
        """Activa/desactiva scraping_enabled."""
        store = self.get_object()
        store.scraping_enabled = not store.scraping_enabled
        store.save(update_fields=["scraping_enabled"])
        return Response(self.get_serializer(store).data)


class CategoryViewSet(viewsets.ModelViewSet):
    """
    CRUD de Category + árbol y productos por categoría.
    """

    serializer_class = CategorySerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter]
    filterset_fields = ["parent", "store"]
    search_fields = ["name"]

    def get_queryset(self) -> QuerySet[Category]:
        qs = Category.objects.filter(is_active=True).select_related("store", "parent")

        # Soporta CategorySerializer.products_count sin N+1
        qs = qs.annotate(products_count=Count("products", distinct=True))

        return qs

    @action(detail=True, methods=["get"])
    def products(self, request: Request, pk: Optional[int] = None) -> Response:
        """
        Productos de una categoría.

        Query params:
        - include_children: incluir subcategorías (default false)
        """
        category = self.get_object()
        include_children = _parse_bool(request, "include_children", default=False)

        if include_children:
            all_categories = [category] + category.get_all_children()
            products_qs = Product.objects.filter(category__in=all_categories, is_active=True)
        else:
            products_qs = category.products.filter(is_active=True)

        products_qs = (
            products_qs.select_related("category")
            .annotate(listings_count=Count("listings", distinct=True))
            .order_by("-created_at")
        )

        page = self.paginate_queryset(products_qs)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context=self.get_serializer_context())
            return self.get_paginated_response(serializer.data)

        serializer = ProductListSerializer(products_qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def tree(self, request: Request) -> Response:
        """Árbol de categorías (solo raíces)."""
        root_qs = self.get_queryset().filter(parent__isnull=True).prefetch_related("children")
        serializer = CategoryTreeSerializer(root_qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class ProductViewSet(viewsets.ModelViewSet):
    """
    CRUD de Product + acciones:
    - GET /products/best_deals/
    - GET /products/trending/
    """

    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ["category", "is_active", "brand"]
    search_fields = ["name", "brand", "model"]
    ordering_fields = ["name", "created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return ProductListSerializer
        if self.action in {"create", "update", "partial_update"}:
            return ProductCreateSerializer
        return ProductDetailSerializer

    def get_queryset(self) -> QuerySet[Product]:
        qs = Product.objects.select_related("category").all()

        # Soporta ProductListSerializer.listings_count sin N+1
        qs = qs.annotate(listings_count=Count("listings", distinct=True))

        # Prefetch para detalle/list (evita N+1 en best_price / listings)
        if self.action == "list":
            qs = qs.prefetch_related(
                "listings__store",
                "listings__price_history",
            )
        elif self.action == "retrieve":
            qs = qs.prefetch_related(
                "listings__store",
                "listings__price_history",
            )

        # Filtro por rango de precio basado en “último precio por listing”
        min_price = self.request.query_params.get("min_price")
        max_price = self.request.query_params.get("max_price")
        if min_price or max_price:
            try:
                min_val = Decimal(min_price) if min_price else None
                max_val = Decimal(max_price) if max_price else None
            except Exception:
                return qs.none()

            listing_qs = (
                ProductListing.objects.filter(product=OuterRef("pk"), is_active=True, is_available=True)
                .annotate(latest_price=_latest_price_subquery(only_available=True))
                .filter(latest_price__isnull=False)
            )
            if min_val is not None:
                listing_qs = listing_qs.filter(latest_price__gte=min_val)
            if max_val is not None:
                listing_qs = listing_qs.filter(latest_price__lte=max_val)

            qs = qs.annotate(has_listing_in_range=Exists(listing_qs)).filter(has_listing_in_range=True)

        return qs

    @action(detail=False, methods=["get"])
    def best_deals(self, request: Request) -> Response:
        """
        Listings con mejores descuentos (basado en último Price con descuento).

        Query params:
        - limit (default 20, max 100)
        - min_discount (porcentaje entero o decimal, ej 20 o 20.5)
        """
        try:
            limit = _parse_int(request, "limit", default=20, minimum=1, maximum=100)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        min_discount_raw = request.query_params.get("min_discount")
        min_discount_pct: Optional[Decimal] = None
        if min_discount_raw:
            try:
                min_discount_pct = Decimal(str(min_discount_raw))
            except Exception:
                return Response(
                    {"detail": "min_discount debe ser numérico (ej: 20 o 20.5)."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        discounted_price_qs = Price.objects.filter(
            listing=OuterRef("pk"),
            original_price__isnull=False,
            original_price__gt=F("price"),
            is_available=True,
        ).order_by("-recorded_at")

        listings = (
            ProductListing.objects.filter(is_active=True, is_available=True)
            .select_related("product", "store")
            .annotate(
                latest_price=Subquery(discounted_price_qs.values("price")[:1]),
                latest_original=Subquery(discounted_price_qs.values("original_price")[:1]),
            )
            .filter(latest_price__isnull=False, latest_original__isnull=False)
        )

        if min_discount_pct is not None:
            # descuento% = (orig - price) / orig * 100
            # => price <= orig * (1 - pct/100)
            factor = (Decimal("100") - min_discount_pct) / Decimal("100")
            listings = listings.filter(latest_price__lte=F("latest_original") * factor)

        # Orden por monto descuento (orig - price) desc
        listings = listings.order_by((F("latest_original") - F("latest_price")).desc())[:limit]

        serializer = ListingListSerializer(listings, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def trending(self, request: Request) -> Response:
        """
        Productos con más registros de precio en una ventana reciente.

        Query params:
        - days (default 7, min 1, max 90)
        - limit (default 20, min 1, max 100)
        """
        try:
            days = _parse_int(request, "days", default=7, minimum=1, maximum=90)
            limit = _parse_int(request, "limit", default=20, minimum=1, maximum=100)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        since = timezone.now() - timedelta(days=days)

        qs = (
            Product.objects.filter(is_active=True, listings__price_history__recorded_at__gte=since)
            .annotate(price_changes=Count("listings__price_history"))
            .filter(price_changes__gt=1)
            .select_related("category")
            .annotate(listings_count=Count("listings", distinct=True))
            .order_by("-price_changes")[:limit]
        )

        serializer = ProductListSerializer(qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)


class ProductListingViewSet(viewsets.ModelViewSet):
    """
    CRUD de ProductListing + historial + actualización de disponibilidad.
    """

    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["store", "product", "is_available", "is_active"]
    ordering_fields = ["last_scraped_at", "created_at"]
    ordering = ["-created_at"]

    def get_serializer_class(self):
        if self.action == "list":
            return ListingListSerializer
        if self.action in {"create", "update", "partial_update"}:
            return ListingCreateSerializer
        return ListingDetailSerializer

    def get_queryset(self) -> QuerySet[ProductListing]:
        qs = ProductListing.objects.select_related("product", "store")

        # Para list/retrieve: evitamos N+1 del serializer (precio actual/historial)
        if self.action in {"list", "retrieve"}:
            qs = qs.prefetch_related("price_history")

        return qs

    @action(detail=True, methods=["get"])
    def price_history(self, request: Request, pk: Optional[int] = None) -> Response:
        """
        Historial de precios del listing.

        Query params:
        - days (default 30, min 1, max 365)
        - limit (default 100, min 1, max 500)
        """
        listing = self.get_object()

        try:
            days = _parse_int(request, "days", default=30, minimum=1, maximum=365)
            limit = _parse_int(request, "limit", default=100, minimum=1, maximum=500)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        start = timezone.now() - timedelta(days=days)
        prices_qs = listing.price_history.filter(recorded_at__gte=start).order_by("-recorded_at")[:limit]

        serializer = PriceSerializer(prices_qs, many=True, context=self.get_serializer_context())
        return Response(serializer.data)

    @action(detail=True, methods=["post"])
    def update_availability(self, request: Request, pk: Optional[int] = None) -> Response:
        """
        Actualiza disponibilidad del listing.

        Body:
        - is_available: bool (requerido)
        - stock_status: str (opcional)
        """
        listing = self.get_object()

        if "is_available" not in request.data:
            return Response(
                {"detail": "Se requiere el campo is_available."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        listing.is_available = bool(request.data.get("is_available"))
        listing.stock_status = str(request.data.get("stock_status", "")).strip()
        listing.update_scrape_timestamp()

        serializer = self.get_serializer(listing, context=self.get_serializer_context())
        return Response(serializer.data)


class PriceViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Consulta read-only de Price + acciones:
    - GET /prices/recent/
    - GET /prices/statistics/
    """

    serializer_class = PriceSerializer
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ["listing", "is_available"]
    ordering = ["-recorded_at"]

    def get_queryset(self) -> QuerySet[Price]:
        return Price.objects.select_related("listing__product", "listing__store")

    @action(detail=False, methods=["get"])
    def recent(self, request: Request) -> Response:
        """
        Precios recientes.

        Query params:
        - limit (default 50, max 200)
        - hours (default 24, min 1, max 168)
        """
        try:
            limit = _parse_int(request, "limit", default=50, minimum=1, maximum=200)
            hours = _parse_int(request, "hours", default=24, minimum=1, maximum=168)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        since = timezone.now() - timedelta(hours=hours)
        qs = self.get_queryset().filter(recorded_at__gte=since).order_by("-recorded_at")

        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(qs[:limit], many=True)
        return Response(serializer.data)

    @action(detail=False, methods=["get"])
    def statistics(self, request: Request) -> Response:
        """
        Estadísticas globales de precios (solo disponibles).

        Query params:
        - days (default 30, min 1, max 365)
        """
        try:
            days = _parse_int(request, "days", default=30, minimum=1, maximum=365)
        except ValueError as e:
            return Response({"detail": str(e)}, status=status.HTTP_400_BAD_REQUEST)

        since = timezone.now() - timedelta(days=days)

        stats = self.get_queryset().filter(recorded_at__gte=since, is_available=True).aggregate(
            total_records=Count("id"),
            avg_price=Avg("price"),
            min_price=Min("price"),
            max_price=Max("price"),
            unique_listings=Count("listing", distinct=True),
        )

        # Normalización: evita nulls raros si no hay datos
        stats["total_records"] = int(stats["total_records"] or 0)
        stats["unique_listings"] = int(stats["unique_listings"] or 0)
        stats["avg_price"] = stats["avg_price"]
        stats["min_price"] = stats["min_price"]
        stats["max_price"] = stats["max_price"]

        return Response(stats)