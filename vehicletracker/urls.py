from django.contrib import admin
from django.urls import include, path
from django.views.generic import RedirectView
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("", RedirectView.as_view(url="/livetracker/", permanent=False)),
    path("livetracker/", include("livetracker.urls")),
    path("livenotif/", include("livenotif.urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    import debug_toolbar
    urlpatterns += [path("__debug__/", include(debug_toolbar.urls))]
