from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("items/", views.item_list, name="item_list"),
    path("items/<int:pk>/", views.item_detail, name="item_detail"),
    path("locations/", views.location_list, name="location_list"),
    path("lots/", views.lot_list, name="lot_list"),
    path("opened/", views.opened_list, name="opened_list"),
    path("receive/", views.receive_stock, name="receive"),
    path("issue/", views.issue_stock, name="issue"),
    path("open/", views.open_container, name="open_container"),
    path("adjust/", views.adjust_stock, name="adjust"),
    path("counts/", views.count_list, name="count_list"),
    path("counts/new/", views.count_create, name="count_create"),
    path("counts/<int:pk>/", views.count_detail, name="count_detail"),
    path("movements/", views.movement_list, name="movement_list"),
    path("reports/", views.reports, name="reports"),
    path("settings/", views.settings_view, name="settings"),
    path("switch-org/<int:org_id>/", views.switch_organization, name="switch_org"),
]
