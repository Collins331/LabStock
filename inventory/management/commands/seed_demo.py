"""Seed a small diagnostic lab with meaningful dummy inventory."""

from datetime import timedelta
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.utils import timezone

from inventory.models import (
    Item,
    Location,
    Membership,
    Organization,
    Supplier,
)
from inventory import services


class Command(BaseCommand):
    help = "Seed LabStock demo data for a small diagnostic laboratory."

    def handle(self, *args, **options):
        User = get_user_model()
        today = timezone.localdate()

        org, _ = Organization.objects.get_or_create(
            slug="ridgeway-diagnostics",
            defaults={
                "name": "Ridgeway Diagnostics",
                "expiry_warning_days": 30,
            },
        )
        # Second tenant for multi-tenant demo
        other, _ = Organization.objects.get_or_create(
            slug="lakeview-pathlab",
            defaults={
                "name": "Lakeview PathLab",
                "expiry_warning_days": 21,
            },
        )

        def user(username, full_name, password="labstockdemo"):
            u, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "first_name": full_name.split()[0],
                    "last_name": " ".join(full_name.split()[1:]),
                    "is_staff": username == "admin",
                },
            )
            if created or not u.check_password(password):
                u.set_password(password)
                u.save()
            return u

        admin = user("admin", "Amina Okello")
        admin.is_staff = True
        admin.is_superuser = True
        admin.save()
        store = user("storekeeper", "Brian Wanjiru")
        tech = user("tech", "Faith Njeri")
        viewer = user("viewer", "Grace Mutiso")

        for u, role in [
            (admin, Membership.Role.ADMIN),
            (store, Membership.Role.STOREKEEPER),
            (tech, Membership.Role.TECHNICIAN),
            (viewer, Membership.Role.VIEWER),
        ]:
            Membership.objects.get_or_create(
                user=u,
                organization=org,
                defaults={"role": role},
            )

        # Admin also sees second tenant (proves isolation)
        Membership.objects.get_or_create(
            user=admin,
            organization=other,
            defaults={"role": Membership.Role.ADMIN},
        )

        cold, _ = Location.objects.get_or_create(
            organization=org,
            name="Cold room 2–8°C",
            defaults={"code": "CR-01", "description": "Main reagent fridge"},
        )
        ambient, _ = Location.objects.get_or_create(
            organization=org,
            name="Ambient store",
            defaults={"code": "ST-01", "description": "Dry consumables"},
        )
        bench, _ = Location.objects.get_or_create(
            organization=org,
            name="Chemistry bench",
            defaults={"code": "BN-CHEM", "description": "Opened reagents in use"},
        )

        # Minimal stock for second org
        other_loc, _ = Location.objects.get_or_create(
            organization=other,
            name="Main store",
            defaults={"code": "MS-01"},
        )

        supplier_a, _ = Supplier.objects.get_or_create(
            organization=org,
            name="MedSupply East Africa",
            defaults={
                "contact_name": "Joyce Kariuki",
                "phone": "+254700111222",
                "lead_time_days": 5,
            },
        )
        supplier_b, _ = Supplier.objects.get_or_create(
            organization=org,
            name="LabCare Distributors",
            defaults={
                "contact_name": "Peter Otieno",
                "phone": "+254711333444",
                "lead_time_days": 10,
            },
        )

        catalog = [
            {
                "name": "Glucose reagent kit",
                "sku": "GLU-400",
                "category": Item.Category.REAGENT,
                "unit": "kit",
                "minimum_level": Decimal("2"),
                "location": cold,
                "supplier": supplier_a,
                "open_days": 30,
                "open_source": "Manufacturer IFU §4.2",
            },
            {
                "name": "ALT/GPT reagent",
                "sku": "ALT-200",
                "category": Item.Category.REAGENT,
                "unit": "kit",
                "minimum_level": Decimal("1"),
                "location": cold,
                "supplier": supplier_a,
                "open_days": 28,
                "open_source": "Manufacturer IFU; Lab SOP CHEM-07",
            },
            {
                "name": "HIV Ag/Ab combo control",
                "sku": "HIV-CTL",
                "category": Item.Category.CONTROL,
                "unit": "vial",
                "minimum_level": Decimal("4"),
                "location": cold,
                "supplier": supplier_b,
                "open_days": 7,
                "open_source": "Package insert — 7 days at 2–8°C after opening",
            },
            {
                "name": "Chemistry calibrator set",
                "sku": "CAL-SET",
                "category": Item.Category.CALIBRATOR,
                "unit": "set",
                "minimum_level": Decimal("1"),
                "location": cold,
                "supplier": supplier_a,
                "open_days": 14,
                "open_source": "Manufacturer IFU",
            },
            {
                "name": "EDTA vacutainer (purple)",
                "sku": "TUBE-EDTA",
                "category": Item.Category.CONSUMABLE,
                "unit": "pack",
                "minimum_level": Decimal("10"),
                "location": ambient,
                "supplier": supplier_b,
                "open_days": None,
                "open_source": "",
            },
            {
                "name": "Pipette tips 1000µL",
                "sku": "TIP-1K",
                "category": Item.Category.CONSUMABLE,
                "unit": "box",
                "minimum_level": Decimal("5"),
                "location": ambient,
                "supplier": supplier_b,
                "open_days": None,
                "open_source": "",
            },
            {
                "name": "Creatinine reagent",
                "sku": "CREA-100",
                "category": Item.Category.REAGENT,
                "unit": "kit",
                "minimum_level": Decimal("2"),
                "location": cold,
                "supplier": supplier_a,
                "open_days": 21,
                "open_source": "Lab SOP CHEM-07 (IFU: 30d; lab chooses 21d)",
            },
        ]

        items = {}
        for row in catalog:
            item, _ = Item.objects.update_or_create(
                organization=org,
                name=row["name"],
                defaults={
                    "sku": row["sku"],
                    "category": row["category"],
                    "unit": row["unit"],
                    "minimum_level": row["minimum_level"],
                    "default_location": row["location"],
                    "preferred_supplier": row["supplier"],
                    "open_expiry_days": row["open_days"],
                    "open_expiry_rule_source": row["open_source"],
                    "is_active": True,
                },
            )
            items[row["sku"]] = item

        # Clear demo movements/lots if re-seeding heavily would duplicate —
        # only receive when lot does not already have stock from seed.
        if org.lots.exists():
            self.stdout.write(self.style.WARNING("Lots already present — skipping stock receipts."))
        else:
            receipts = [
                ("GLU-400", "G24-1188", cold, Decimal("4"), today + timedelta(days=120), store),
                ("GLU-400", "G23-9901", cold, Decimal("1"), today + timedelta(days=12), store),
                ("ALT-200", "A25-044", cold, Decimal("2"), today + timedelta(days=90), store),
                ("HIV-CTL", "H24-771", cold, Decimal("6"), today + timedelta(days=45), store),
                ("CAL-SET", "C25-012", cold, Decimal("1"), today + timedelta(days=60), store),
                ("TUBE-EDTA", "E26-301", ambient, Decimal("8"), today + timedelta(days=400), store),
                ("TIP-1K", "T26-088", ambient, Decimal("3"), today + timedelta(days=500), store),
                ("CREA-100", "CR24-55", cold, Decimal("1"), today + timedelta(days=25), store),
            ]
            for sku, lot_no, loc, qty, exp, who in receipts:
                services.receive_stock(
                    organization=org,
                    item=items[sku],
                    lot_number=lot_no,
                    location=loc,
                    quantity=qty,
                    manufacturer_expiry=exp,
                    user=who,
                    supplier=items[sku].preferred_supplier,
                    reason="Opening stock / supplier delivery",
                    reference=f"GRN-{lot_no}",
                )

            # Open two containers from same HIV control lot on different dates
            hiv_lot = org.lots.get(item=items["HIV-CTL"], lot_number="H24-771")
            services.open_container(
                organization=org,
                lot=hiv_lot,
                quantity=Decimal("1"),
                container_label="Vial A",
                user=tech,
                opened_on=today - timedelta(days=5),
                notes="Opened for morning QC",
            )
            # Move remaining sealed? open second with different date
            hiv_lot.refresh_from_db()
            services.open_container(
                organization=org,
                lot=hiv_lot,
                quantity=Decimal("1"),
                container_label="Vial B",
                user=tech,
                opened_on=today - timedelta(days=1),
                notes="Opened for afternoon run",
            )

            # Issue some stock (usage)
            glu_lot = org.lots.get(item=items["GLU-400"], lot_number="G24-1188")
            services.issue_stock(
                organization=org,
                item=items["GLU-400"],
                quantity=Decimal("1"),
                user=tech,
                lot=glu_lot,
                reason="Issued to chemistry analyser",
            )

            # Tips below minimum already (3 < 5); issue tubes further below
            tube_lot = org.lots.get(item=items["TUBE-EDTA"], lot_number="E26-301")
            services.issue_stock(
                organization=org,
                item=items["TUBE-EDTA"],
                quantity=Decimal("2"),
                user=store,
                lot=tube_lot,
                reason="Phlebotomy restock",
            )

            # Dispose expired-ish glucose short-dated unit partially
            short_glu = org.lots.get(item=items["GLU-400"], lot_number="G23-9901")
            services.dispose_stock(
                organization=org,
                item=items["GLU-400"],
                quantity=Decimal("0.5"),
                user=store,
                lot=short_glu,
                reason="Suspected cold-chain excursion — quarantine disposal",
            )

            # Adjustment example (count correction)
            tip_lot = org.lots.get(item=items["TIP-1K"], lot_number="T26-088")
            services.adjust_stock(
                organization=org,
                item=items["TIP-1K"],
                quantity_delta=Decimal("-1"),
                user=store,
                reason="Physical count short — box damaged",
                lot=tip_lot,
            )

        # Tiny stock for second tenant
        if not other.items.exists():
            other_item = Item.objects.create(
                organization=other,
                name="Malaria RDT",
                sku="MLR-RDT",
                category=Item.Category.CONSUMABLE,
                unit="kit",
                minimum_level=Decimal("20"),
                default_location=other_loc,
            )
            services.receive_stock(
                organization=other,
                item=other_item,
                lot_number="LV-100",
                location=other_loc,
                quantity=Decimal("40"),
                manufacturer_expiry=today + timedelta(days=180),
                user=admin,
                reason="Opening stock",
            )

        self.stdout.write(self.style.SUCCESS("Demo data ready."))
        self.stdout.write("  Org: Ridgeway Diagnostics (+ Lakeview PathLab for admin)")
        self.stdout.write("  Logins (password labstockdemo): admin, storekeeper, tech, viewer")
