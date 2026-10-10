from datetime import timedelta
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView, LogoutView
from django.db.models import Q, Sum
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .forms import (
    AdjustmentForm,
    IssueForm,
    OpenContainerForm,
    ReceiveForm,
    StockCountForm,
    StyledAuthenticationForm,
)
from .models import (
    Item,
    Location,
    Lot,
    Membership,
    OpenedContainer,
    StockCount,
    StockCountLine,
    StockMovement,
)
from . import services


class LabLoginView(LoginView):
    template_name = "registration/login.html"
    authentication_form = StyledAuthenticationForm
    redirect_authenticated_user = True


class LabLogoutView(LogoutView):
    next_page = "login"


def _require_org(request):
    if not request.organization:
        raise Http404("No organization assigned to this user.")
    return request.organization


def _require_write(request):
    membership = request.membership
    if not membership or not membership.can_write:
        return False
    return True


@login_required
def switch_organization(request, org_id):
    membership = Membership.objects.filter(
        user=request.user, organization_id=org_id, is_active=True
    ).first()
    if not membership:
        return HttpResponseForbidden("Not a member of that organization.")
    request.session["active_organization_id"] = membership.organization_id
    messages.success(request, f"Switched to {membership.organization.name}")
    return redirect("dashboard")


@login_required
def dashboard(request):
    org = _require_org(request)
    today = timezone.localdate()
    warn_days = org.expiry_warning_days
    warn_until = today + timedelta(days=warn_days)

    items = list(Item.objects.filter(organization=org, is_active=True))
    reorder = [i for i in items if i.is_below_minimum()]

    expiring_lots = (
        Lot.objects.filter(
            organization=org,
            is_active=True,
            quantity_on_hand__gt=0,
            manufacturer_expiry__lte=warn_until,
        )
        .select_related("item", "location")
        .order_by("manufacturer_expiry")[:20]
    )
    expiring_opened = (
        OpenedContainer.objects.filter(
            organization=org,
            is_active=True,
            quantity_remaining__gt=0,
            effective_expiry__lte=warn_until,
        )
        .select_related("item", "lot", "location")
        .order_by("effective_expiry")[:20]
    )

    recent = (
        StockMovement.objects.filter(organization=org)
        .select_related("item", "performed_by")[:10]
    )

    expired_lots = sum(
        1 for lot in expiring_lots if lot.manufacturer_expiry < today
    )
    expired_opened = sum(
        1 for c in expiring_opened if c.effective_expiry < today
    )

    context = {
        "item_count": len(items),
        "lot_count": Lot.objects.filter(organization=org, is_active=True).count(),
        "opened_count": OpenedContainer.objects.filter(
            organization=org, is_active=True, quantity_remaining__gt=0
        ).count(),
        "reorder_items": reorder,
        "expiring_lots": expiring_lots,
        "expiring_opened": expiring_opened,
        "recent_movements": recent,
        "warn_days": warn_days,
        "expired_count": expired_lots + expired_opened,
        "today": today,
    }
    return render(request, "inventory/dashboard.html", context)


@login_required
def item_list(request):
    org = _require_org(request)
    q = request.GET.get("q", "").strip()
    items = Item.objects.filter(organization=org).select_related(
        "default_location", "preferred_supplier"
    )
    if q:
        items = items.filter(Q(name__icontains=q) | Q(sku__icontains=q))
    locations = Location.objects.filter(organization=org, is_active=True)
    enriched = []
    for item in items:
        on_hand = item.on_hand_quantity()
        enriched.append(
            {
                "item": item,
                "on_hand": on_hand,
                "below_min": on_hand < item.minimum_level,
            }
        )
    return render(
        request,
        "inventory/item_list.html",
        {"rows": enriched, "locations": locations, "q": q},
    )


