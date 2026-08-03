"""
devtools/test apis/random_stress_fill.test.py

Extensive, randomized data-generation stress test across every Construction
Works Data chunk (str_foundation, str_sub_structure, str_super_structure,
str_misc):

  1. Picks one SOR database at random (GET /catalog/databases).
  2. Searches it for "a" (GET /catalog/search?q=a) and pages through EVERY
     matching item (not just the first page).
  3. For every existing component in every str_* chunk: adds one random
     catalog item (add_from_catalog) with a random quantity spanning a huge
     magnitude range - deliberately no artificial upper/lower clamp beyond
     what the API itself requires (quantity > 0), so both tiny fractional
     and enormous quantities get exercised.
  4. Also, for every existing component in every str_* chunk: adds one
     fully random manual material (add_manual) - random name, random unit
     (from a safe known-unit set), random quantity AND rate spanning the
     same huge magnitude range.
  5. Trashes a handful of the entries this run created (not all - a
     partial trash, same as the user asked), verified via GET .../trash.

Every add is checked via a follow-up GET, same policy as the rest of this
folder: the point isn't just "did the POST return 200" but "did the value
actually land in the stored project file."

Run:

    python "devtools/test apis/random_stress_fill.test.py" --project-id <id> --token <token>

This heavily mutates real chunk data across every Construction Works
chunk on whichever project you point it at - point it at a scratch/testing
project. No full cleanup pass (only a partial trash, by design); there's
also no delete-project/delete-component API, so this is a one-way, fairly
large data injection into that project.
"""

import random
import string
import sys
import uuid
from urllib.parse import urlencode

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

STR_CHUNKS = ["str_foundation", "str_sub_structure", "str_super_structure", "str_misc"]
SAFE_UNITS = ["kg", "cum", "MT", "sqm", "m", "nos", "litre", "sqft"]

parser = build_arg_parser(__doc__)
args = parser.parse_args()

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup

added: list[tuple[str, str]] = []  # (chunk, entry_id) created this run


def random_name(prefix: str) -> str:
    return f"{prefix} {uuid.uuid4().hex[:8]} " + "".join(random.choices(string.ascii_letters, k=6))


def random_magnitude() -> float:
    """A value spanning many orders of magnitude (roughly 1e-6 to 1e9),
    deliberately not clamped to any 'sensible' range - the point is to
    exercise both extremely tiny and extremely large real quantities/rates,
    not just typical ones."""
    exponent = random.uniform(-6, 9)
    mantissa = random.uniform(1, 9.999999)
    return round(mantissa * (10 ** exponent), 6)


def get_data(chunk: str) -> dict:
    _, body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    return body.get("data", {})


def find_entry(data: dict, component: str, material_name: str):
    for e in data.get(component, []):
        if e.get("values", {}).get("material_name") == material_name:
            return e
    return None


# ============================================================================
# 1. Pick a random SOR database
# ============================================================================
step("1. GET /catalog/databases - pick one at random")
status, dbs = call("GET", "/catalog/databases", token=TOKEN)
ok("GET /catalog/databases -> 200, non-empty", status == 200 and dbs.get("count", 0) > 0)
if status != 200 or not dbs.get("databases"):
    print("No databases available - cannot continue.")
    sys.exit(summary())

db = random.choice(dbs["databases"])
db_key = db["db_key"]
print(f"  chosen at random: {db_key!r} (country={db.get('country')!r}, region={db.get('region')!r})")


# ============================================================================
# 2. Search "a" in that database - page through EVERY matching item
# ============================================================================
step(f"2. GET /catalog/search?q=a&db_key={db_key} - list ALL matching items")
all_items = []
offset = 0
limit = 200
while True:
    q = urlencode({"q": "a", "db_key": db_key, "limit": limit, "offset": offset})
    status, page = call("GET", f"/catalog/search?{q}", token=TOKEN)
    if status != 200:
        break
    items = page.get("items", [])
    all_items.extend(items)
    total = page.get("total", len(all_items))
    offset += limit
    if offset >= total or not items:
        break
ok(f"GET /catalog/search -> 200, collected all matching items", status == 200)
print(f"  {len(all_items)} item(s) found for q='a' in {db_key!r}")
if not all_items:
    print("  no items matched 'a' in this database - catalog-item additions will be skipped, "
          "manual-value additions will still proceed.")


