"""
Configuración del Django Admin para productos y tracking de precios.

Objetivo:
- Admin cómodo para operar datos (búsqueda, filtros, acciones).
- Performance: evitar N+1 con select_related / annotate cuando corresponda.
- Mantener historial de precios como "append-only": Price es solo lectura.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Optional

from django.contrib import admin
from django.db.models import Count, F, Q, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html
from django.utils.translation import gettext_lazy as _

from .models import Category, Price, Product, ProductListing, Store



def _icon_bool(value: bool, *, true_label: str = "✓", false_label: str = "✗") -> str:
    return true_label if value else false_label


def _colored(text: str, color: str) -> str:
    return format_html('<span style="color: {};">{}</span>', color, text)


def _money(value: Decimal) -> str:
    # Ajusta formato si quieres decimales; por precios en COP suele ser 0 decimales.
    return f"{value:,.0f}"


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """Admin para Store (tiendas)."""

    list_display = (
        "name",
        "code",
        "is_active_display",
        "scraping_enabled_display",
        "listings_count_display",
    )
    list_filter = ("is_active", "scraping_enabled", "code")
    search_fields = ("name", "code")
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_("Información Básica"), {"fields": ("name", "code", "base_url")}),
        (_("Configuración"), {"fields": ("is_active", "scraping_enabled")}),
        (_("Metadata"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ["enable_scraping", "disable_scraping"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Store]:
        qs = super().get_queryset(request)
        return qs.annotate(
            listings_count=Count("listings", filter=Q(listings__is_active=True), distinct=True)
        )

    @admin.display(description=_("Listings activos"), ordering="listings_count")
    def listings_count_display(self, obj: Store) -> int:
        return int(getattr(obj, "listings_count", 0))

    @admin.display(description=_("Estado"))
    def is_active_display(self, obj: Store) -> str:
        if obj.is_active:
            return _colored("✓ Activa", "green")
        return _colored("✗ Inactiva", "red")

    @admin.display(description=_("Scraping"))
    def scraping_enabled_display(self, obj: Store) -> str:
        if obj.scraping_enabled:
            return _colored("✓ Habilitado", "green")
        return _colored("✗ Deshabilitado", "orange")

    @admin.action(description=_("Habilitar scraping"))
    def enable_scraping(self, request: HttpRequest, queryset: QuerySet[Store]) -> None:
        updated = queryset.update(scraping_enabled=True)
        self.message_user(request, _("%(n)s tienda(s) actualizadas.") % {"n": updated})

    @admin.action(description=_("Deshabilitar scraping"))
    def disable_scraping(self, request: HttpRequest, queryset: QuerySet[Store]) -> None:
        updated = queryset.update(scraping_enabled=False)
        self.message_user(request, _("%(n)s tienda(s) actualizadas.") % {"n": updated})


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """Admin para Category (categorías por tienda, jerárquicas)."""

    list_display = (
        "name",
        "store_display",
        "parent",
        "full_path_display",
        "is_active_display",
        "products_count_display",
        "url",
    )
    list_filter = ("is_active", "store", "parent")
    search_fields = ("name",)
    readonly_fields = ("created_at", "updated_at")
    raw_id_fields = ("parent",)
    fieldsets = (
        (_("Información Básica"), {"fields": ("store", "name", "parent", "url")}),
        (_("Contenido"), {"fields": ("description",)}),
        (_("Estado"), {"fields": ("is_active",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[Category]:
        qs = super().get_queryset(request)
        return qs.select_related("store", "parent").annotate(
            products_count=Count("products", distinct=True)
        )

    @admin.display(description=_("Tienda"), ordering="store__name")
    def store_display(self, obj: Category) -> str:
        return f"{obj.store.code} - {obj.store.name}"

    @admin.display(description=_("Ruta completa"))
    def full_path_display(self, obj: Category) -> str:
        return obj.get_full_path()

    @admin.display(description=_("Productos"), ordering="products_count")
    def products_count_display(self, obj: Category) -> int:
        return int(getattr(obj, "products_count", 0))

    @admin.display(description=_("Activa"))
    def is_active_display(self, obj: Category) -> str:
        return _colored(_icon_bool(obj.is_active), "green" if obj.is_active else "red")


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """Admin para Product (producto global)."""

    list_display = (
        "name",
        "brand",
        "category",
        "best_price_display",
        "listings_count_display",
        "is_active_display",
    )
    list_filter = ("category", "is_active", "brand")
    search_fields = ("name", "brand", "model")
    raw_id_fields = ("category",)
    readonly_fields = ("created_at", "updated_at")
    fieldsets = (
        (_("Información del Producto"), {"fields": ("name", "brand", "model")}),
        (_("Clasificación"), {"fields": ("category",)}),
        (_("Descripción"), {"fields": ("description",)}),
        (_("Estado"), {"fields": ("is_active",)}),
        (_("Metadata"), {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    actions = ["activate_products", "deactivate_products"]

    def get_queryset(self, request: HttpRequest) -> QuerySet[Product]:
        qs = super().get_queryset(request)
        # listings_count para ordenar/mostrar sin consultas extra.
        qs = qs.select_related("category").annotate(
            listings_count=Count("listings", filter=Q(listings__is_active=True), distinct=True)
        ).prefetch_related(
            "listings__store",
            "listings__price_history",
        )
        return qs

    @admin.display(description=_("Mejor precio"))
    def best_price_display(self, obj: Product) -> str:
        best = obj.get_best_price()
        if not best:
            return _colored("-", "#999")

        latest = best.get_latest_price()
        if not latest:
            return _colored("-", "#999")

        return format_html(
            '<strong>${}</strong> <span style="color: #666;">({})</span>',
            _money(latest.price),
            best.store.code,
        )

    @admin.display(description=_("Disponibilidad"), ordering="listings_count")
    def listings_count_display(self, obj: Product) -> str:
        count = int(getattr(obj, "listings_count", 0))
        if count > 0:
            return _colored(f"{count} tienda(s)", "green")
        return _colored("0 tiendas", "red")

    @admin.display(description=_("Activo"))
    def is_active_display(self, obj: Product) -> str:
        return _colored(_icon_bool(obj.is_active), "green" if obj.is_active else "red")

    @admin.action(description=_("Activar productos seleccionados"))
    def activate_products(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        updated = queryset.update(is_active=True)
        self.message_user(request, _("%(n)s producto(s) activado(s).") % {"n": updated})

    @admin.action(description=_("Desactivar productos seleccionados"))
    def deactivate_products(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        updated = queryset.update(is_active=False)
        self.message_user(request, _("%(n)s producto(s) desactivado(s).") % {"n": updated})


@admin.register(ProductListing)
class ProductListingAdmin(admin.ModelAdmin):
    """Admin para ProductListing (producto por tienda)."""

    list_display = (
        "product_name",
        "store",
        "current_price_display",
        "discount_display",
        "is_available_display",
        "last_scraped_at",
        "is_active",
    )
    list_filter = ("store", "is_available", "is_active")
    search_fields = ("product__name", "url")
    raw_id_fields = ("product",)
    readonly_fields = ("last_scraped_at", "created_at", "updated_at")
    date_hierarchy = "last_scraped_at"
    fieldsets = (
        (_("Relaciones"), {"fields": ("product", "store")}),
        (_("Información de Tienda"), {"fields": ("url",)}),
        (_("Disponibilidad"), {"fields": ("is_available", "stock_status")}),
        (_("Estado"), {"fields": ("is_active",)}),
        (_("Metadata"), {"fields": ("last_scraped_at", "created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request: HttpRequest) -> QuerySet[ProductListing]:
        qs = super().get_queryset(request)
        return qs.select_related("product", "store").prefetch_related("price_history")

    @admin.display(description=_("Producto"), ordering="product__name")
    def product_name(self, obj: ProductListing) -> str:
        return obj.product.name

    @admin.display(description=_("Precio actual"))
    def current_price_display(self, obj: ProductListing) -> str:
        latest = obj.get_latest_price()
        if not latest:
            return _colored("Sin precio", "#999")
        return format_html("<strong>${}</strong>", _money(latest.price))

    @admin.display(description=_("Descuento"))
    def discount_display(self, obj: ProductListing) -> str:
        discount = obj.get_discount_percentage()
        if discount > 0:
            # quantize ya lo hace el modelo si usaste mi versión, pero esto es seguro.
            return format_html(
                '<span style="color: green; font-weight: bold;">-{}%</span>',
                discount,
            )
        return _colored("-", "#999")

    @admin.display(description=_("Disponibilidad"))
    def is_available_display(self, obj: ProductListing) -> str:
        if obj.is_available:
            return _colored("✓ Disponible", "green")
        return _colored("✗ No disponible", "red")


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    """Admin para Price (historial, solo lectura)."""

    list_display = (
        "product_display",
        "store_display",
        "price_display",
        "discount_display",
        "is_available_display",
        "recorded_at",
    )
    list_filter = ("is_available", "recorded_at", "listing__store")
    search_fields = ("listing__product__name",)
    readonly_fields = ("listing", "price", "original_price", "is_available", "recorded_at")
    date_hierarchy = "recorded_at"

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Optional[Price] = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Optional[Price] = None) -> bool:
        return bool(getattr(request.user, "is_superuser", False))

    def get_queryset(self, request: HttpRequest) -> QuerySet[Price]:
        qs = super().get_queryset(request)
        return qs.select_related("listing__product", "listing__store")

    @admin.display(description=_("Producto"), ordering="listing__product__name")
    def product_display(self, obj: Price) -> str:
        return obj.listing.product.name

    @admin.display(description=_("Tienda"), ordering="listing__store__name")
    def store_display(self, obj: Price) -> str:
        return obj.listing.store.name

    @admin.display(description=_("Precio"))
    def price_display(self, obj: Price) -> str:
        return format_html("<strong>${}</strong>", _money(obj.price))

    @admin.display(description=_("Descuento"))
    def discount_display(self, obj: Price) -> str:
        if not obj.has_discount:
            return _colored("-", "#999")

        # Evitar división por cero aunque no debería pasar.
        if not obj.original_price or obj.original_price <= 0:
            return _colored("-", "#999")

        discount_pct = ((obj.original_price - obj.price) / obj.original_price) * 100
        return format_html(
            '<span style="color: green;">-{:.1f}%</span> <span style="color: #999;">(orig: ${})</span>',
            float(discount_pct),
            _money(obj.original_price),
        )

    @admin.display(description=_("Disponible"))
    def is_available_display(self, obj: Price) -> str:
        return _colored(_icon_bool(obj.is_available), "green" if obj.is_available else "red")