@login_required
def item_detail(request, pk):
    org = _require_org(request)
    item = get_object_or_404(Item, pk=pk, organization=org)
    lots = item.lots.filter(is_active=True).select_related("location")
    opened = item.opened_containers.filter(
        is_active=True, quantity_remaining__gt=0
    ).select_related("lot", "location")
    movements = item.movements.select_related("performed_by")[:30]
    return render(
        request,
        "inventory/item_detail.html",
        {
            "item": item,
            "lots": lots,
            "opened": opened,
            "movements": movements,
            "on_hand": item.on_hand_quantity(),
        },
    )


@login_required
def location_list(request):
    org = _require_org(request)
    locations = Location.objects.filter(organization=org)
    rows = []
    for loc in locations:
        sealed = (
            Lot.objects.filter(location=loc, is_active=True).aggregate(
                t=Sum("quantity_on_hand")
            )["t"]
            or Decimal("0")
        )
        opened = (
            OpenedContainer.objects.filter(
                location=loc, is_active=True
            ).aggregate(t=Sum("quantity_remaining"))["t"]
            or Decimal("0")
        )
        rows.append({"location": loc, "quantity": sealed + opened})
    return render(request, "inventory/location_list.html", {"rows": rows})


@login_required
def lot_list(request):
    org = _require_org(request)
    lots = (
        Lot.objects.filter(organization=org)
        .select_related("item", "location", "supplier")
        .order_by("manufacturer_expiry")
    )
    show = request.GET.get("show", "active")
    if show == "active":
        lots = lots.filter(is_active=True, quantity_on_hand__gt=0)
    return render(
        request,
        "inventory/lot_list.html",
        {"lots": lots, "show": show, "today": timezone.localdate()},
    )


@login_required
def opened_list(request):
    org = _require_org(request)
    containers = (
        OpenedContainer.objects.filter(organization=org)
        .select_related("item", "lot", "location", "opened_by")
        .order_by("effective_expiry")
    )
    show = request.GET.get("show", "active")
    if show == "active":
        containers = containers.filter(is_active=True, quantity_remaining__gt=0)
    return render(
        request,
        "inventory/opened_list.html",
        {"containers": containers, "show": show, "today": timezone.localdate()},
    )


