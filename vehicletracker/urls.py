from django.contrib import admin
from django.urls import include, path
from django.conf import settings
from django.conf.urls.static import static

project_prefixed_urlpatterns = [
    path("", include("dashboard.urls")),
    path("livetracker/", include("livetracker.urls")),
    path("roster/", include("roster.urls")),
    path("livenotif/", include("livenotif.urls")),
]

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", include("dashboard.urls")),
    path("accounts/", include(("dashboard.urls", "accounts"), namespace="accounts")),
    path("livetracker/", include("livetracker.urls")),
    path("roster/", include("roster.urls")),
    path("livenotif/", include("livenotif.urls")),
    path("<slug:project>/", include((project_prefixed_urlpatterns, "project_prefixed"))),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    import debug_toolbar
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
