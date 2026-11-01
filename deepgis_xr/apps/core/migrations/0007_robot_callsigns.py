"""Lab twins get callsigns: one id per robot, independent of the world it runs in.

locutus -> kestrel (multirotor), locutus-rover -> badger (rover), heron-tempe -> otter (boat).
Rows are renamed in place, so their tracks (VehiclePosition) stay attached. The world goes
in site; "multicopter" becomes "multirotor".
"""

from django.db import migrations

RENAMES = {"locutus": "kestrel", "locutus-rover": "badger", "heron-tempe": "otter"}

LAB_TWINS = {
    "kestrel": {
        "name": "Kestrel", "platform": "multirotor",
        "airframe": "Holybro X500 quadcopter with a gimbal camera",
        "site": "Locutus world (digital twin, PX4 SITL in Gazebo)",
        "aliases": ["the multirotor", "multirotor", "the quadcopter", "x500"], "mcp_robot": "kestrel",
        "description": "Simulated PX4 multirotor in the Locutus world; the LLM can fly it through the MCP.",
    },
    "badger": {
        "name": "Badger", "platform": "rover",
        "airframe": "Aion R1 four-wheel rover with a forward camera",
        "site": "Locutus world (digital twin, PX4 SITL in Gazebo)",
        "aliases": ["the rover", "rover", "r1", "aion r1"], "mcp_robot": "badger",
        "description": "Simulated PX4 ground rover in the Locutus world; read-only for the LLM.",
    },
    "otter": {
        "name": "Otter", "platform": "boat",
        "airframe": "Clearpath Heron uncrewed surface vessel with a gimbal camera",
        "site": "Tempe Town Lake world (digital twin, PX4 SITL in Gazebo)",
        "aliases": ["the boat", "boat", "heron", "usv"], "mcp_robot": "otter",
        "description": "Simulated PX4 boat on Tempe Town Lake; the LLM can steer it through the MCP.",
    },
}
TYPES = {"multirotor": ("Multirotor", "DRONE", "\U0001F681"), "rover": ("Rover", "GROUND", "\U0001F699"),
         "boat": ("Boat", "MARINE", "\U0001F6A4")}


def forward(apps, schema_editor):
    VehicleType = apps.get_model("core", "VehicleType")
    Vehicle = apps.get_model("core", "Vehicle")
    old_type = VehicleType.objects.filter(name="Multicopter").first()
    if old_type and not VehicleType.objects.filter(name="Multirotor").exists():
        old_type.name = "Multirotor"
        old_type.save(update_fields=["name"])
    types = {}
    for platform, (name, category, icon) in TYPES.items():
        types[platform], _ = VehicleType.objects.get_or_create(
            name=name, defaults={"category": category, "icon_symbol": icon})
    Vehicle.objects.filter(platform="multicopter").update(platform="multirotor")
    for old, new in RENAMES.items():
        if not Vehicle.objects.filter(vehicle_id=new).exists():
            Vehicle.objects.filter(vehicle_id=old).update(vehicle_id=new)
    for vid, fields in LAB_TWINS.items():
        Vehicle.objects.update_or_create(
            vehicle_id=vid, defaults={**fields, "kind": "sim", "vehicle_type": types[fields["platform"]]})


def backward(apps, schema_editor):
    Vehicle = apps.get_model("core", "Vehicle")
    for old, new in RENAMES.items():
        if not Vehicle.objects.filter(vehicle_id=old).exists():
            Vehicle.objects.filter(vehicle_id=new).update(vehicle_id=old, mcp_robot=old)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_vehicle_registry"),
    ]

    operations = [migrations.RunPython(forward, backward)]
