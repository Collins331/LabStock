from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Organization(models.Model):
    """Customer account / lab tenant. All inventory is scoped here."""

    name = models.CharField(max_length=200)
    slug = models.SlugField(unique=True)
    expiry_warning_days = models.PositiveIntegerField(
        default=30,
        help_text="Days before expiry to show on the dashboard.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class Membership(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Admin"
        STOREKEEPER = "storekeeper", "Storekeeper"
        TECHNICIAN = "technician", "Technician"
        VIEWER = "viewer", "Viewer"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    organization = models.ForeignKey(
        Organization,
        on_delete=models.CASCADE,
        related_name="memberships",
    )
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.TECHNICIAN)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("user", "organization")]
        ordering = ["organization__name", "user__username"]

    def __str__(self):
        return f"{self.user} @ {self.organization} ({self.role})"

    @property
    def can_write(self):
        return self.role in {
            self.Role.ADMIN,
            self.Role.STOREKEEPER,
            self.Role.TECHNICIAN,
        }

    @property
    def can_manage(self):
        return self.role in {self.Role.ADMIN, self.Role.STOREKEEPER}


class Location(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="locations"
    )
    name = models.CharField(max_length=120)
    code = models.CharField(max_length=40, blank=True)
    description = models.CharField(max_length=255, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name


class Supplier(models.Model):
    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="suppliers"
    )
    name = models.CharField(max_length=200)
    contact_name = models.CharField(max_length=120, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    lead_time_days = models.PositiveIntegerField(default=7)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name


class Item(models.Model):
    class Category(models.TextChoices):
        REAGENT = "reagent", "Reagent"
        CONTROL = "control", "Control"
        CALIBRATOR = "calibrator", "Calibrator"
        CONSUMABLE = "consumable", "Consumable"
        OTHER = "other", "Other"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="items"
    )
    name = models.CharField(max_length=200)
    sku = models.CharField(max_length=60, blank=True)
    category = models.CharField(
        max_length=20, choices=Category.choices, default=Category.REAGENT
    )
    unit = models.CharField(max_length=40, help_text="e.g. kit, bottle, pack, ml")
    minimum_level = models.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal("0")
    )
    default_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="default_items",
    )
    preferred_supplier = models.ForeignKey(
        Supplier,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="items",
    )
    # Default opened-container expiry rule for this item
    open_expiry_days = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text="Days until expiry after opening, if applicable.",
    )
    open_expiry_rule_source = models.CharField(
        max_length=255,
        blank=True,
        help_text="e.g. Manufacturer IFU, Lab SOP INV-12",
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        unique_together = [("organization", "name")]

    def __str__(self):
        return self.name

    def on_hand_quantity(self):
        sealed = (
            self.lots.filter(is_active=True).aggregate(total=Sum("quantity_on_hand"))[
                "total"
            ]
            or Decimal("0")
        )
        opened = (
            self.opened_containers.filter(is_active=True, quantity_remaining__gt=0).aggregate(
                total=Sum("quantity_remaining")
            )["total"]
            or Decimal("0")
        )
        return sealed + opened

    def is_below_minimum(self):
        return self.on_hand_quantity() < self.minimum_level


class Lot(models.Model):
    """Unopened / bulk lot at a location. Opened bottles become OpenedContainer rows."""

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="lots"
    )
    item = models.ForeignKey(Item, on_delete=models.CASCADE, related_name="lots")
    lot_number = models.CharField(max_length=80)
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="lots"
    )
    supplier = models.ForeignKey(
        Supplier, on_delete=models.SET_NULL, null=True, blank=True, related_name="lots"
    )
    manufacturer_expiry = models.DateField()
    received_at = models.DateField(default=timezone.localdate)
    quantity_on_hand = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=Decimal("0"),
        validators=[MinValueValidator(Decimal("0"))],
    )
    unit_cost = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["manufacturer_expiry", "lot_number"]
        unique_together = [("organization", "item", "lot_number", "location")]

    def __str__(self):
        return f"{self.item.name} · {self.lot_number}"

    def days_until_expiry(self):
        return (self.manufacturer_expiry - timezone.localdate()).days


