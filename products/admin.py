"""
Configuración del Django Admin para productos y tracking de precios.

Este módulo registra los modelos en el panel de administración de Django
con interfaces personalizadas para facilitar la gestión de datos.

Admin Classes:
    - StoreAdmin: Gestión de tiendas
    - CategoryAdmin: Gestión de categorías jerárquicas
    - ProductAdmin: Gestión de productos
    - ProductListingAdmin: Gestión de listings
    - PriceAdmin: Visualización de historial de precios
"""

from typing import Optional

from django.contrib import admin
from django.db.models import Count, QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import Category, Price, Product, ProductListing, Store


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    """
    Admin para el modelo Store.
    
    Proporciona una interfaz para gestionar tiendas con filtros
    por estado y capacidad de búsqueda por nombre/código.
    
    List Display:
        - Nombre de la tienda
        - Código
        - Estado activo
        - Scraping habilitado
        - Contador de listings activos
    
    Features:
        - Filtros por is_active y scraping_enabled
        - Búsqueda por nombre y código
        - Acción para activar/desactivar scraping en masa
    """
    
    list_display = (
        'name',
        'code',
        'is_active_display',
        'scraping_enabled_display',
        'get_listings_count'
    )
    list_filter = ('is_active', 'scraping_enabled')
    search_fields = ('name', 'code')
    readonly_fields = ('created_at', 'updated_at')
    fieldsets = (
        ('Información Básica', {
            'fields': ('name', 'code', 'base_url')
        }),
        ('Configuración', {
            'fields': ('is_active', 'scraping_enabled')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[Store]:
        """
        Optimiza el queryset con prefetch de listings.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.prefetch_related('listings')
    
    def get_listings_count(self, obj: Store) -> int:
        """
        Retorna el número de listings activos.
        
        Args:
            obj: Instancia de Store
        
        Returns:
            Número de listings activos
        """
        return obj.listings.filter(is_active=True).count()
    get_listings_count.short_description = 'Listings activos'
    get_listings_count.admin_order_field = 'listings__count'
    
    def is_active_display(self, obj: Store) -> str:
        """
        Muestra el estado activo con color.
        
        Args:
            obj: Instancia de Store
        
        Returns:
            HTML con ícono de estado
        """
        if obj.is_active:
            return format_html(
                '<span style="color: green;">✓ Activa</span>'
            )
        return format_html(
            '<span style="color: red;">✗ Inactiva</span>'
        )
    is_active_display.short_description = 'Estado'
    
    def scraping_enabled_display(self, obj: Store) -> str:
        """
        Muestra el estado del scraping con color.
        
        Args:
            obj: Instancia de Store
        
        Returns:
            HTML con ícono de estado
        """
        if obj.scraping_enabled:
            return format_html(
                '<span style="color: green;">✓ Habilitado</span>'
            )
        return format_html(
            '<span style="color: orange;">✗ Deshabilitado</span>'
        )
    scraping_enabled_display.short_description = 'Scraping'
    
    actions = ['enable_scraping', 'disable_scraping']
    
    def enable_scraping(self, request: HttpRequest, queryset: QuerySet[Store]) -> None:
        """Acción para habilitar scraping en tiendas seleccionadas."""
        updated = queryset.update(scraping_enabled=True)
        self.message_user(request, f'{updated} tienda(s) actualizadas.')
    enable_scraping.short_description = 'Habilitar scraping'
    
    def disable_scraping(self, request: HttpRequest, queryset: QuerySet[Store]) -> None:
        """Acción para deshabilitar scraping en tiendas seleccionadas."""
        updated = queryset.update(scraping_enabled=False)
        self.message_user(request, f'{updated} tienda(s) actualizadas.')
    disable_scraping.short_description = 'Deshabilitar scraping'


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    """
    Admin para el modelo Category.
    
    Gestiona categorías jerárquicas con visualización de la
    ruta completa y contador de productos.
    
    List Display:
        - Nombre de la categoría
        - Categoría padre
        - Ruta completa
        - Estado activo
        - Contador de productos
    
    Features:
        - Filtros por is_active y parent
        - Búsqueda por nombre
        - Visualización jerárquica
    """
    
    list_display = (
        'name',
        'get_store_display',
        'parent',
        'get_full_path',
        'is_active_display',
        'get_products_count',
        'url'
    )
    list_filter = ('is_active', 'store', 'parent')
    search_fields = ('name',)
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('parent',)
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('store', 'name', 'parent', 'url')
        }),
        ('Contenido', {
            'fields': ('description',)
        }),
        ('Estado', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[Category]:
        """
        Optimiza el queryset con select_related y annotate.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.select_related('store', 'parent').annotate(
            products_count=Count('products', distinct=True)
        )
    
    def get_store_display(self, obj: Category) -> str:
        """
        Retorna el código y nombre de la tienda.
        
        Args:
            obj: Instancia de Category
        
        Returns:
            Código y nombre de tienda
        """
        return f"{obj.store.code} - {obj.store.name}"
    get_store_display.short_description = 'Tienda'
    get_store_display.admin_order_field = 'store__name'

    def get_full_path(self, obj: Category) -> str:
        """
        Retorna la ruta completa de la categoría.
        
        Args:
            obj: Instancia de Category
        
        Returns:
            Ruta jerárquica completa
        """
        return obj.get_full_path()
    get_full_path.short_description = 'Ruta completa'
    
    def get_products_count(self, obj: Category) -> int:
        """
        Retorna el número de productos en la categoría.
        
        Args:
            obj: Instancia de Category
        
        Returns:
            Número de productos
        """
        return obj.products.count()
    get_products_count.short_description = 'Productos'
    get_products_count.admin_order_field = 'products_count'
    
    def is_active_display(self, obj: Category) -> str:
        """Muestra el estado activo con color."""
        if obj.is_active:
            return format_html('<span style="color: green;">✓</span>')
        return format_html('<span style="color: red;">✗</span>')
    is_active_display.short_description = 'Activa'


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    """
    Admin para el modelo Product.
    
    Gestiona productos con visualización del mejor precio
    y número de tiendas donde está disponible.
    
    List Display:
        - Nombre del producto
        - Marca
        - Categoría
        - Mejor precio actual
        - Número de tiendas
        - Estado activo
    
    Features:
        - Filtros por categoría, is_active y brand
        - Búsqueda por nombre, marca y modelo
        - Raw ID fields para optimizar selección de categoría
        - Acciones en masa para activar/desactivar
    """
    
    list_display = (
        'name',
        'brand',
        'category',
        'get_best_price',
        'get_listings_count',
        'is_active_display'
    )
    list_filter = ('category', 'is_active', 'brand')
    search_fields = ('name', 'brand', 'model')
    raw_id_fields = ('category',)
    readonly_fields = ('created_at', 'updated_at')
    
    fieldsets = (
        ('Información del Producto', {
            'fields': ('name', 'brand', 'model')
        }),
        ('Clasificación', {
            'fields': ('category',)
        }),
        ('Descripción', {
            'fields': ('description',)
        }),
        ('Estado', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[Product]:
        """
        Optimiza el queryset con prefetch de listings y precios.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.select_related('category').prefetch_related(
            'listings',
            'listings__store',
            'listings__price_history'
        )
    
    def get_best_price(self, obj: Product) -> str:
        """
        Muestra el mejor precio disponible.
        
        Args:
            obj: Instancia de Product
        
        Returns:
            String formateado con precio y tienda
        """
        best = obj.get_best_price()
        if best:
            latest = best.get_latest_price()
            if latest:
                return format_html(
                    '<strong>${}</strong> <span style="color: #666;">({}) </span>',
                    f'{latest.price:,.0f}',
                    best.store.code
                )
        return format_html('<span style="color: #999;">-</span>')
    get_best_price.short_description = 'Mejor precio'
    
    def get_listings_count(self, obj: Product) -> str:
        """
        Muestra el número de tiendas donde está disponible.
        
        Args:
            obj: Instancia de Product
        
        Returns:
            Número de listings activos
        """
        count = obj.listings.filter(is_active=True).count()
        if count > 0:
            return format_html(
                '<span style="color: green;">{} tienda(s)</span>',
                count
            )
        return format_html('<span style="color: red;">0 tiendas</span>')
    get_listings_count.short_description = 'Disponibilidad'
    
    def is_active_display(self, obj: Product) -> str:
        """Muestra el estado activo con color."""
        if obj.is_active:
            return format_html('<span style="color: green;">✓</span>')
        return format_html('<span style="color: red;">✗</span>')
    is_active_display.short_description = 'Activo'
    
    actions = ['activate_products', 'deactivate_products']
    
    def activate_products(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        """Acción para activar productos seleccionados."""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} producto(s) activado(s).')
    activate_products.short_description = 'Activar productos seleccionados'
    
    def deactivate_products(self, request: HttpRequest, queryset: QuerySet[Product]) -> None:
        """Acción para desactivar productos seleccionados."""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} producto(s) desactivado(s).')
    deactivate_products.short_description = 'Desactivar productos seleccionados'


@admin.register(ProductListing)
class ProductListingAdmin(admin.ModelAdmin):
    """
    Admin para el modelo ProductListing.
    
    Gestiona los listings de productos en tiendas específicas,
    mostrando precio actual, descuento y disponibilidad.
    
    List Display:
        - Nombre del producto
        - Tienda
        - Precio actual
        - Descuento
        - Disponibilidad
        - Última actualización
    
    Features:
        - Filtros por store, is_available e is_active
        - Búsqueda por nombre de producto y URL
        - Raw ID fields para optimizar selección
        - Visualización de última fecha de scraping
    """
    
    list_display = (
        'get_product_name',
        'store',
        'get_current_price',
        'get_discount',
        'is_available_display',
        'last_scraped_at'
    )
    list_filter = ('store', 'is_available', 'is_active')
    search_fields = ('product__name', 'url')
    raw_id_fields = ('product',)
    readonly_fields = ('last_scraped_at', 'created_at', 'updated_at')
    date_hierarchy = 'last_scraped_at'
    
    fieldsets = (
        ('Relaciones', {
            'fields': ('product', 'store')
        }),
        ('Información de Tienda', {
            'fields': ('url',)
        }),
        ('Disponibilidad', {
            'fields': ('is_available', 'stock_status')
        }),
        ('Estado', {
            'fields': ('is_active',)
        }),
        ('Metadata', {
            'fields': ('last_scraped_at', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[ProductListing]:
        """
        Optimiza el queryset con select_related y prefetch.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.select_related('product', 'store').prefetch_related(
            'price_history'
        )
    
    def get_product_name(self, obj: ProductListing) -> str:
        """
        Retorna el nombre del producto con link.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Nombre del producto
        """
        return obj.product.name
    get_product_name.short_description = 'Producto'
    get_product_name.admin_order_field = 'product__name'
    
    def get_current_price(self, obj: ProductListing) -> str:
        """
        Muestra el precio actual formateado.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Precio formateado con color
        """
        latest = obj.get_latest_price()
        if latest:
            return format_html(
                '<strong>${}</strong>',
                f'{latest.price:,.0f}'
            )
        return format_html('<span style="color: #999;">Sin precio</span>')
    get_current_price.short_description = 'Precio actual'
    
    def get_discount(self, obj: ProductListing) -> str:
        """
        Muestra el porcentaje de descuento.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Descuento formateado con color
        """
        discount = obj.get_discount_percentage()
        if discount > 0:
            return format_html(
                '<span style="color: green; font-weight: bold;">-{}%</span>',
                discount
            )
        return format_html('<span style="color: #999;">-</span>')
    get_discount.short_description = 'Descuento'
    
    def is_available_display(self, obj: ProductListing) -> str:
        """
        Muestra la disponibilidad con color.
        
        Args:
            obj: Instancia de ProductListing
        
        Returns:
            Estado de disponibilidad formateado
        """
        if obj.is_available:
            return format_html('<span style="color: green;">✓ Disponible</span>')
        return format_html('<span style="color: red;">✗ No disponible</span>')
    is_available_display.short_description = 'Disponibilidad'


@admin.register(Price)
class PriceAdmin(admin.ModelAdmin):
    """
    Admin para el modelo Price.
    
    Visualización de solo lectura del historial de precios.
    No permite edición para mantener integridad del historial.
    
    List Display:
        - Producto
        - Tienda
        - Precio
        - Descuento (si aplica)
        - Disponibilidad
        - Fecha de registro
    
    Features:
        - Filtros por is_available y fecha
        - Búsqueda por nombre de producto
        - Jerarquía por fecha
        - Solo lectura (no editable)
    """
    
    list_display = (
        'get_product',
        'get_store',
        'get_price_display',
        'get_discount_display',
        'is_available_display',
        'recorded_at'
    )
    list_filter = ('is_available', 'recorded_at')
    search_fields = ('listing__product__name',)
    readonly_fields = ('listing', 'price', 'original_price', 'is_available', 'recorded_at')
    date_hierarchy = 'recorded_at'
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        """Deshabilita la creación manual de precios."""
        return False
    
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Optional[Price] = None
    ) -> bool:
        """Deshabilita la edición de precios."""
        return False
    
    def has_delete_permission(
        self,
        request: HttpRequest,
        obj: Optional[Price] = None
    ) -> bool:
        """Permite eliminación solo a superusuarios."""
        return request.user.is_superuser
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[Price]:
        """
        Optimiza el queryset con select_related.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.select_related('listing__product', 'listing__store')
    
    def get_product(self, obj: Price) -> str:
        """
        Retorna el nombre del producto.
        
        Args:
            obj: Instancia de Price
        
        Returns:
            Nombre del producto
        """
        return obj.listing.product.name
    get_product.short_description = 'Producto'
    get_product.admin_order_field = 'listing__product__name'
    
    def get_store(self, obj: Price) -> str:
        """
        Retorna el nombre de la tienda.
        
        Args:
            obj: Instancia de Price
        
        Returns:
            Nombre de la tienda
        """
        return obj.listing.store.name
    get_store.short_description = 'Tienda'
    get_store.admin_order_field = 'listing__store__name'
    
    def get_price_display(self, obj: Price) -> str:
        """
        Muestra el precio formateado.
        
        Args:
            obj: Instancia de Price
        
        Returns:
            Precio formateado
        """
        return format_html(
            '<strong>${}</strong>',
            f'{obj.price:,.0f}'
        )
    get_price_display.short_description = 'Precio'
    
    def get_discount_display(self, obj: Price) -> str:
        """
        Muestra el descuento si aplica.
        
        Args:
            obj: Instancia de Price
        
        Returns:
            Descuento formateado o guión
        """
        if obj.has_discount:
            discount_pct = ((obj.original_price - obj.price) / obj.original_price) * 100
            return format_html(
                '<span style="color: green;">-{:.1f}%</span> <span style="color: #999;">(${:,.0f})</span>',
                discount_pct,
                obj.original_price
            )
        return format_html('<span style="color: #999;">-</span>')
    get_discount_display.short_description = 'Descuento'
    
    def is_available_display(self, obj: Price) -> str:
        """
        Muestra la disponibilidad con color.
        
        Args:
            obj: Instancia de Price
        
        Returns:
            Estado de disponibilidad formateado
        """
        if obj.is_available:
            return format_html('<span style="color: green;">✓</span>')
        return format_html('<span style="color: red;">✗</span>')
    is_available_display.short_description = 'Disponible'