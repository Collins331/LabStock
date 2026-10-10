"""Stock ledger operations. All balance changes go through recorded movements."""

from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from .models import Lot, OpenedContainer, StockCount, StockMovement


class StockError(Exception):
    pass


@transaction.atomic
def receive_stock(
    *,
    organization,
    item,
    lot_number,
    location,
    quantity,
    manufacturer_expiry,
    user,
    supplier=None,
    unit_cost=None,
    reason="Goods received",
    reference="",
    notes="",
):
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise StockError("Receipt quantity must be positive.")

    lot, created = Lot.objects.select_for_update().get_or_create(
        organization=organization,
        item=item,
        lot_number=lot_number,
        location=location,
        defaults={
            "supplier": supplier,
            "manufacturer_expiry": manufacturer_expiry,
            "quantity_on_hand": Decimal("0"),
            "unit_cost": unit_cost,
            "received_at": timezone.localdate(),
        },
    )
    if not created:
        if lot.manufacturer_expiry != manufacturer_expiry:
            raise StockError(
                "Existing lot has a different manufacturer expiry. "
                "Use a distinct lot/location or adjust carefully."
            )
        lot.supplier = supplier or lot.supplier
        if unit_cost is not None:
            lot.unit_cost = unit_cost

    lot.quantity_on_hand += quantity
    lot.is_active = True
    lot.save()

    return StockMovement.objects.create(
        organization=organization,
        item=item,
        lot=lot,
        movement_type=StockMovement.MovementType.RECEIPT,
        quantity=quantity,
        reason=reason,
        to_location=location,
        performed_by=user,
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def issue_stock(
    *,
    organization,
    item,
    quantity,
    user,
    lot=None,
    opened_container=None,
    reason="Issued to bench",
    from_location=None,
    reference="",
    notes="",
    movement_type=StockMovement.MovementType.ISSUE,
):
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise StockError("Issue quantity must be positive.")

    if opened_container is not None:
        container = OpenedContainer.objects.select_for_update().get(pk=opened_container.pk)
        if container.organization_id != organization.id:
            raise StockError("Container belongs to another organization.")
        if container.quantity_remaining < quantity:
            raise StockError("Not enough quantity in opened container.")
        container.quantity_remaining -= quantity
        if container.quantity_remaining == 0:
            container.is_active = False
        container.save()
        return StockMovement.objects.create(
            organization=organization,
            item=item,
            lot=container.lot,
            opened_container=container,
            movement_type=movement_type,
            quantity=-quantity,
            reason=reason,
            from_location=container.location,
            performed_by=user,
            reference=reference,
            notes=notes,
        )

    if lot is None:
        raise StockError("Select a lot or opened container.")

    lot = Lot.objects.select_for_update().get(pk=lot.pk)
    if lot.organization_id != organization.id:
        raise StockError("Lot belongs to another organization.")
    if lot.quantity_on_hand < quantity:
        raise StockError("Not enough quantity on this lot.")
    lot.quantity_on_hand -= quantity
    if lot.quantity_on_hand == 0:
        lot.is_active = False
    lot.save()

    return StockMovement.objects.create(
        organization=organization,
        item=item,
        lot=lot,
        movement_type=movement_type,
        quantity=-quantity,
        reason=reason,
        from_location=from_location or lot.location,
        performed_by=user,
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def adjust_stock(
    *,
    organization,
    item,
    quantity_delta,
    user,
    reason,
    lot=None,
    opened_container=None,
    notes="",
    reference="",
):
    """Record a signed adjustment. Positive increases stock; negative decreases."""
    quantity_delta = Decimal(quantity_delta)
    if quantity_delta == 0:
        raise StockError("Adjustment quantity cannot be zero.")
    if not reason:
        raise StockError("Adjustment reason is required.")

    if opened_container is not None:
        container = OpenedContainer.objects.select_for_update().get(pk=opened_container.pk)
        new_qty = container.quantity_remaining + quantity_delta
        if new_qty < 0:
            raise StockError("Adjustment would make container quantity negative.")
        container.quantity_remaining = new_qty
        container.is_active = new_qty > 0
        container.save()
        return StockMovement.objects.create(
            organization=organization,
            item=item,
            lot=container.lot,
            opened_container=container,
            movement_type=StockMovement.MovementType.ADJUSTMENT,
            quantity=quantity_delta,
            reason=reason,
            from_location=container.location if quantity_delta < 0 else None,
            to_location=container.location if quantity_delta > 0 else None,
            performed_by=user,
            reference=reference,
            notes=notes,
        )

    if lot is None:
        raise StockError("Select a lot or opened container.")

    lot = Lot.objects.select_for_update().get(pk=lot.pk)
    new_qty = lot.quantity_on_hand + quantity_delta
    if new_qty < 0:
        raise StockError("Adjustment would make lot quantity negative.")
    lot.quantity_on_hand = new_qty
    lot.is_active = new_qty > 0
    lot.save()

    return StockMovement.objects.create(
        organization=organization,
        item=item,
        lot=lot,
        movement_type=StockMovement.MovementType.ADJUSTMENT,
        quantity=quantity_delta,
        reason=reason,
        from_location=lot.location if quantity_delta < 0 else None,
        to_location=lot.location if quantity_delta > 0 else None,
        performed_by=user,
        reference=reference,
        notes=notes,
    )


@transaction.atomic
def open_container(
    *,
    organization,
    lot,
    quantity,
    container_label,
    user,
    opened_on=None,
    expiry_rule_days=None,
    expiry_rule_source="",
    notes="",
):
    """
    Move quantity from a sealed lot into an individually tracked opened container.
    """
    quantity = Decimal(quantity)
    if quantity <= 0:
        raise StockError("Open quantity must be positive.")

    lot = Lot.objects.select_for_update().get(pk=lot.pk)
    if lot.organization_id != organization.id:
        raise StockError("Lot belongs to another organization.")
    if lot.quantity_on_hand < quantity:
        raise StockError("Not enough sealed stock to open.")

    item = lot.item
    opened_on = opened_on or timezone.localdate()
    rule_days = expiry_rule_days if expiry_rule_days is not None else item.open_expiry_days
    if rule_days is None:
        raise StockError(
            "Set an open-expiry rule (days) for this item or provide one when opening."
        )
    source = expiry_rule_source or item.open_expiry_rule_source or "Not specified"
    # Effective expiry is the earlier of manufacturer expiry and open+rule
    open_expiry = opened_on + timedelta(days=int(rule_days))
    effective = min(open_expiry, lot.manufacturer_expiry)

    lot.quantity_on_hand -= quantity
    if lot.quantity_on_hand == 0:
        lot.is_active = False
    lot.save()

    container = OpenedContainer.objects.create(
        organization=organization,
        item=item,
        lot=lot,
        location=lot.location,
        container_label=container_label,
        opened_on=opened_on,
        quantity_remaining=quantity,
        effective_expiry=effective,
        expiry_rule_days=int(rule_days),
        expiry_rule_source=source,
        opened_by=user,
        notes=notes,
    )

    StockMovement.objects.create(
        organization=organization,
        item=item,
        lot=lot,
        opened_container=container,
        movement_type=StockMovement.MovementType.OPEN,
        quantity=Decimal("0"),  # net stock unchanged; sealed → opened
        reason=f"Opened container {container_label}",
        from_location=lot.location,
        to_location=lot.location,
        performed_by=user,
        notes=notes,
    )
    return container


@transaction.atomic
def dispose_stock(
    *,
    organization,
    item,
    quantity,
    user,
    reason,
    lot=None,
    opened_container=None,
    notes="",
):
    return issue_stock(
        organization=organization,
        item=item,
        quantity=quantity,
        user=user,
        lot=lot,
        opened_container=opened_container,
        reason=reason,
        notes=notes,
        movement_type=StockMovement.MovementType.DISPOSAL,
    )


@transaction.atomic
def post_stock_count(*, stock_count: StockCount, user):
    if stock_count.status == StockCount.Status.POSTED:
        raise StockError("This count is already posted.")

    for line in stock_count.lines.select_related("item", "lot"):
        variance = line.counted_quantity - line.system_quantity
        if variance == 0:
            continue
        reason = line.variance_reason or f"Stock count {stock_count.counted_on}"
        # Ledger correction via adjustment (traceable); count id in reference
        movement = adjust_stock(
            organization=stock_count.organization,
            item=line.item,
            quantity_delta=variance,
            user=user,
            reason=reason,
            lot=line.lot,
            notes=f"Posted from stock count #{stock_count.pk}",
            reference=f"COUNT-{stock_count.pk}",
        )
        movement.movement_type = StockMovement.MovementType.COUNT
        movement.save(update_fields=["movement_type"])

    stock_count.status = StockCount.Status.POSTED
    stock_count.posted_at = timezone.now()
    stock_count.counted_by = user
    stock_count.save()
    return stock_count
