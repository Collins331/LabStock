from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.utils import timezone

from inventory.models import Item, Location, Membership, Organization, StockMovement
from inventory import services


class LedgerTests(TestCase):
    def setUp(self):
        self.org = Organization.objects.create(name="Test Lab", slug="test-lab")
        self.user = get_user_model().objects.create_user("u1", password="x")
        Membership.objects.create(
            user=self.user,
            organization=self.org,
            role=Membership.Role.STOREKEEPER,
        )
        self.loc = Location.objects.create(organization=self.org, name="Fridge")
        self.item = Item.objects.create(
            organization=self.org,
            name="Reagent A",
            unit="kit",
            minimum_level=Decimal("1"),
            open_expiry_days=7,
            open_expiry_rule_source="IFU",
            default_location=self.loc,
        )

    def test_receive_issue_and_open_keep_traceable_history(self):
        services.receive_stock(
            organization=self.org,
            item=self.item,
            lot_number="L1",
            location=self.loc,
            quantity=Decimal("3"),
            manufacturer_expiry=timezone.localdate() + timedelta(days=60),
            user=self.user,
        )
        lot = self.item.lots.get()
        self.assertEqual(lot.quantity_on_hand, Decimal("3"))

        container = services.open_container(
            organization=self.org,
            lot=lot,
            quantity=Decimal("1"),
            container_label="Bottle 1",
            user=self.user,
        )
        lot.refresh_from_db()
        self.assertEqual(lot.quantity_on_hand, Decimal("2"))
        self.assertEqual(container.expiry_rule_source, "IFU")
        self.assertEqual(container.expiry_rule_days, 7)

        services.issue_stock(
            organization=self.org,
            item=self.item,
            quantity=Decimal("0.5"),
            user=self.user,
            opened_container=container,
            reason="Bench use",
        )
        container.refresh_from_db()
        self.assertEqual(container.quantity_remaining, Decimal("0.5"))

        services.adjust_stock(
            organization=self.org,
            item=self.item,
            quantity_delta=Decimal("-0.5"),
            user=self.user,
            reason="Count correction",
            lot=lot,
        )
        types = list(
            StockMovement.objects.filter(organization=self.org).values_list(
                "movement_type", flat=True
            )
        )
        self.assertIn(StockMovement.MovementType.RECEIPT, types)
        self.assertIn(StockMovement.MovementType.OPEN, types)
        self.assertIn(StockMovement.MovementType.ISSUE, types)
        self.assertIn(StockMovement.MovementType.ADJUSTMENT, types)
        self.assertTrue(all(m.reason and m.performed_by_id for m in StockMovement.objects.all()))
