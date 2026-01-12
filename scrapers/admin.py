"""
Configuración del Django Admin para scrapers.

Este módulo registra los modelos de scraping en el panel de administración
con interfaces personalizadas para monitoreo y gestión de ejecuciones.

Admin Classes:
    - ScraperRunAdmin: Gestión de ejecuciones de scraping
    - ScraperErrorAdmin: Gestión de errores de scraping
"""

from typing import Optional

from django.contrib import admin
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils.html import format_html

from .models import ScraperError, ScraperRun


@admin.register(ScraperRun)
class ScraperRunAdmin(admin.ModelAdmin):
    """
    Admin para el modelo ScraperRun.
    
    Proporciona una interfaz para monitorear ejecuciones de scraping
    con métricas de rendimiento y filtros por estado.
    
    List Display:
        - Tienda
        - Estado de la ejecución
        - Tipo de trigger
        - Fecha de inicio
        - Productos scrapeados
        - Conteo de errores
        - Tasa de éxito
    
    Features:
        - Filtros por status, trigger_type, store y fecha
        - Búsqueda por nombre de tienda y notas
        - Campos de solo lectura para timestamps
        - Jerarquía por fecha de inicio
        - Visualización de tasa de éxito
    """
    
    list_display = (
        'store',
        'status_display',
        'trigger_type',
        'started_at',
        'products_scraped',
        'errors_count',
        'get_success_rate'
    )
    list_filter = ('status', 'trigger_type', 'store', 'started_at')
    search_fields = ('store__name', 'notes', 'task_id')
    readonly_fields = ('started_at', 'finished_at', 'execution_time')
    date_hierarchy = 'started_at'
    
    fieldsets = (
        ('Información Básica', {
            'fields': ('store', 'status', 'trigger_type', 'task_id')
        }),
        ('Tiempos', {
            'fields': ('started_at', 'finished_at', 'execution_time')
        }),
        ('Métricas', {
            'fields': (
                'products_scraped',
                'products_updated',
                'products_created',
                'errors_count'
            )
        }),
        ('Notas', {
            'fields': ('notes',),
            'classes': ('collapse',)
        }),
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[ScraperRun]:
        """
        Optimiza el queryset con select_related.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.select_related('store')
    
    def status_display(self, obj: ScraperRun) -> str:
        """
        Muestra el estado con color según el resultado.
        
        Args:
            obj: Instancia de ScraperRun
        
        Returns:
            HTML con estado coloreado
        """
        colors = {
            'COMPLETED': 'green',
            'RUNNING': 'blue',
            'FAILED': 'red',
            'PARTIAL': 'orange',
            'PENDING': 'gray',
        }
        color = colors.get(obj.status, 'black')
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}</span>',
            color,
            obj.get_status_display()
        )
    status_display.short_description = 'Estado'
    
    def get_success_rate(self, obj: ScraperRun) -> str:
        """
        Muestra la tasa de éxito con formato de porcentaje.
        
        Args:
            obj: Instancia de ScraperRun
        
        Returns:
            Tasa de éxito formateada
        """
        rate = obj.get_success_rate()
        if rate >= 95:
            color = 'green'
        elif rate >= 80:
            color = 'orange'
        else:
            color = 'red'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{}%</span>',
            color,
            rate
        )
    get_success_rate.short_description = 'Éxito'
    
    def has_add_permission(self, request: HttpRequest) -> bool:
        """
        Deshabilita la creación manual de ejecuciones.
        
        Las ejecuciones se crean automáticamente desde comandos o tareas.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            False siempre
        """
        return False
    
    def has_change_permission(
        self,
        request: HttpRequest,
        obj: Optional[ScraperRun] = None
    ) -> bool:
        """
        Deshabilita la edición de ejecuciones.
        
        Args:
            request: HttpRequest del admin
            obj: Instancia de ScraperRun
        
        Returns:
            False siempre
        """
        return False


@admin.register(ScraperError)
class ScraperErrorAdmin(admin.ModelAdmin):
    """
    Admin para el modelo ScraperError.
    
    Proporciona una interfaz para revisar y gestionar errores
    ocurridos durante el scraping.
    
    List Display:
        - Ejecución relacionada
        - Tipo de error
        - Producto/listing afectado
        - Fecha de ocurrencia
        - Estado de resolución
    
    Features:
        - Filtros por tipo de error, estado de resolución y fecha
        - Búsqueda por mensaje, URL y producto
        - Campos de solo lectura para timestamp
        - Acción para marcar errores como resueltos
        - Jerarquía por fecha de ocurrencia
    """
    
    list_display = (
        'scraper_run',
        'error_type_display',
        'get_listing',
        'occurred_at',
        'is_resolved_display'
    )
    list_filter = ('error_type', 'is_resolved', 'occurred_at')
    search_fields = (
        'error_message',
        'url',
        'listing__product__name',
        'scraper_run__store__name'
    )
    readonly_fields = ('occurred_at',)
    date_hierarchy = 'occurred_at'
    
    fieldsets = (
        ('Información del Error', {
            'fields': ('scraper_run', 'listing', 'error_type')
        }),
        ('Detalles', {
            'fields': ('error_message', 'url', 'occurred_at')
        }),
        ('Stack Trace', {
            'fields': ('stack_trace',),
            'classes': ('collapse',)
        }),
        ('Resolución', {
            'fields': ('is_resolved', 'resolution_notes')
        }),
    )
    
    def get_queryset(self, request: HttpRequest) -> QuerySet[ScraperError]:
        """
        Optimiza el queryset con select_related.
        
        Args:
            request: HttpRequest del admin
        
        Returns:
            QuerySet optimizado
        """
        qs = super().get_queryset(request)
        return qs.select_related(
            'scraper_run__store',
            'listing__product'
        )
    
    def error_type_display(self, obj: ScraperError) -> str:
        """
        Muestra el tipo de error con color.
        
        Args:
            obj: Instancia de ScraperError
        
        Returns:
            HTML con tipo de error coloreado
        """
        colors = {
            'CONNECTION': 'red',
            'TIMEOUT': 'orange',
            'PARSE': 'blue',
            'VALIDATION': 'purple',
            'NOT_FOUND': 'gray',
            'OTHER': 'black',
        }
        color = colors.get(obj.error_type, 'black')
        return format_html(
            '<span style="color: {};">{}</span>',
            color,
            obj.get_error_type_display()
        )
    error_type_display.short_description = 'Tipo'
    
    def get_listing(self, obj: ScraperError) -> str:
        """
        Retorna el nombre del producto del listing.
        
        Args:
            obj: Instancia de ScraperError
        
        Returns:
            Nombre del producto o guión
        """
        if obj.listing:
            return obj.listing.product.name
        return '-'
    get_listing.short_description = 'Producto'
    
    def is_resolved_display(self, obj: ScraperError) -> str:
        """
        Muestra el estado de resolución con ícono.
        
        Args:
            obj: Instancia de ScraperError
        
        Returns:
            HTML con estado de resolución
        """
        if obj.is_resolved:
            return format_html(
                '<span style="color: green;">✓ Resuelto</span>'
            )
        return format_html(
            '<span style="color: red;">✗ Pendiente</span>'
        )
    is_resolved_display.short_description = 'Estado'
    
    actions = ['mark_resolved', 'mark_unresolved']
    
    def mark_resolved(
        self,
        request: HttpRequest,
        queryset: QuerySet[ScraperError]
    ) -> None:
        """
        Acción para marcar errores como resueltos.
        
        Args:
            request: HttpRequest del admin
            queryset: QuerySet de errores seleccionados
        """
        updated = queryset.update(is_resolved=True)
        self.message_user(request, f'{updated} error(es) marcado(s) como resuelto(s)')
    mark_resolved.short_description = 'Marcar como resueltos'
    
    def mark_unresolved(
        self,
        request: HttpRequest,
        queryset: QuerySet[ScraperError]
    ) -> None:
        """
        Acción para marcar errores como no resueltos.
        
        Args:
            request: HttpRequest del admin
            queryset: QuerySet de errores seleccionados
        """
        updated = queryset.update(is_resolved=False)
        self.message_user(request, f'{updated} error(es) marcado(s) como no resuelto(s)')
    mark_unresolved.short_description = 'Marcar como no resueltos'