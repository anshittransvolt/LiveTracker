from django.apps import AppConfig


class MisConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'mis'
    verbose_name = 'Management Information System'

    def ready(self):
        from . import scheduler
        scheduler.start()
