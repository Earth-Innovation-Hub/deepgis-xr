from django.db import migrations, models

TYPES = {
    "multicopter": ("Multicopter", "DRONE", "\U0001F681"),
    "rover": ("Rover", "GROUND", "\U0001F699"),
    "boat": ("Boat", "MARINE", "\U0001F6A4"),
}

LAB_TWINS = [
    {
        "vehicle_id": "locutus", "name": "Locutus drone", "platform": "multicopter",
        "airframe": "Holybro X500 quadcopter with a gimbal camera",
        "site": "Locutus digital twin (PX4 SITL in Gazebo)",
        "aliases": ["the twin", "the drone", "locutus drone", "x500"], "mcp_robot": "locutus",
        "description": "The DREAMS Lab's simulated PX4 quadcopter; the LLM can fly it through the MCP.",
    },
    {
        "vehicle_id": "locutus-rover", "name": "Locutus rover", "platform": "rover",
        "airframe": "Aion R1 four-wheel rover with a forward camera",
        "site": "Locutus digital twin (PX4 SITL in Gazebo)",
        "aliases": ["the rover", "locutus rover", "r1", "aion r1"], "mcp_robot": "locutus-rover",
        "description": "A simulated PX4 ground rover in the same world as the Locutus drone; read-only for the LLM.",
    },
    {
        "vehicle_id": "heron-tempe", "name": "Heron boat", "platform": "boat",
        "airframe": "Clearpath Heron uncrewed surface vessel with a gimbal camera",
        "site": "Tempe Town Lake digital twin (PX4 SITL in Gazebo)",
        "aliases": ["the boat", "heron", "heron boat", "tempe boat", "usv"], "mcp_robot": "heron-tempe",
        "description": "A simulated PX4 boat on Tempe Town Lake; the LLM can steer it through the MCP.",
    },
]


def seed(apps, schema_editor):
    VehicleType = apps.get_model("core", "VehicleType")
    Vehicle = apps.get_model("core", "Vehicle")
    types = {}
    for platform, (name, category, icon) in TYPES.items():
        types[platform], _ = VehicleType.objects.get_or_create(
            name=name, defaults={"category": category, "icon_symbol": icon})
    for twin in LAB_TWINS:
        fields = {k: v for k, v in twin.items() if k != "vehicle_id"}
        Vehicle.objects.update_or_create(
            vehicle_id=twin["vehicle_id"],
            defaults={**fields, "kind": "sim", "vehicle_type": types[twin["platform"]]})


def unseed(apps, schema_editor):
    apps.get_model("core", "Vehicle").objects.filter(
        vehicle_id__in=[t["vehicle_id"] for t in LAB_TWINS]).delete()


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0005_trainingdataset_kind_min_tiles"),
    ]

    operations = [
        migrations.AddField(
            model_name="vehicle", name="kind",
            field=models.CharField(choices=[("sim", "Simulation"), ("field", "Field robot")],
                                   default="sim", max_length=10)),
        migrations.AddField(
            model_name="vehicle", name="platform",
            field=models.CharField(blank=True, default="", max_length=20,
                                   help_text="multicopter, fixed_wing, vtol, rover, legged, boat, submarine or other")),
        migrations.AddField(
            model_name="vehicle", name="airframe",
            field=models.CharField(blank=True, default="", max_length=120)),
        migrations.AddField(
            model_name="vehicle", name="site",
            field=models.CharField(blank=True, default="", max_length=200)),
        migrations.AddField(
            model_name="vehicle", name="aliases",
            field=models.JSONField(blank=True, default=list,
                                   help_text='Other names users call it, e.g. ["the rover"]')),
        migrations.AddField(
            model_name="vehicle", name="mcp_robot",
            field=models.CharField(blank=True, default="", max_length=50,
                                   help_text="Its robot id on the DREAMS Lab MCP, if the lab LLM serves it")),
        migrations.AddField(
            model_name="vehicle", name="description",
            field=models.TextField(blank=True, default="")),
        migrations.RunPython(seed, unseed),
    ]
