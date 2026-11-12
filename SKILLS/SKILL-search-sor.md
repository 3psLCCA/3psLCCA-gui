---
name: search-sor
description: Guide for searching a Schedule of Rates (SOR) catalog database in the running 3psLCCA desktop app to find a matching material/work item for something the user describes. Use whenever the user describes a construction activity, material, or work item and wants to find (and optionally add) a matching catalog entry, rather than typing a raw search query themselves.
---

# Search SOR Skill

This skill documents the workflow for turning a user's plain-language description of a
construction activity or material into a correct, token-based catalog search against a
specific Schedule of Rates (SOR) database in the local 3psLCCA API
(`http://127.0.0.1:8765`), and deciding whether a result is actually a good match.

> **Golden rule**: Never assume the SOR database, never guess a search query, and never
> add an item without the user explicitly picking it. If nothing usable turns up, say so
> plainly and offer manual entry instead of forcing a weak match.

---

## Step 1 — Confirm with the user which SOR to search (STRICT)

> **Strict rules, no exceptions:**
> - **Confirm the database with the user before any search.** Never guess it.
> - Search **only** the confirmed database. Always pass its `db_key`.
> - **Never search other databases** to find a match, and **never take a material from
>   another database just to finish the task.**
> - If the item isn't in the confirmed database, **stop and tell the user.** The user
>   decides: switch the project's database, or add the item manually.
> - The app enforces this: a material from any database other than the project's
>   `sor_database` is refused with `400 wrong_sor_database`.

1. Read `general_info` → `sor_database`. Tell the user which database the project uses
   and ask them to confirm it.
2. If it is empty, call `GET /catalog/databases` (optionally filtered by `country`/
   `region`), show the list, and ask the user to pick one. Set it with
   `POST /{project_id}/general_info {"sor_database": "<db_key>"}` before searching.
3. Keep that `db_key` (and `region`, if applicable). Every following call needs it.

---

## Step 2 — Get the tokens of that SOR

Call `GET /catalog/tokens?db_key=<db_key>&region=<region>`.

This returns the full vocabulary of real, indexed words extracted from every `name` and
`description` field in that specific SOR database (stop words, numbers, and single
letters already removed). This is the *only* reliable source of words that will actually
return results — don't search with a word that isn't in this set.

Treat this token list as the ground truth for that database and hold onto it for Step 3.

---

## Step 3 — Analyze the user's request and extract matching tokens

Read what the user described (the activity, material, or work item) and break it down
into candidate words/roots — then intersect those candidates against the token
vocabulary from Step 2. Only search using words that are actually present in that set.

Tips:
- Every candidate token must be checked against the Step 2 token set before it's used —
  never search a word just because it seems plausible. If it's not in that set, it will
  not return results.
- SOR wording varies by state/region (singular/plural, spelling), so when the user's
  exact word isn't in the vocabulary, check whether a variant is — `pile`/`piles`,
  `levelling`/`leveling`, `cofferdam`/`cofferdams` — and search whichever form the
  fetched token set actually contains, not whichever form the user happened to type.
- If no direct variant exists either, look for synonyms or related terms that are in the
  vocabulary (e.g. "footing" → `cap`/`foundation`; "shuttering" → `formwork`).
- Prepare a short ranked list of 2–4 candidate tokens, all confirmed present in the
  vocabulary, rather than just one — the first may return nothing or only weak matches.

---

## Step 4 — Search, then read description + title before deciding

1. Search with `GET /catalog/search?q=<token>&db_key=<db_key>&region=<region>`.
2. For every candidate row, read the full `name` **and** `description` fields — never
   decide a match on the title/token overlap alone. A name can look right while the
   description reveals a different grade, size, unit basis, or scope.
3. Keep only rows whose description genuinely fits the activity/spec the user described.
   Drop everything else, even if the name matched well.
4. If no row survives this filter (zero results, or only weak/partial matches):
   - Go back to the Step 3 candidate list and try another token.
   - Repeat with a few reasonable alternates before concluding there's no match — don't
     stop after a single query.

---

## Step 5 — Present results, or offer manual entry

**If one or more good matches survive Step 4:**
Present them to the user as a table, e.g.:

`Sr no. | Item Name | Description (short) | Rate / Unit | Database`

Ask the user to pick a row by Sr no. (and quantity, if this is feeding into an add
operation). Never auto-select or auto-add — the user must explicitly confirm.

**If no usable match was found after trying reasonable alternate tokens:**
Tell the user plainly, e.g.:

> "No results found in the [db name] database for [activity/material] — search was
> incomplete even after trying [tokens tried]."

Then offer the choice — don't assume it — between:
- **Trying a different SOR database** (list alternatives from `GET /catalog/databases`), or
- **Adding it manually**, asking the user for the values it needs (material name, unit,
  quantity, rate, and carbon figure if known) rather than filling any of them in yourself.

---

## Quick reference — endpoints used in this skill

| Purpose | Endpoint |
| :--- | :--- |
| List available SOR databases | `GET /catalog/databases?country=&region=` |
| Get indexed vocabulary for one SOR | `GET /catalog/tokens?db_key=&region=` |
| Full-text search within one SOR | `GET /catalog/search?q=<token>&db_key=&region=&limit=&offset=` |
| Browse raw catalog rows | `GET /catalog/items?db_key=&region=&limit=&offset=` |

All `/catalog/*` endpoints require a valid `X-API-Token` header (any currently-valid
project token works — they are not project-scoped).
