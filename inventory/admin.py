from django.contrib import admin

from . import models


@admin.register(models.Organization)
class OrganizationAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "expiry_warning_days", "created_at")
    prepopulated_fields = {"slug": ("name",)}


@admin.register(models.Membership)
class MembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "organization", "role", "is_active")
    list_filter = ("role", "organization")


@admin.register(models.Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "organization", "is_active")
    list_filter = ("organization",)


@admin.register(models.Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ("name", "organization", "lead_time_days", "phone")
    list_filter = ("organization",)


@admin.register(models.Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "category",
        "unit",
        "minimum_level",
        "organization",
        "is_active",
    )
    list_filter = ("category", "organization", "is_active")
    search_fields = ("name", "sku")


@admin.register(models.Lot)
class LotAdmin(admin.ModelAdmin):
    list_display = (
        "lot_number",
        "item",
        "location",
        "quantity_on_hand",
        "manufacturer_expiry",
        "organization",
    )
    list_filter = ("organization", "location")


@admin.register(models.OpenedContainer)
class OpenedContainerAdmin(admin.ModelAdmin):
    list_display = (
        "container_label",
        "item",
        "lot",
        "quantity_remaining",
        "opened_on",
        "effective_expiry",
        "expiry_rule_source",
    )
    list_filter = ("organization",)


@admin.register(models.StockMovement)
class StockMovementAdmin(admin.ModelAdmin):
    list_display = (
        "occurred_at",
        "movement_type",
        "item",
        "quantity",
        "reason",
        "performed_by",
        "organization",
    )
    list_filter = ("movement_type", "organization")
    readonly_fields = ("created_at",)


class StockCountLineInline(admin.TabularInline):
    model = models.StockCountLine
    extra = 0


@admin.register(models.StockCount)
class StockCountAdmin(admin.ModelAdmin):
    list_display = ("counted_on", "location", "status", "counted_by", "organization")
    list_filter = ("status", "organization")
    inlines = [StockCountLineInline]
