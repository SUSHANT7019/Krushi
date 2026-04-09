from django.apps import AppConfig
from django.db.models.signals import post_migrate


class KrushiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Krushi'

    def ready(self):
        import Krushi.signals

# def create_default_site(sender, **kwargs):
    # from django.conf import settings
    # from django.contrib.sites.models import Site

    # try:
    #     site_id = int(getattr(settings, 'SITE_ID', 1))
    # except (TypeError, ValueError):
    #     site_id = 1

    # domain = getattr(settings, 'DEV_TUNNEL_HOST', 'localhost') or 'localhost'

    # Site.objects.get_or_create(
    #     id=site_id,
    #     defaults={
    #         'domain': domain,
    #         'name': domain,
    #     }
    # )