class OpenedContainer(models.Model):
    """
    Individually tracked opened container when expiry differs from the sealed lot.
    Stores the expiry rule and its source for auditability.
    """

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="opened_containers"
    )
    item = models.ForeignKey(
        Item, on_delete=models.CASCADE, related_name="opened_containers"
    )
    lot = models.ForeignKey(
        Lot, on_delete=models.PROTECT, related_name="opened_containers"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="opened_containers"
    )
    container_label = models.CharField(
        max_length=80,
        help_text="Short label, e.g. Bottle A / vial 2",
    )
    opened_on = models.DateField()
    quantity_remaining = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        validators=[MinValueValidator(Decimal("0"))],
    )
    # Computed / stored expiry after opening
    effective_expiry = models.DateField()
    expiry_rule_days = models.PositiveIntegerField(
        help_text="Days after opening used for this container."
    )
    expiry_rule_source = models.CharField(
        max_length=255,
        help_text="Where the rule came from (IFU, SOP, etc.).",
    )
    opened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="opened_containers",
    )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["effective_expiry", "container_label"]

    def __str__(self):
        return f"{self.item.name} · {self.container_label} ({self.lot.lot_number})"

    def days_until_expiry(self):
        return (self.effective_expiry - timezone.localdate()).days


class StockMovement(models.Model):
    """Append-only stock ledger. Corrections are new adjustment rows."""

    class MovementType(models.TextChoices):
        RECEIPT = "receipt", "Receipt"
        ISSUE = "issue", "Issue / use"
        TRANSFER = "transfer", "Transfer"
        ADJUSTMENT = "adjustment", "Adjustment"
        DISPOSAL = "disposal", "Disposal"
        OPEN = "open", "Open container"
        COUNT = "count", "Stock count"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="movements"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="movements")
    lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True, related_name="movements"
    )
    opened_container = models.ForeignKey(
        OpenedContainer,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movements",
    )
    movement_type = models.CharField(max_length=20, choices=MovementType.choices)
    # Signed quantity relative to on-hand: positive increases stock, negative decreases
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=255)
    from_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movements_from",
    )
    to_location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="movements_to",
    )
    performed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_movements",
    )
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=80, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-occurred_at", "-id"]
        indexes = [
            models.Index(fields=["organization", "-occurred_at"]),
            models.Index(fields=["item", "-occurred_at"]),
        ]

    def __str__(self):
        sign = "+" if self.quantity >= 0 else ""
        return f"{self.get_movement_type_display()} {sign}{self.quantity} {self.item}"


class StockCount(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        POSTED = "posted", "Posted"

    organization = models.ForeignKey(
        Organization, on_delete=models.CASCADE, related_name="stock_counts"
    )
    location = models.ForeignKey(
        Location, on_delete=models.PROTECT, related_name="stock_counts"
    )
    counted_on = models.DateField(default=timezone.localdate)
    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.DRAFT
    )
    counted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="stock_counts",
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-counted_on", "-id"]

    def __str__(self):
        return f"Count {self.location} · {self.counted_on}"


class StockCountLine(models.Model):
    stock_count = models.ForeignKey(
        StockCount, on_delete=models.CASCADE, related_name="lines"
    )
    item = models.ForeignKey(Item, on_delete=models.PROTECT, related_name="count_lines")
    lot = models.ForeignKey(
        Lot, on_delete=models.SET_NULL, null=True, blank=True, related_name="count_lines"
    )
    system_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    counted_quantity = models.DecimalField(max_digits=12, decimal_places=2)
    variance_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["item__name"]

    @property
    def variance(self):
        return self.counted_quantity - self.system_quantity
