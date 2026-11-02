"""Project URLs: Django admin, language switch, JS translations and the app."""
from django.contrib import admin
from django.urls import path, include
from django.views.i18n import JavaScriptCatalog

urlpatterns = [
    path('admin/', admin.site.urls),
    # POST {language: "hi"} here to change the page language (language menu).
    path('i18n/', include('django.conf.urls.i18n')),
    # gettext() for page JavaScript (pop-ups, form errors) in the user's language.
    path('jsi18n/', JavaScriptCatalog.as_view(packages=['pharma_app']), name='javascript-catalog'),
    path('', include("pharma_app.urls")),
]