# ============================================================================
# 2b. Discover the REAL canonical component list per chunk via
#     str_component_registry - a component with zero materials doesn't
#     appear as a key in GET /{chunk}'s own data yet, so relying on that
#     alone would miss every not-yet-populated table (Excavation, Pile,
#     Pile Cap, Bearings, Pedestal, Pier, Pier Cap, Girder, Deck Slab,
#     Diaphragm, Cross Bracings, Waterproofing, Drainage, etc.) - exactly
#     the ones this run is meant to reach. str_component_registry is the
#     one source that lists them all regardless of entry count.
# ============================================================================
step("2b. GET str_component_registry - the real component list per chunk")
status, registry_body = call("GET", f"/{project_id}/str_component_registry", token=TOKEN)
ok("GET str_component_registry -> 200", status == 200)
registry_data = registry_body.get("data", {})
for chunk in STR_CHUNKS:
    comps = registry_data.get(chunk, {})
    active = [c for c, meta in comps.items() if not meta.get("is_deleted")]
    print(f"  {chunk}: {len(active)} registered component(s): {active}")


# ============================================================================
# 3+4. For EVERY registered component in every str_* chunk: add one random
#      catalog item AND one fully random manual material - not just the
#      ones that already happen to have entries.
# ============================================================================
step("3+4. Add a random catalog item + a random manual material to every registered component")
for chunk in STR_CHUNKS:
    reg_comps = registry_data.get(chunk, {})
    components = [c for c, meta in reg_comps.items() if not meta.get("is_deleted")]
    # Union with anything that has entries but somehow isn't in the registry
    # snapshot (defensive - shouldn't normally happen, but don't silently
    # skip a real table if it does).
    for c in get_data(chunk):
        if c not in components:
            components.append(c)
    if not components:
        components = [f"Auto Component ({chunk})"]  # genuinely nothing registered - add_manual will create it
        print(f"  {chunk}: nothing registered - will create {components[0]!r} via add_manual")
    else:
        print(f"  {chunk}: targeting {len(components)} component(s): {components}")

    for comp in components:
        # --- random catalog item, random extreme quantity ---
        if all_items:
            item = random.choice(all_items)
            qty = random_magnitude()
            status, r = call(
                "POST", f"/{project_id}/{chunk}/add_from_catalog", token=TOKEN,
                body={"component": comp, "db_key": item["db_key"], "material_name": item["name"], "quantity": qty},
            )
            ok(f"{chunk}/{comp!r}: add_from_catalog {item['name']!r} qty={qty} -> {status}",
               status == 200, detail=f"body={r}" if status != 200 else "")
            if status == 200:
                entry = find_entry(get_data(chunk), comp, item["name"])
                ok(f"{chunk}/{comp!r}: GET confirms {item['name']!r} persisted with qty={qty}",
                   entry is not None and entry.get("values", {}).get("quantity") == qty)
                if entry:
                    added.append((chunk, entry["id"]))

        # --- fully random manual material, random extreme quantity + rate ---
        name = random_name("RandomMaterial")
        unit = random.choice(SAFE_UNITS)
        qty = random_magnitude()
        rate = random_magnitude()
        status, r = call(
            "POST", f"/{project_id}/{chunk}/add_manual", token=TOKEN,
            body={"component": comp, "values": {"material_name": name, "unit": unit, "quantity": qty, "rate": rate}},
        )
        ok(f"{chunk}/{comp!r}: add_manual {name!r} unit={unit} qty={qty} rate={rate} -> {status}",
           status == 200, detail=f"body={r}" if status != 200 else "")
        if status == 200:
            entry = find_entry(get_data(chunk), comp, name)
            ok(f"{chunk}/{comp!r}: GET confirms {name!r} persisted with qty={qty}, rate={rate}",
               entry is not None
               and entry.get("values", {}).get("quantity") == qty
               and entry.get("values", {}).get("rate") == rate)
            if entry:
                added.append((chunk, entry["id"]))


# ============================================================================
# 5. Trash a handful of the entries created this run (partial, not all)
# ============================================================================
step("5. Trash a handful of the entries created this run")
sample_size = min(5, len(added))
to_trash = random.sample(added, sample_size) if added else []
print(f"  trashing {sample_size} of {len(added)} entries created this run")

trashed_ok = True
for chunk, entry_id in to_trash:
    status, r = call("POST", f"/{project_id}/{chunk}/trash", token=TOKEN, body={"id": entry_id})
    trashed_ok = trashed_ok and status == 200
ok(f"POST .../trash -> 200 for all {sample_size} sampled entries", trashed_ok)

for chunk, entry_id in to_trash:
    status, trashed_list = call("GET", f"/{project_id}/{chunk}/trash", token=TOKEN)
    found = any(e.get("id") == entry_id for entries in trashed_list.get("data", {}).values() for e in entries)
    ok(f"GET {chunk}/trash -> entry {entry_id} confirmed trashed", status == 200 and found)


print(f"\n{len(added)} entries created this run across {len(STR_CHUNKS)} chunks; "
      f"{sample_size} trashed, {len(added) - sample_size} left active.")

sys.exit(summary())
