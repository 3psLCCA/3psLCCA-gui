"""
devtools/test apis/stress_bulk_add.test.py

Volume/throughput stress test across every Construction Works chunk
(str_foundation, str_sub_structure, str_super_structure, str_misc): adds a
user-specified number of random materials (default 1000) to EACH chunk via
repeated add_manual calls, one entry per HTTP request. This is deliberately
about VOLUME (does the app stay correct and responsive under thousands of
sequential writes to the same project file) rather than one-off edge-case
correctness (see str_work_data.test.py / random_stress_fill.test.py for
that) - though a slice of the load is deliberately "poisoned" (see below)
so numeric-edge-case behaviour gets exercised at scale too, not just once.

Poison mix - a configurable fraction (--poison-rate, default 5%) of the
materials sent per chunk use one of these instead of a normal random
quantity/rate:
  - NaN       - json.dumps(float('nan')) emits the literal token NaN,
                which Python's own json.loads parses right back into
                float('nan') - no hand-crafted bytes needed. Per
                str_work_data.test.py's finding, validate_material_values's
                "qty <= 0" / "rate < 0"/"rate == 0" guards never fire for
                NaN, so this is EXPECTED TO BE ACCEPTED.
  - Infinity  - same story: neither "<= 0" nor "< 0"/"== 0" catches
                +Infinity. EXPECTED TO BE ACCEPTED.
  - -Infinity - "-inf <= 0" IS true, so this one correctly gets rejected.
  - null      - quantity/rate missing entirely (sent as JSON null) -
                required-field checks correctly reject this too.
Each poison outcome is tracked and verified via GET same as a normal entry,
not just assumed from the docstring above - what actually happens this run
is what gets reported.

Flow per chunk:
  1. GET /{project_id}/{chunk} FIRST, to record the real baseline (per-
     component entry counts) before anything is written.
  2. Adds <count> materials via add_manual, rotating across every
     registered component (str_component_registry), mixing in the poison
     probes above at --poison-rate.
  3. GETs again afterward and confirms the total entry count increased by
     exactly the number of ACCEPTED adds (normal + accepted poison) - not
     just "the loop finished without raising an exception."
  4. Spot-checks a random sample of newly-created normal entries for exact
     persistence, and separately verifies every poison probe's actual
     accept/reject outcome and (if accepted) that the NaN/Infinity value
     really persisted.
  5. Reports elapsed time and throughput (materials/sec).

Run:

    python "devtools/test apis/stress_bulk_add.test.py" --project-id <id> --token <token> [--count 1000] [--chunks str_foundation,str_sub_structure,str_super_structure,str_misc] [--poison-rate 0.05] [--bombard] [--bombard-workers 20]

Omit --count to be asked interactively (default 1000 on blank input).
--chunks defaults to all four if omitted.

--bombard: fires all of a chunk's requests CONCURRENTLY (via a thread pool,
--bombard-workers wide, default 20) instead of one at a time. Without it,
every request is sent sequentially - blocking on each response before
sending the next - which is what "volume" testing means by default here.
--bombard is a genuinely different kind of test: since server.py's
start_api_server() uses werkzeug's make_server() without threaded=True,
this dev server does NOT process requests in parallel - so --bombard
mainly exercises what happens when a burst of requests queue up at the
socket/OS level waiting for a single-threaded server to work through them
one by one (timeouts? dropped connections? out-of-order responses due to
connection reuse?), not true server-side concurrency. Useful for finding
timeout/connection-handling bugs that per-request-sequential testing can't
reach; every result is still matched back to its original job and
processed with the exact same bookkeeping as the sequential path, so
correctness assertions (entry counts, poison outcomes, spot-checks) apply
identically either way.

This adds real, permanent entries to whichever project you point it at -
point it at a scratch/testing project. There is no bulk-delete API, so this
is a large, one-way amount of data added to that project (no trash/cleanup
pass here - this file is testing volume, not trash behaviour).
"""

import concurrent.futures
import math
import random
import string
import sys
import time
import uuid

from _common import call, step, ok, build_arg_parser, setup_project_and_token, summary

ALL_CHUNKS = ["str_foundation", "str_sub_structure", "str_super_structure", "str_misc"]
SAFE_UNITS = ["kg", "cum", "MT", "sqm", "m", "nos", "litre", "sqft"]
POISON_KINDS = ["nan", "inf", "neg_inf", "null"]

parser = build_arg_parser(__doc__)
parser.add_argument("--count", type=int, default=None,
                     help="how many random materials to add PER CHUNK (default: ask interactively, default 1000 on blank)")
parser.add_argument("--chunks", default=None,
                     help="comma-separated chunk list (default: all four str_* chunks)")
parser.add_argument("--poison-rate", type=float, default=0.05,
                     help="fraction of adds per chunk that use a NaN/Infinity/-Infinity/null probe instead "
                          "of a normal random value (default 0.05 = 5%%)")
parser.add_argument("--bombard", action="store_true",
                     help="fire all of a chunk's requests concurrently (thread pool) instead of one at a time")
