"""Load the bundled fuel price file, so `migrate` alone gives a ready database."""

from django.db import migrations


def load(apps, schema_editor):
    from stations.importer import import_stations

    import_stations(apps.get_model("stations", "FuelStation"))


def unload(apps, schema_editor):
    apps.get_model("stations", "FuelStation").objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("stations", "0001_initial")]
    operations = [migrations.RunPython(load, unload)]
