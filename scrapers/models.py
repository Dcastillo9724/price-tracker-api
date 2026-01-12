"""
Modelos para gestión de ejecuciones y errores de scraping.

Este módulo maneja el registro y seguimiento de las ejecuciones de scraping,
incluyendo métricas de rendimiento y tracking de errores.

Estructura:
    - ScraperRun: Registro de cada ejecución de scraping
    - ScraperError: Registro de errores ocurridos durante el scraping
"""

from typing import Optional

from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from products.models import ProductListing, Store


class ScraperRun(models.Model):
    """
    Registro de ejecución de scraping.
    
    Almacena información sobre cada ejecución de scraping incluyendo
    métricas de rendimiento, tiempo de ejecución y estado.
    
    Attributes:
        store: Tienda que fue scrapeada
        status: Estado actual de la ejecución
        trigger_type: Cómo se inició el scraping
        started_at: Momento de inicio de la ejecución
        finished_at: Momento de finalización
        execution_time: Duración total de la ejecución
        products_scraped: Total de productos procesados
        products_updated: Productos actualizados
        products_created: Productos nuevos creados
        errors_count: Número de errores encontrados
        task_id: ID de la tarea de Celery (si aplica)
        notes: Notas adicionales sobre la ejecución
    
    Examples:
        >>> run = ScraperRun.objects.create(store=ml_store)
        >>> run.mark_as_running()
        >>> # ... proceso de scraping ...
        >>> run.products_scraped = 100
        >>> run.mark_as_completed()
        >>> print(run.get_success_rate())
        100.0
    """
    
    class Status(models.TextChoices):
        """Estados posibles de una ejecución de scraping."""
        PENDING = 'PENDING', 'Pendiente'
        RUNNING = 'RUNNING', 'En ejecución'
        COMPLETED = 'COMPLETED', 'Completado'
        FAILED = 'FAILED', 'Fallido'
        PARTIAL = 'PARTIAL', 'Parcial'
    
    class TriggerType(models.TextChoices):
        """Tipos de trigger que inician el scraping."""
        MANUAL = 'MANUAL', 'Manual'
        SCHEDULED = 'SCHEDULED', 'Programado'
        API = 'API', 'API'
    
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='scraper_runs',
        verbose_name='tienda',
        help_text='Tienda que fue scrapeada'
    )
    status = models.CharField(
        'estado',
        max_length=20,
        choices=Status.choices,
        default=Status.PENDING,
        db_index=True,
        help_text='Estado actual de la ejecución'
    )
    trigger_type = models.CharField(
        'tipo',
        max_length=20,
        choices=TriggerType.choices,
        default=TriggerType.MANUAL,
        help_text='Cómo se inició el scraping'
    )
    started_at = models.DateTimeField(
        'inicio',
        default=timezone.now,
        db_index=True,
        help_text='Momento de inicio de la ejecución'
    )
    finished_at = models.DateTimeField(
        'fin',
        null=True,
        blank=True,
        help_text='Momento de finalización'
    )
    execution_time = models.DurationField(
        'duración',
        null=True,
        blank=True,
        help_text='Duración total de la ejecución'
    )
    products_scraped = models.PositiveIntegerField(
        'scrapeados',
        default=0,
        help_text='Total de productos procesados'
    )
    products_updated = models.PositiveIntegerField(
        'actualizados',
        default=0,
        help_text='Productos actualizados'
    )
    products_created = models.PositiveIntegerField(
        'creados',
        default=0,
        help_text='Productos nuevos creados'
    )
    errors_count = models.PositiveIntegerField(
        'errores',
        default=0,
        help_text='Número de errores encontrados'
    )
    task_id = models.CharField(
        'ID tarea',
        max_length=255,
        blank=True,
        help_text='ID de la tarea de Celery'
    )
    notes = models.TextField(
        'notas',
        blank=True,
        help_text='Notas adicionales sobre la ejecución'
    )
    
    class Meta:
        db_table = 'scraper_run'
        verbose_name = 'ejecución'
        verbose_name_plural = 'ejecuciones'
        ordering = ['-started_at']
        indexes = [
            models.Index(fields=['store', '-started_at']),
            models.Index(fields=['status', '-started_at']),
            models.Index(fields=['trigger_type']),
        ]
    
    def __str__(self) -> str:
        """Retorna representación con tienda, estado y fecha."""
        return (
            f"{self.store.name} - {self.status} "
            f"({self.started_at.strftime('%Y-%m-%d %H:%M')})"
        )
    
    def mark_as_running(self) -> None:
        """
        Marca la ejecución como en progreso.
        
        Actualiza el estado a RUNNING y registra el tiempo de inicio.
        """
        self.status = self.Status.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])
    
    def mark_as_completed(self) -> None:
        """
        Marca la ejecución como completada exitosamente.
        
        Calcula el tiempo de ejecución y actualiza el estado a COMPLETED.
        """
        self.status = self.Status.COMPLETED
        self.finished_at = timezone.now()
        self.execution_time = self.finished_at - self.started_at
        self.save(update_fields=['status', 'finished_at', 'execution_time'])
    
    def mark_as_partial(self) -> None:
        """
        Marca la ejecución como parcialmente exitosa.
        
        Se usa cuando hubo errores pero el scraping no falló completamente.
        """
        self.status = self.Status.PARTIAL
        self.finished_at = timezone.now()
        self.execution_time = self.finished_at - self.started_at
        self.save(update_fields=['status', 'finished_at', 'execution_time'])
    
    def mark_as_failed(self, error_message: Optional[str] = None) -> None:
        """
        Marca la ejecución como fallida.
        
        Args:
            error_message: Mensaje de error opcional para agregar a las notas
        """
        self.status = self.Status.FAILED
        self.finished_at = timezone.now()
        self.execution_time = self.finished_at - self.started_at
        if error_message:
            self.notes = error_message
        self.save(update_fields=['status', 'finished_at', 'execution_time', 'notes'])
    
    def get_success_rate(self) -> float:
        """
        Calcula el porcentaje de éxito del scraping.
        
        Returns:
            Porcentaje de productos procesados sin errores (0-100)
        
        Examples:
            >>> run = ScraperRun(products_scraped=10, errors_count=2)
            >>> run.get_success_rate()
            80.0
        """
        if self.products_scraped == 0:
            return 0.0
        successful = self.products_scraped - self.errors_count
        return round((successful / self.products_scraped) * 100, 2)
    
    def get_duration_seconds(self) -> Optional[float]:
        """
        Retorna la duración en segundos.
        
        Returns:
            Duración en segundos o None si no ha finalizado
        """
        if self.execution_time:
            return self.execution_time.total_seconds()
        return None
    
    @property
    def is_running(self) -> bool:
        """Indica si la ejecución está en progreso."""
        return self.status == self.Status.RUNNING
    
    @property
    def is_completed(self) -> bool:
        """Indica si la ejecución completó exitosamente."""
        return self.status == self.Status.COMPLETED
    
    @property
    def has_errors(self) -> bool:
        """Indica si hubo errores durante la ejecución."""
        return self.errors_count > 0