parser.add_argument("--bombard-workers", type=int, default=20,
                     help="thread pool size when --bombard is set (default 20)")
args = parser.parse_args()

if args.count is not None:
    count = args.count
else:
    try:
        raw = input("How many random materials to add PER CHUNK? [default 1000]: ").strip()
    except EOFError:
        raw = ""
    count = int(raw) if raw else 1000

chunks = [c.strip() for c in args.chunks.split(",")] if args.chunks else ALL_CHUNKS
poison_rate = args.poison_rate

setup = setup_project_and_token(args)
if setup is None:
    sys.exit(1)
project_id, TOKEN = setup


def random_name(tag: str = "StressMaterial") -> str:
    return f"{tag} {uuid.uuid4().hex[:10]} " + "".join(random.choices(string.ascii_letters, k=6))


def random_magnitude() -> float:
    exponent = random.uniform(-3, 6)
    mantissa = random.uniform(1, 9.999999)
    return round(mantissa * (10 ** exponent), 6)


def component_counts(data: dict) -> dict:
    return {comp: len(entries) for comp, entries in data.items()}


def poison_value(kind: str):
    return {"nan": float("nan"), "inf": float("inf"), "neg_inf": float("-inf"), "null": None}[kind]


# ============================================================================
# Discover registry once (component lists are per-chunk, fetched per chunk
# below, but the registry GET itself is one call).
# ============================================================================
step("0. GET str_component_registry - component lists for every chunk")
status, registry_body = call("GET", f"/{project_id}/str_component_registry", token=TOKEN)
ok("GET str_component_registry -> 200", status == 200)
registry_data = registry_body.get("data", {})

grand_created = 0
grand_failed = 0
grand_poison_accepted = 0
grand_poison_rejected = 0
grand_mismatches = 0