@login_required
@require_http_methods(["GET", "POST"])
def receive_stock(request):
    org = _require_org(request)
    if not _require_write(request):
        return HttpResponseForbidden("Read-only role.")
    form = ReceiveForm(org, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            movement = services.receive_stock(
                organization=org,
                item=form.cleaned_data["item"],
                lot_number=form.cleaned_data["lot_number"],
                location=form.cleaned_data["location"],
                quantity=form.cleaned_data["quantity"],
                manufacturer_expiry=form.cleaned_data["manufacturer_expiry"],
                user=request.user,
                reason=form.cleaned_data["reason"],
                reference=form.cleaned_data.get("reference") or "",
                notes=form.cleaned_data.get("notes") or "",
            )
            messages.success(
                request,
                f"Received {movement.quantity} {movement.item.unit} of {movement.item.name}.",
            )
            return redirect("lot_list")
        except services.StockError as exc:
            messages.error(request, str(exc))
    return render(request, "inventory/receive.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def issue_stock(request):
    org = _require_org(request)
    if not _require_write(request):
        return HttpResponseForbidden("Read-only role.")
    form = IssueForm(org, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            lot = form.cleaned_data.get("lot")
            opened = form.cleaned_data.get("opened_container")
            if form.cleaned_data["source_type"] == IssueForm.SOURCE_OPENED:
                lot = None
            else:
                opened = None
            item = (opened.item if opened else lot.item)
            movement = services.issue_stock(
                organization=org,
                item=item,
                quantity=form.cleaned_data["quantity"],
                user=request.user,
                lot=lot,
                opened_container=opened,
                reason=form.cleaned_data["reason"],
                notes=form.cleaned_data.get("notes") or "",
            )
            messages.success(
                request,
                f"Issued {abs(movement.quantity)} {item.unit} of {item.name}.",
            )
            return redirect("dashboard")
        except services.StockError as exc:
            messages.error(request, str(exc))
    return render(request, "inventory/issue.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def open_container(request):
    org = _require_org(request)
    if not _require_write(request):
        return HttpResponseForbidden("Read-only role.")
    initial = {"opened_on": timezone.localdate()}
    form = OpenContainerForm(org, request.POST or None, initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            container = services.open_container(
                organization=org,
                lot=form.cleaned_data["lot"],
                quantity=form.cleaned_data["quantity"],
                container_label=form.cleaned_data["container_label"],
                user=request.user,
                opened_on=form.cleaned_data["opened_on"],
                expiry_rule_days=form.cleaned_data.get("expiry_rule_days"),
                expiry_rule_source=form.cleaned_data.get("expiry_rule_source") or "",
                notes=form.cleaned_data.get("notes") or "",
            )
            messages.success(
                request,
                f"Opened {container.container_label}; expires {container.effective_expiry} "
                f"(rule: {container.expiry_rule_days}d from {container.expiry_rule_source}).",
            )
            return redirect("opened_list")
        except services.StockError as exc:
            messages.error(request, str(exc))
    return render(request, "inventory/open_container.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def adjust_stock(request):
    org = _require_org(request)
    if not _require_write(request):
        return HttpResponseForbidden("Read-only role.")
    form = AdjustmentForm(org, request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            lot = form.cleaned_data.get("lot")
            opened = form.cleaned_data.get("opened_container")
            if form.cleaned_data["source_type"] == AdjustmentForm.SOURCE_OPENED:
                lot = None
            else:
                opened = None
            item = (opened.item if opened else lot.item)
            movement = services.adjust_stock(
                organization=org,
                item=item,
                quantity_delta=form.cleaned_data["quantity_delta"],
                user=request.user,
                reason=form.cleaned_data["reason"],
                lot=lot,
                opened_container=opened,
                notes=form.cleaned_data.get("notes") or "",
            )
            messages.success(
                request,
                f"Adjustment recorded: {movement.quantity:+} {item.unit} ({movement.reason}).",
            )
            return redirect("movement_list")
        except services.StockError as exc:
            messages.error(request, str(exc))
    return render(request, "inventory/adjust.html", {"form": form})


@login_required
def count_list(request):
    org = _require_org(request)
    counts = StockCount.objects.filter(organization=org).select_related(
        "location", "counted_by"
    )
    return render(request, "inventory/count_list.html", {"counts": counts})


@login_required
@require_http_methods(["GET", "POST"])
def count_create(request):
    org = _require_org(request)
    if not _require_write(request):
        return HttpResponseForbidden("Read-only role.")
    form = StockCountForm(org, request.POST or None, initial={"counted_on": timezone.localdate()})
    if request.method == "POST" and form.is_valid():
        count = form.save(commit=False)
        count.organization = org
        count.counted_by = request.user
        count.save()
        # Prefill lines from lots at location
        lots = Lot.objects.filter(
            organization=org, location=count.location, quantity_on_hand__gt=0
        ).select_related("item")
        for lot in lots:
            StockCountLine.objects.create(
                stock_count=count,
                item=lot.item,
                lot=lot,
                system_quantity=lot.quantity_on_hand,
                counted_quantity=lot.quantity_on_hand,
            )
        messages.info(request, "Count created. Enter physical quantities, then post.")
        return redirect("count_detail", pk=count.pk)
    return render(request, "inventory/count_form.html", {"form": form})


@login_required
@require_http_methods(["GET", "POST"])
def count_detail(request, pk):
    org = _require_org(request)
    count = get_object_or_404(StockCount, pk=pk, organization=org)
    lines = count.lines.select_related("item", "lot")
    if request.method == "POST" and count.status == StockCount.Status.DRAFT:
        if not _require_write(request):
            return HttpResponseForbidden("Read-only role.")
        for line in lines:
            qty = request.POST.get(f"qty_{line.pk}")
            reason = request.POST.get(f"reason_{line.pk}", "")
            if qty is None or qty == "":
                continue
            line.counted_quantity = Decimal(qty)
            line.variance_reason = reason
            line.save()
        if "post" in request.POST:
            try:
                services.post_stock_count(stock_count=count, user=request.user)
                messages.success(request, "Stock count posted; ledger updated.")
                return redirect("count_detail", pk=count.pk)
            except services.StockError as exc:
                messages.error(request, str(exc))
        else:
            messages.success(request, "Count quantities saved.")
            return redirect("count_detail", pk=count.pk)
    return render(
        request,
        "inventory/count_detail.html",
        {"count": count, "lines": lines},
    )


@login_required
def movement_list(request):
    org = _require_org(request)
    movements = (
        StockMovement.objects.filter(organization=org)
        .select_related("item", "lot", "opened_container", "performed_by")
    )
    mtype = request.GET.get("type")
    if mtype:
        movements = movements.filter(movement_type=mtype)
    return render(
        request,
        "inventory/movement_list.html",
        {
            "movements": movements[:200],
            "types": StockMovement.MovementType.choices,
            "selected_type": mtype or "",
        },
    )


@login_required
def reports(request):
    org = _require_org(request)
    today = timezone.localdate()
    month_start = today.replace(day=1)

    usage_qs = (
        StockMovement.objects.filter(
            organization=org,
            movement_type=StockMovement.MovementType.ISSUE,
            occurred_at__date__gte=month_start,
        )
        .values("item__name", "item__unit")
        .annotate(total=Sum("quantity"))
        .order_by("item__name")
    )
    usage = [
        {
            "name": row["item__name"],
            "unit": row["item__unit"],
            "total": abs(row["total"] or 0),
        }
        for row in usage_qs
    ]
    wastage_qs = (
        StockMovement.objects.filter(
            organization=org,
            movement_type=StockMovement.MovementType.DISPOSAL,
            occurred_at__date__gte=month_start,
        )
        .values("item__name", "item__unit")
        .annotate(total=Sum("quantity"))
        .order_by("item__name")
    )
    wastage = [
        {
            "name": row["item__name"],
            "unit": row["item__unit"],
            "total": abs(row["total"] or 0),
        }
        for row in wastage_qs
    ]
    reorder = []
    for i in Item.objects.filter(organization=org, is_active=True).select_related(
        "preferred_supplier"
    ):
        on_hand = i.on_hand_quantity()
        if on_hand < i.minimum_level:
            reorder.append(
                {
                    "item": i,
                    "on_hand": on_hand,
                    "gap": i.minimum_level - on_hand,
                }
            )
    return render(
        request,
        "inventory/reports.html",
        {
            "usage": usage,
            "wastage": wastage,
            "reorder": reorder,
            "month_start": month_start,
        },
    )


@login_required
def settings_view(request):
    org = _require_org(request)
    memberships = Membership.objects.filter(organization=org).select_related("user")
    user_memberships = Membership.objects.filter(
        user=request.user, is_active=True
    ).select_related("organization")
    if request.method == "POST" and request.membership and request.membership.can_manage:
        days = request.POST.get("expiry_warning_days")
        try:
            org.expiry_warning_days = max(1, int(days))
            org.save(update_fields=["expiry_warning_days"])
            messages.success(request, "Settings updated.")
        except (TypeError, ValueError):
            messages.error(request, "Invalid warning days.")
        return redirect("settings")
    return render(
        request,
        "inventory/settings.html",
        {
            "memberships": memberships,
            "user_memberships": user_memberships,
            "recent_audit": StockMovement.objects.filter(organization=org)
            .select_related("item", "performed_by")[:25],
        },
    )
