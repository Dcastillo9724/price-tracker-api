"""
Modelos para gestión de productos y seguimiento de precios.

Este módulo contiene los modelos principales del sistema de tracking de precios:
- Store: Tiendas donde se venden productos
- Category: Categorías jerárquicas (por tienda)
- Product: Productos únicos (agnóstico de tienda)
- ProductListing: Producto específico en una tienda
- Price: Historial de precios por listing

Arquitectura:
    Un Product puede tener múltiples ProductListing (uno por tienda).
    Cada ProductListing tiene su propio historial de Price.
    Los precios SOLO se almacenan en Price, nunca en ProductListing.

Notas de diseño:
- Se prioriza integridad a nivel DB con constraints.
- Se evita N+1 en helpers usando prefetch cuando es razonable.
- __str__ NO debe disparar queries costosas (por eso no calcula precio).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Optional

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


_DECIMAL_ZERO = Decimal("0")


class Store(models.Model):
    """
    Tienda donde se venden productos.

    Representa una plataforma de e-commerce (MercadoLibre, Falabella, etc.)
    donde se pueden listar productos para seguimiento de precios.
    """

    class StoreCode(models.TextChoices):
        """Códigos únicos de tiendas soportadas."""
        MERCADOLIBRE = "ML", "MercadoLibre"
        EXITO = "EX", "Éxito"
        FALABELLA = "FA", "Falabella"
        ALKOSTO = "AL", "Alkosto"
        JUMBO = "JU", "Jumbo"

    name = models.CharField(
        _("nombre"),
        max_length=100,
        unique=True,
        help_text=_("Nombre completo de la tienda"),
    )
    code = models.CharField(
        _("código"),
        max_length=2,
        choices=StoreCode.choices,
        unique=True,
        help_text=_("Código único de 2 caracteres"),
    )
    base_url = models.URLField(
        _("URL base"),
        help_text=_("URL base del sitio web"),
    )
    is_active = models.BooleanField(
        _("activa"),
        default=True,
        help_text=_("Indica si la tienda está activa"),
    )
    scraping_enabled = models.BooleanField(
        _("scraping habilitado"),
        default=True,
        help_text=_("Habilitar scraping automático"),
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        db_table = "store"
        verbose_name = _("tienda")
        verbose_name_plural = _("tiendas")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active", "scraping_enabled"]),
        ]
        constraints = [
            # Por higiene: evita strings vacíos/espacios en nombres.
            models.CheckConstraint(
                name="store_name_not_blank",
                check=~Q(name=""),
            ),
        ]

    def __str__(self) -> str:
        """Representación: 'Nombre (CODE)'."""
        return f"{self.name} ({self.code})"

    def get_active_listings_count(self) -> int:
        """
        Retorna el número de listings activos en esta tienda.

        Returns:
            int: Número de ProductListing activos asociados a esta tienda.
        """
        return self.listings.filter(is_active=True).count()


class Category(models.Model):
    """
    Categoría de productos con soporte para jerarquía y asociación a tienda.

    Las categorías SON específicas por tienda, ya que cada e-commerce maneja su
    propia taxonomía, URLs y estructura de navegación.
    """

    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="categories",
        verbose_name=_("tienda"),
        help_text=_("Tienda a la que pertenece esta categoría"),
    )
    name = models.CharField(
        _("nombre"),
        max_length=200,
        help_text=_("Nombre de la categoría"),
    )
    url = models.URLField(
        _("URL"),
        max_length=1000,
        blank=True,
        help_text=_("URL de la categoría en la tienda"),
    )
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
        verbose_name=_("padre"),
        help_text=_("Categoría padre dentro de la misma tienda"),
    )
    description = models.TextField(
        _("descripción"),
        blank=True,
        help_text=_("Descripción de la categoría"),
    )
    is_active = models.BooleanField(
        _("activa"),
        default=True,
        help_text=_("Indica si la categoría está activa"),
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        db_table = "category"
        verbose_name = _("categoría")
        verbose_name_plural = _("categorías")
        ordering = ["name"]
        indexes = [
            models.Index(fields=["store", "parent"]),
            models.Index(fields=["store", "is_active"]),
        ]
        constraints = [
            # Unicidad por tienda + padre + nombre.
            models.UniqueConstraint(
                fields=["store", "parent", "name"],
                name="uq_category_store_parent_name",
            ),
            # Evita nombre vacío (si quieres permitirlo, borra esto).
            models.CheckConstraint(
                name="category_name_not_blank",
                check=~Q(name=""),
            ),
        ]

    def clean(self) -> None:
        """
        Validaciones de dominio.

        - Si hay parent, debe pertenecer a la MISMA tienda.
        """
        super().clean()
        if self.parent and self.parent.store_id != self.store_id:
            raise ValidationError(
                {"parent": _("La categoría padre debe pertenecer a la misma tienda.")}
            )

    def __str__(self) -> str:
        """Representación con jerarquía y tienda."""
        if self.parent:
            return f"{self.store.code} | {self.parent.name} > {self.name}"
        return f"{self.store.code} | {self.name}"

    def get_full_path(self) -> str:
        """
        Retorna la ruta jerárquica completa de la categoría.

        Returns:
            str: Ruta completa separada por ' > '.
        """
        path = [self.name]
        parent = self.parent
        while parent:
            path.append(parent.name)
            parent = parent.parent
        return " > ".join(reversed(path))

    def get_all_children(self) -> List["Category"]:
        """
        Retorna todas las subcategorías recursivamente (solo activas).

        Returns:
            list[Category]: Hijas y descendientes activos.
        """
        children: List["Category"] = []
        for child in self.children.filter(is_active=True):
            children.append(child)
            children.extend(child.get_all_children())
        return children


class Product(models.Model):
    """
    Producto único, independiente de la tienda donde se vende.

    Este modelo NO contiene precios ni info específica de tienda.
    Los precios viven en Price (vía ProductListing).
    """

    name = models.CharField(
        _("nombre"),
        max_length=500,
        help_text=_("Nombre completo del producto"),
    )
    brand = models.CharField(
        _("marca"),
        max_length=100,
        blank=True,
        help_text=_("Marca del producto"),
    )
    model = models.CharField(
        _("modelo"),
        max_length=200,
        blank=True,
        help_text=_("Modelo específico del producto"),
    )
    description = models.TextField(
        _("descripción"),
        blank=True,
        help_text=_("Descripción detallada del producto"),
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="products",
        verbose_name=_("categoría"),
        help_text=_("Categoría del producto"),
    )
    is_active = models.BooleanField(
        _("activo"),
        default=True,
        help_text=_("Indica si el producto está activo"),
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        db_table = "product"
        verbose_name = _("producto")
        verbose_name_plural = _("productos")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["brand"]),
            models.Index(fields=["category", "is_active"]),
        ]
        constraints = [
            models.CheckConstraint(
                name="product_name_not_blank",
                check=~Q(name=""),
            ),
        ]

    def __str__(self) -> str:
        """Retorna el nombre del producto (sin queries extra)."""
        return self.name

    def get_best_price(self) -> Optional["ProductListing"]:
        """
        Retorna el listing con el mejor precio actual (más bajo).

        Recomendación de performance:
            Si vas a llamar esto para muchos productos, precarga listings con:
            - select_related('store')
            - prefetch_related('price_history') (limitando al más reciente si lo implementas)

        Returns:
            ProductListing | None: Listing con mejor precio disponible o None.
        """
        best_listing: Optional["ProductListing"] = None
        best_price: Optional["Price"] = None

        qs = (
            self.listings.filter(is_active=True)
            .select_related("store")
            .prefetch_related(
                models.Prefetch(
                    "price_history",
                    queryset=Price.objects.order_by("-recorded_at"),
                    to_attr="_prefetched_prices",
                )
            )
        )

        for listing in qs:
            latest = listing.get_latest_price()
            if latest and latest.is_available:
                if best_price is None or latest.price < best_price.price:
                    best_price = latest
                    best_listing = listing

        return best_listing

    def get_price_range(self) -> Optional[Dict[str, Decimal]]:
        """
        Retorna el rango de precios del producto entre todas las tiendas.

        Returns:
            dict | None: {'min': ..., 'max': ..., 'count': ...} o None si no hay precios.
        """
        prices: List[Decimal] = []

        qs = self.listings.filter(is_active=True).prefetch_related(
            models.Prefetch(
                "price_history",
                queryset=Price.objects.order_by("-recorded_at"),
                to_attr="_prefetched_prices",
            )
        )

        for listing in qs:
            latest = listing.get_latest_price()
            if latest and latest.is_available:
                prices.append(latest.price)

        if not prices:
            return None

        return {"min": min(prices), "max": max(prices), "count": Decimal(len(prices))}

    def get_average_price(self) -> Optional[Decimal]:
        """
        Retorna el precio promedio del producto entre todas las tiendas (solo disponibles).

        Returns:
            Decimal | None: Promedio o None si no hay precios.
        """
        prices: List[Decimal] = []

        qs = self.listings.filter(is_active=True).prefetch_related(
            models.Prefetch(
                "price_history",
                queryset=Price.objects.order_by("-recorded_at"),
                to_attr="_prefetched_prices",
            )
        )

        for listing in qs:
            latest = listing.get_latest_price()
            if latest and latest.is_available:
                prices.append(latest.price)

        if not prices:
            return None

        return sum(prices, _DECIMAL_ZERO) / Decimal(len(prices))


class ProductListing(models.Model):
    """
    Producto en una tienda específica.

    Contiene información específica de la tienda (URL, disponibilidad)
    pero NO contiene precios: los precios viven en Price.
    """

    product = models.ForeignKey(
        Product,
        on_delete=models.CASCADE,
        related_name="listings",
        verbose_name=_("producto"),
        help_text=_("Producto al que pertenece"),
    )
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name="listings",
        verbose_name=_("tienda"),
        help_text=_("Tienda donde se vende"),
    )
    url = models.URLField(
        _("URL"),
        max_length=1000,
        help_text=_("URL del producto en la tienda"),
    )
    is_available = models.BooleanField(
        _("disponible"),
        default=True,
        help_text=_("Disponibilidad actual"),
    )
    stock_status = models.CharField(
        _("stock"),
        max_length=100,
        blank=True,
        help_text=_('Estado del stock (ej: "En stock", "Últimas unidades")'),
    )
    is_active = models.BooleanField(
        _("activo"),
        default=True,
        help_text=_("Indica si el listing está activo"),
    )
    last_scraped_at = models.DateTimeField(
        _("último scraping"),
        null=True,
        blank=True,
        help_text=_("Última vez que se hizo scraping"),
    )
    created_at = models.DateTimeField(_("creado"), auto_now_add=True)
    updated_at = models.DateTimeField(_("actualizado"), auto_now=True)

    class Meta:
        db_table = "product_listing"
        verbose_name = _("listado")
        verbose_name_plural = _("listados")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["product", "store"]),
            models.Index(fields=["is_active", "is_available"]),
            models.Index(fields=["last_scraped_at"]),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["product", "store"],
                name="uq_listing_product_store",
            ),
        ]

    def __str__(self) -> str:
        """
        Representación sin queries extra.

        Nota: NO incluimos el precio acá para no disparar queries en listados/admin.
        """
        return f"{self.product.name} - {self.store.code}"

    def get_latest_price(self) -> Optional["Price"]:
        """
        Retorna el precio más reciente de este listing.

        Optimización:
            Si se usó Prefetch con to_attr='_prefetched_prices', se usa esa data
            sin tocar la DB.

        Returns:
            Price | None: Precio más reciente o None.
        """
        prefetched = getattr(self, "_prefetched_prices", None)
        if prefetched is not None:
            return prefetched[0] if prefetched else None
        return self.price_history.order_by("-recorded_at").first()

    def get_discount_percentage(self) -> Decimal:
        """
        Calcula el porcentaje de descuento basado en precio original.

        Returns:
            Decimal: Porcentaje (0 si no hay descuento).
        """
        latest = self.get_latest_price()
        if not latest or latest.original_price is None:
            return Decimal("0")

        if latest.original_price > latest.price and latest.original_price > 0:
            discount = ((latest.original_price - latest.price) / latest.original_price) * 100
            return discount.quantize(Decimal("0.01"))
        return Decimal("0")

    def update_scrape_timestamp(self) -> None:
        """Actualiza el timestamp del último scraping a ahora."""
        self.last_scraped_at = timezone.now()
        self.save(update_fields=["last_scraped_at"])


class Price(models.Model):
    """
    Registro de precio en el historial de un listing.

    ÚNICA FUENTE DE PRECIOS EN EL SISTEMA.
    Cada scraping crea un nuevo registro Price con el precio actual.
    """

    listing = models.ForeignKey(
        ProductListing,
        on_delete=models.CASCADE,
        related_name="price_history",
        verbose_name=_("listado"),
        help_text=_("ProductListing al que pertenece"),
    )
    price = models.DecimalField(
        _("precio"),
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(_DECIMAL_ZERO)],
        help_text=_("Precio actual del producto"),
    )
    original_price = models.DecimalField(
        _("precio original"),
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        validators=[MinValueValidator(_DECIMAL_ZERO)],
        help_text=_("Precio original antes de descuento"),
    )
    is_available = models.BooleanField(
        _("disponible"),
        default=True,
        help_text=_("Si el producto estaba disponible al momento del registro"),
    )
    recorded_at = models.DateTimeField(
        _("fecha"),
        default=timezone.now,
        db_index=True,
        help_text=_("Fecha y hora del registro de precio"),
    )

    class Meta:
        db_table = "price"
        verbose_name = _("precio")
        verbose_name_plural = _("precios")
        ordering = ["-recorded_at"]
        indexes = [
            models.Index(fields=["listing", "recorded_at"]),
            models.Index(fields=["is_available"]),
        ]
        constraints = [
            # Si hay original_price, debe ser >= price (define "original" como precio antes del descuento).
            models.CheckConstraint(
                name="price_original_gte_price_when_set",
                check=Q(original_price__isnull=True) | Q(original_price__gte=models.F("price")),
            ),
        ]

    def clean(self) -> None:
        """
        Validaciones de dominio adicionales.

        - original_price (si existe) debe ser >= price.
        """
        super().clean()
        if self.original_price is not None and self.original_price < self.price:
            raise ValidationError(
                {"original_price": _("El precio original no puede ser menor que el precio actual.")}
            )

    def __str__(self) -> str:
        """Representación con producto, precio y fecha (sin trabajo extra)."""
        return (
            f"{self.listing.product.name} - "
            f"${self.price} ({self.recorded_at.strftime('%Y-%m-%d %H:%M')})"
        )

    @property
    def has_discount(self) -> bool:
        """Indica si este precio tiene descuento."""
        return self.original_price is not None and self.original_price > self.price

    @property
    def discount_amount(self) -> Optional[Decimal]:
        """Retorna el monto del descuento (si aplica)."""
        return (self.original_price - self.price) if self.has_discount else None