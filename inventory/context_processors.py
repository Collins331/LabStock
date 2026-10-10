def tenant_context(request):
    return {
        "current_organization": getattr(request, "organization", None),
        "current_membership": getattr(request, "membership", None),
    }
