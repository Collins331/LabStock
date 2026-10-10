from django.contrib import admin
from django.urls import include, path

from inventory.views import LabLoginView, LabLogoutView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", LabLoginView.as_view(), name="login"),
    path("logout/", LabLogoutView.as_view(), name="logout"),
    path("", include("inventory.urls")),
]
