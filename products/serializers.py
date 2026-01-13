"""
Serializers para la API de productos y tracking de precios.

Diseño:
- Los serializers exponen representación JSON consistente.
- Se evita duplicar reglas del modelo; se valida lo “de entrada” (trim, coherencia).
- Para performance, varios campos soportan valores anotados desde el queryset
  (ej: products_count, listings_count). Si no vienen anotados, se calcula fallback.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from django.utils.translation import gettext_lazy as _
from rest_framework import serializers

from .models import Category, Price, Product, ProductListing, Store


def _latest_price(listing: ProductListing) -> Optional[Price]:
    """
    Retorna el último Price de un listing.

    Usa optimización del modelo (prefetch to_attr) si existe.
    """
    return listing.get_latest_price()


class StoreSerializer(serializers.ModelSerializer):
    """
    Serializer para Store.

    - listings_count: idealmente viene anotado desde el queryset.
      Si no viene, se calcula como fallback.
    """

    listings_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            "id",
            "name",
            "code",
            "base_url",
            "is_active",
            "scraping_enabled",
            "listings_count",
            "created_at",
        ]
        read_only_fields = ["id", "created_at", "listings_count"]

    def get_listings_count(self, obj: Store) -> int:
        annotated = getattr(obj, "listings_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.listings.filter(is_active=True).count()


class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer para Category.

    full_path es calculado, y products_count soporta anotación.
    """

    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)

    full_path = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            "id",
            "store",
            "store_name",
            "store_code",
            "name",
            "parent",
            "url",
            "full_path",
            "products_count",
            "is_active",
        ]
        read_only_fields = ["id", "store_name", "store_code", "full_path", "products_count"]

    def get_full_path(self, obj: Category) -> str:
        return obj.get_full_path()

    def get_products_count(self, obj: Category) -> int:
        annotated = getattr(obj, "products_count", None)
        if annotated is not None:
            return int(annotated)
        # Fallback: puede ser costoso si se usa masivamente sin annotate.
        return obj.products.count()

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validación de coherencia:
        - parent (si existe) debe pertenecer a la misma tienda.
        """
        parent = attrs.get("parent")
        store = attrs.get("store")

        if store is None and self.instance is not None:
            store = self.instance.store

        if parent is not None and store is not None and parent.store_id != store.id:
            raise serializers.ValidationError(
                {"parent": _("La categoría padre debe pertenecer a la misma tienda.")}
            )

        return attrs


class CategoryTreeSerializer(serializers.ModelSerializer):
    """
    Serializer para mostrar categorías en estructura de árbol (recursivo).
    """

    children = serializers.SerializerMethodField()
    products_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ["id", "name", "children", "products_count"]

    def get_children(self, obj: Category) -> list:
        qs = obj.children.filter(is_active=True)
        return CategoryTreeSerializer(qs, many=True, context=self.context).data

    def get_products_count(self, obj: Category) -> int:
        annotated = getattr(obj, "products_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.products.count()


class PriceSerializer(serializers.ModelSerializer):
    """Serializer para Price (historial)."""

    class Meta:
        model = Price
        fields = ["id", "price", "original_price", "is_available", "recorded_at"]
        read_only_fields = ["id", "recorded_at"]


class PriceStatsSerializer(serializers.Serializer):
    """Serializer para retornar estadísticas agregadas de precios (no-model)."""

    min_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    max_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    avg_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    current_price = serializers.DecimalField(max_digits=12, decimal_places=2)
    lowest_date = serializers.DateTimeField()
    highest_date = serializers.DateTimeField()


class ListingListSerializer(serializers.ModelSerializer):
    """
    Serializer de ProductListing para listados.

    Nota de performance: para listados masivos, en views se debe usar:
      - select_related('product', 'store')
      - prefetch_related(Prefetch('price_history', ...)) o anotación del último precio.
    """

    product_name = serializers.CharField(source="product.name", read_only=True)
    store_name = serializers.CharField(source="store.name", read_only=True)
    store_code = serializers.CharField(source="store.code", read_only=True)

    current_price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()

    class Meta:
        model = ProductListing
        fields = [
            "id",
            "product_name",
            "store_name",
            "store_code",
            "url",
            "current_price",
            "original_price",
            "discount",
            "is_available",
            "last_scraped_at",
        ]

    def get_current_price(self, obj: ProductListing) -> Optional[Decimal]:
        latest = _latest_price(obj)
        return latest.price if latest else None

    def get_original_price(self, obj: ProductListing) -> Optional[Decimal]:
        latest = _latest_price(obj)
        return latest.original_price if (latest and latest.original_price) else None

    def get_discount(self, obj: ProductListing) -> Decimal:
        return obj.get_discount_percentage()


class ListingDetailSerializer(serializers.ModelSerializer):
    """
    Serializer de ProductListing para detalle.

    Incluye historial reciente de precios.
    """

    product = serializers.SerializerMethodField()
    store = StoreSerializer(read_only=True)

    current_price = serializers.SerializerMethodField()
    original_price = serializers.SerializerMethodField()
    discount = serializers.SerializerMethodField()
    recent_prices = serializers.SerializerMethodField()

    class Meta:
        model = ProductListing
        fields = [
            "id",
            "product",
            "store",
            "url",
            "current_price",
            "original_price",
            "discount",
            "is_available",
            "stock_status",
            "recent_prices",
            "last_scraped_at",
            "created_at",
        ]

    def get_product(self, obj: ProductListing) -> Dict[str, Any]:
        return {
            "id": obj.product_id,
            "name": obj.product.name,
            "brand": obj.product.brand,
            "category": obj.product.category.name if obj.product.category else None,
        }

    def get_current_price(self, obj: ProductListing) -> Optional[Decimal]:
        latest = _latest_price(obj)
        return latest.price if latest else None

    def get_original_price(self, obj: ProductListing) -> Optional[Decimal]:
        latest = _latest_price(obj)
        return latest.original_price if (latest and latest.original_price) else None

    def get_discount(self, obj: ProductListing) -> Decimal:
        return obj.get_discount_percentage()

    def get_recent_prices(self, obj: ProductListing) -> list:
        # Tip: en views, prefetch de price_history ordenado y sliceable si quieres.
        prices = obj.price_history.all().order_by("-recorded_at")[:20]
        return PriceSerializer(prices, many=True, context=self.context).data


class ListingCreateSerializer(serializers.ModelSerializer):
    """
    Serializer para crear/actualizar ProductListing (campos editables).
    """

    class Meta:
        model = ProductListing
        fields = ["product", "store", "url", "is_available", "stock_status", "is_active"]

    def validate_url(self, value: str) -> str:
        value = (value or "").strip()
        if not value:
            raise serializers.ValidationError(_("La URL no puede estar vacía."))
        return value


class ProductListSerializer(serializers.ModelSerializer):
    """
    Serializer de Product para listados.

    best_price usa lógica del modelo; para listados grandes,
    lo optimizamos en views con prefetch/annotate.
    """

    category_name = serializers.CharField(source="category.name", read_only=True, default=None)
    listings_count = serializers.SerializerMethodField()
    best_price = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ["id", "name", "brand", "model", "category_name", "best_price", "listings_count"]

    def get_listings_count(self, obj: Product) -> int:
        annotated = getattr(obj, "listings_count", None)
        if annotated is not None:
            return int(annotated)
        return obj.listings.count()

    def get_best_price(self, obj: Product) -> Optional[Dict[str, Any]]:
        best_listing = obj.get_best_price()
        if not best_listing:
            return None

        latest = best_listing.get_latest_price()
        if not latest or not latest.is_available:
            return None

        return {
            "price": latest.price,
            "store": best_listing.store.name,
            "url": best_listing.url,
        }


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Serializer de Product para detalle.

    Incluye listings activos (ligeros), best_price y price_range.
    """

    category = CategorySerializer(read_only=True)
    listings = serializers.SerializerMethodField()
    best_price = serializers.SerializerMethodField()
    price_range = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            "id",
            "name",
            "brand",
            "model",
            "description",
            "category",
            "listings",
            "best_price",
            "price_range",
            "is_active",
        ]

    def get_listings(self, obj: Product) -> list:
        qs = obj.listings.filter(is_active=True).select_related("store", "product")
        return ListingListSerializer(qs, many=True, context=self.context).data

    def get_best_price(self, obj: Product) -> Optional[Dict[str, Any]]:
        best_listing = obj.get_best_price()
        if not best_listing:
            return None

        latest = best_listing.get_latest_price()
        if not latest or not latest.is_available:
            return None

        return {
            "price": latest.price,
            "store": best_listing.store.name,
            "store_code": best_listing.store.code,
            "url": best_listing.url,
        }

    def get_price_range(self, obj: Product) -> Optional[Dict[str, Any]]:
        pr = obj.get_price_range()
        if not pr:
            return None
        # En models.py te dejé 'count' como Decimal en mi versión; si en tu modelo original es int,
        # igual funciona. Aquí normalizamos a int.
        count = int(pr.get("count")) if pr.get("count") is not None else 0
        return {"min": pr["min"], "max": pr["max"], "count": count}


class ProductCreateSerializer(serializers.ModelSerializer):
    """Serializer para crear/actualizar Product (campos editables)."""

    class Meta:
        model = Product
        fields = ["name", "brand", "model", "description", "category", "is_active"]

    def validate_name(self, value: str) -> str:
        value = (value or "").strip()
        if len(value) < 3:
            raise serializers.ValidationError(_("El nombre debe tener al menos 3 caracteres."))
        return value

    def validate_brand(self, value: str) -> str:
        return value.strip() if value else value

    def validate_model(self, value: str) -> str:
        return value.strip() if value else value

    def validate(self, attrs: Dict[str, Any]) -> Dict[str, Any]:
        category = attrs.get("category")
        if category and not category.is_active:
            raise serializers.ValidationError(
                {"category": _("No se puede asignar una categoría inactiva.")}
            )
        return attrs