for chunk in chunks:
    step(f"=== {chunk} ===")

    # ------------------------------------------------------------------
    # 1. GET FIRST - baseline before any writes to this chunk
    # ------------------------------------------------------------------
    step(f"1. GET /{project_id}/{chunk} - baseline before adding {count} material(s)")
    status, before_body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    ok(f"GET {chunk} -> 200", status == 200)
    before_data = before_body.get("data", {})
    before_counts = component_counts(before_data)
    before_total = sum(before_counts.values())
    print(f"  baseline: {before_total} entr(y/ies) across {len(before_counts)} component(s): {before_counts}")

    reg_comps = registry_data.get(chunk, {})
    components = [c for c, meta in reg_comps.items() if not meta.get("is_deleted")]
    for c in before_data:
        if c not in components:
            components.append(c)
    if not components:
        components = [f"Stress Component ({chunk})"]
    print(f"  rotating across {len(components)} component(s): {components}")

    # ------------------------------------------------------------------
    # 2. Build every job upfront (same job list regardless of send mode),
    #    then fire them either sequentially or concurrently (--bombard).
    # ------------------------------------------------------------------
    step(f"2. Adding {count} material(s) to {chunk} ({poison_rate * 100:.0f}% poisoned"
         f"{', BOMBARD mode - ' + str(args.bombard_workers) + ' concurrent workers' if args.bombard else ', sequential'})")

    jobs = []  # each: (comp, name, values, is_poison, kind, field)
    for i in range(count):
        comp = components[i % len(components)]
        name = random_name()
        unit = random.choice(SAFE_UNITS)
        values = {"material_name": name, "unit": unit, "quantity": random_magnitude(), "rate": random_magnitude()}

        is_poison = random.random() < poison_rate
        kind = field = None
        if is_poison:
            kind = random.choice(POISON_KINDS)
            field = random.choice(["quantity", "rate"])
            values[field] = poison_value(kind)

        jobs.append((comp, name, values, is_poison, kind, field))

    def _send(job):
        comp, name, values, *_ = job
        return call("POST", f"/{project_id}/{chunk}/add_manual", token=TOKEN,
                     body={"component": comp, "values": values})

    created: list[tuple[str, str, float, float]] = []       # normal entries
    poison_sent: list[tuple[str, str, str, str]] = []       # (component, name, kind, field)
    counters = {"fail": 0}  # dict, not a plain int - _record() below is a nested
                             # function defined inside a for-loop (not inside an
                             # enclosing def), so there's no function scope for
                             # `nonlocal` to bind to; a mutable container sidesteps that.
    progress_every = max(1, count // 20)

    def _record(i, job, status, r):
        comp, name, values, is_poison, kind, field = job
        if is_poison:
            poison_sent.append((comp, name, kind, field))
        elif status == 200:
            created.append((comp, name, values["quantity"], values["rate"]))
        else:
            counters["fail"] += 1
        if (i + 1) % progress_every == 0 or (i + 1) == count:
            elapsed = time.time() - start
            rate_so_far = (i + 1) / elapsed if elapsed > 0 else 0
            print(f"  {i + 1}/{count} done ({counters['fail']} unexpected failures so far) - {rate_so_far:.1f} req/s")

    start = time.time()
    if args.bombard:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.bombard_workers) as pool:
            future_to_index = {pool.submit(_send, job): i for i, job in enumerate(jobs)}
            done_count = 0
            for future in concurrent.futures.as_completed(future_to_index):
                i = future_to_index[future]
                try:
                    status, r = future.result()
                except Exception as e:
                    status, r = -1, {"error": "request_exception", "detail": str(e)}
                done_count += 1
                _record(done_count - 1, jobs[i], status, r)  # index only affects progress-print cadence here
    else:
        for i, job in enumerate(jobs):
            status, r = _send(job)
            _record(i, job, status, r)
    elapsed_total = time.time() - start

    fail_count = counters["fail"]
    ok(f"{chunk}: {len(created)} normal add_manual calls succeeded, {fail_count} unexpectedly failed",
       fail_count == 0, detail=f"{fail_count} failures")
    print(f"  elapsed: {elapsed_total:.1f}s for {count} requests "
          f"({count / elapsed_total:.1f} req/s, {elapsed_total / count * 1000:.1f} ms/req average)")

    # ------------------------------------------------------------------
    # 3. GET again - confirm exact entry-count increase
    # ------------------------------------------------------------------
    step(f"3. GET {chunk} again - confirm entry-count increase and check poison outcomes")
    status, after_body = call("GET", f"/{project_id}/{chunk}", token=TOKEN)
    ok(f"GET {chunk} -> 200 (server still responsive after {count} writes)", status == 200)
    after_data = after_body.get("data", {})
    after_counts = component_counts(after_data)
    after_total = sum(after_counts.values())
    print(f"  after: {after_total} entr(y/ies) across {len(after_counts)} component(s): {after_counts}")

    # Figure out which poison probes actually got accepted, by presence in
    # the after-data (rather than assuming from the docstring's prediction).
    poison_accepted = 0
    poison_rejected = 0
    for comp, name, kind, field in poison_sent:
        entry = next((e for e in after_data.get(comp, []) if e.get("values", {}).get("material_name") == name), None)
        if entry is None:
            poison_rejected += 1
            continue
        v = entry.get("values", {}).get(field)
        looks_right = (
            (kind == "nan" and isinstance(v, float) and math.isnan(v)) or
            (kind == "inf" and v == float("inf")) or
            (kind == "neg_inf" and v == float("-inf")) or
            (kind == "null" and v is None)
        )
        if looks_right:
            poison_accepted += 1
        else:
            poison_rejected += 1  # present but not with the poisoned value - treat as "didn't take"
    print(f"  poison probes sent: {len(poison_sent)} "
          f"({sum(1 for *_, k, _f in poison_sent if k == 'nan')} nan, "
          f"{sum(1 for *_, k, _f in poison_sent if k == 'inf')} inf, "
          f"{sum(1 for *_, k, _f in poison_sent if k == 'neg_inf')} -inf, "
          f"{sum(1 for *_, k, _f in poison_sent if k == 'null')} null)")
    print(f"  poison outcome: {poison_accepted} accepted+persisted, {poison_rejected} rejected/not-found")
    ok(f"{chunk}: every poison probe accounted for (accepted + rejected == sent)",
       poison_accepted + poison_rejected == len(poison_sent))

    expected_total = before_total + len(created) + poison_accepted
    ok(f"{chunk}: total entry count increased by exactly (normal + accepted-poison) adds "
       f"(before={before_total}, after={after_total}, expected={expected_total})",
       after_total == expected_total)

    # ------------------------------------------------------------------
    # 4. Spot-check a random sample of newly-created NORMAL entries
    # ------------------------------------------------------------------
    step(f"4. Spot-check a random sample of {chunk}'s newly-created normal entries")
    sample_size = min(25, len(created))
    sample = random.sample(created, sample_size) if created else []
    mismatches = []
    for comp, name, qty, rate in sample:
        entry = next((e for e in after_data.get(comp, []) if e.get("values", {}).get("material_name") == name), None)
        if entry is None:
            mismatches.append(f"{name!r} missing from {comp!r}")
            continue
        v = entry.get("values", {})
        if v.get("quantity") != qty or v.get("rate") != rate:
            mismatches.append(f"{name!r}: expected qty={qty} rate={rate}, got qty={v.get('quantity')} rate={v.get('rate')}")
    ok(f"{chunk}: spot-checked {sample_size} random normal entries - all match exactly",
       not mismatches, detail=f"{len(mismatches)} mismatch(es): {mismatches[:5]}")

    grand_created += len(created)
    grand_failed += fail_count
    grand_poison_accepted += poison_accepted
    grand_poison_rejected += poison_rejected
    grand_mismatches += len(mismatches)


step("Grand summary across all chunks")
print(f"  total normal entries created : {grand_created}")
print(f"  total unexpected failures    : {grand_failed}")
print(f"  total poison probes accepted : {grand_poison_accepted}")
print(f"  total poison probes rejected : {grand_poison_rejected}")
print(f"  total spot-check mismatches  : {grand_mismatches}")

sys.exit(summary())
