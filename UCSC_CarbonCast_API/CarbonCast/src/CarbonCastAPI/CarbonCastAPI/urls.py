"""
URL configuration for CarbonCastAPI project.
"""
from django.contrib import admin
from django.urls import path, include
from CarbonCastRESTAPI import urls as CarbonCastRESTAPI_urls
from django.urls import re_path
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi 
from django.conf import settings
from django.conf.urls.static import static
from CarbonCastAPI.api_info import API_INFO 


schema_view = get_schema_view(
   API_INFO,
   public=True,
   permission_classes=(permissions.AllowAny,),
   url='http://127.0.0.1:8001/v1/',
)

urlpatterns = [
    re_path(r'^doc(?P<format>\.json|\.yaml)$',
            schema_view.without_ui(cache_timeout=0), name='schema-json'), 
    path('doc/', schema_view.with_ui('swagger', cache_timeout=0),
         name='schema-swagger-ui'), 
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0),
         name='schema-redoc'),
    path('admin/', admin.site.urls),
    path('api-auth/', include('rest_framework.urls')),
    path('v1/', include(CarbonCastRESTAPI_urls)),
    path('', include(CarbonCastRESTAPI_urls)),
]
if settings.DEBUG:
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
