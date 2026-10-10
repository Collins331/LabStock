from .models import Membership


class TenantMiddleware:
    """Attach the active organization membership to the request."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.membership = None
        request.organization = None

        if request.user.is_authenticated:
            org_id = request.session.get("active_organization_id")
            memberships = (
                Membership.objects.filter(user=request.user, is_active=True)
                .select_related("organization")
                .order_by("organization__name")
            )
            membership = None
            if org_id:
                membership = next(
                    (m for m in memberships if m.organization_id == org_id), None
                )
            if membership is None and memberships:
                membership = memberships[0]
                request.session["active_organization_id"] = membership.organization_id
            request.membership = membership
            request.organization = membership.organization if membership else None

        return self.get_response(request)