class ScraperError(models.Model):
    """
    Registro de error durante scraping.
    
    Almacena información detallada sobre errores que ocurren
    durante el proceso de scraping para debugging y monitoreo.
    
    Attributes:
        scraper_run: Ejecución en la que ocurrió el error
        listing: ProductListing relacionado (si aplica)
        error_type: Tipo de error ocurrido
        error_message: Mensaje descriptivo del error
        stack_trace: Stack trace completo del error
        url: URL donde ocurrió el error
        occurred_at: Momento en que ocurrió el error
        is_resolved: Si el error ya fue resuelto
        resolution_notes: Notas sobre la resolución
    
    Examples:
        >>> error = ScraperError.objects.create(
        ...     scraper_run=run,
        ...     error_type=ScraperError.ErrorType.CONNECTION,
        ...     error_message='Timeout after 30s',
        ...     url='https://example.com/product'
        ... )
    """
    
    class ErrorType(models.TextChoices):
        """Tipos de errores que pueden ocurrir durante scraping."""
        CONNECTION = 'CONNECTION', 'Conexión'
        TIMEOUT = 'TIMEOUT', 'Timeout'
        PARSE = 'PARSE', 'Parseo'
        VALIDATION = 'VALIDATION', 'Validación'
        NOT_FOUND = 'NOT_FOUND', 'No encontrado'
        OTHER = 'OTHER', 'Otro'
    
    scraper_run = models.ForeignKey(
        ScraperRun,
        on_delete=models.CASCADE,
        related_name='errors',
        verbose_name='ejecución',
        help_text='Ejecución en la que ocurrió el error'
    )
    listing = models.ForeignKey(
        ProductListing,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='scraper_errors',
        verbose_name='listing',
        help_text='ProductListing relacionado'
    )
    error_type = models.CharField(
        'tipo',
        max_length=20,
        choices=ErrorType.choices,
        default=ErrorType.OTHER,
        db_index=True,
        help_text='Tipo de error ocurrido'
    )
    error_message = models.TextField(
        'mensaje',
        help_text='Mensaje descriptivo del error'
    )
    stack_trace = models.TextField(
        'stack',
        blank=True,
        help_text='Stack trace completo del error'
    )
    url = models.URLField(
        'URL',
        max_length=1000,
        blank=True,
        help_text='URL donde ocurrió el error'
    )
    occurred_at = models.DateTimeField(
        'fecha',
        default=timezone.now,
        db_index=True,
        help_text='Momento en que ocurrió el error'
    )
    is_resolved = models.BooleanField(
        'resuelto',
        default=False,
        help_text='Si el error ya fue resuelto'
    )
    resolution_notes = models.TextField(
        'notas de resolución',
        blank=True,
        help_text='Notas sobre cómo se resolvió el error'
    )
    
    class Meta:
        db_table = 'scraper_error'
        verbose_name = 'error'
        verbose_name_plural = 'errores'
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['scraper_run', '-occurred_at']),
            models.Index(fields=['error_type', 'is_resolved']),
            models.Index(fields=['is_resolved', '-occurred_at']),
        ]
    
    def __str__(self) -> str:
        """Retorna representación con tipo de error y tienda."""
        return f"{self.error_type} - {self.scraper_run.store.name}"
    
    def mark_as_resolved(self, notes: str = '') -> None:
        """
        Marca el error como resuelto.
        
        Args:
            notes: Notas sobre cómo se resolvió el error
        """
        self.is_resolved = True
        if notes:
            self.resolution_notes = notes
        self.save(update_fields=['is_resolved', 'resolution_notes'])
    
    @property
    def age_hours(self) -> float:
        """
        Retorna la antigüedad del error en horas.
        
        Returns:
            Horas desde que ocurrió el error
        """
        delta = timezone.now() - self.occurred_at
        return delta.total_seconds() / 3600