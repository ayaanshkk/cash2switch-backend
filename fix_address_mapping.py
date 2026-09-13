"""
One-time migration: re-parse incorrectly mapped address fields
for both Opportunity_Details (leads) and Client_Master/Project_Details (renewals).

Run once: python fix_address_mapping.py
"""

import os
import re
import psycopg2
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from datetime import datetime


# ---------------------------------------------------------------------------
# Connection — reuse same logic as _get_raw_connection
# ---------------------------------------------------------------------------

def get_raw_connection():
    db_url = os.environ.get('DATABASE_URL', '')

    for prefix in ('postgresql+psycopg2://', 'postgresql+pg8000://',
                   'postgres+psycopg2://', 'postgres+pg8000://'):
        if db_url.startswith(prefix):
            db_url = 'postgresql://' + db_url[len(prefix):]
            break

    if not db_url:
        raise RuntimeError('DATABASE_URL environment variable not set')

    parsed = urlparse(db_url)
    search_path = None

    if parsed.query:
        query_params = parse_qs(parsed.query, keep_blank_values=True)
        options_val  = query_params.pop('options', [None])[0]

        if options_val:
            m = re.search(r'--search_path[= ]([^\s&]+)', options_val)
            if m:
                search_path = m.group(1)

        new_query = urlencode(
            {k: v[0] for k, v in query_params.items()},
            safe=''
        )
        parsed  = parsed._replace(query=new_query)
        db_url  = urlunparse(parsed)

    if db_url.endswith('?'):
        db_url = db_url[:-1]

    conn = psycopg2.connect(db_url)
    conn.autocommit = False

    if search_path:
        cur = conn.cursor()
        schemas = ', '.join(
            f'"{s.strip()}"' if not s.strip().startswith('"') else s.strip()
            for s in search_path.split(',')
        )
        cur.execute(f'SET search_path TO {schemas}')
        cur.close()
        conn.commit()

    return conn


# ---------------------------------------------------------------------------
# Address parser — same logic as _parse_address_components
# ---------------------------------------------------------------------------

def parse_address_components(addr1: str, addr2: str = '', addr3: str = '') -> dict:
    """
    Parse raw address lines into structured components.
    If addr1 starts with a number, split it into door_number + street.
    """
    door_number  = None
    street_parts = []

    if addr1:
        m = re.match(r'^(\d+[A-Za-z]?)\s+(.+)$', addr1.strip())
        if m:
            door_number = m.group(1)
            street_parts.append(m.group(2))
        else:
            street_parts.append(addr1.strip())

    if addr2 and addr2.lower() not in ('nan', 'none', ''):
        street_parts.append(addr2.strip())
    if addr3 and addr3.lower() not in ('nan', 'none', ''):
        street_parts.append(addr3.strip())

    street = ', '.join(p for p in street_parts if p)

    return {
        'door_number': door_number,
        'street':      street or None,
    }


def is_bad_address(street_val: str, town_val: str, county_val: str, postcode_val: str) -> bool:
    """
    Detect whether the street field has everything dumped into it.
    Signs: street contains commas with what looks like a postcode or town,
    while town/county are empty.
    """
    if not street_val:
        return False
    # If town and county are empty but street is long and comma-separated
    # it's likely everything got joined into street
    has_empty_town   = not town_val or town_val.strip() == ''
    has_empty_county = not county_val or county_val.strip() == ''
    street_has_commas = ',' in street_val
    # Also catch postcode pattern inside the street value
    postcode_in_street = bool(re.search(r'[A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2}', street_val.upper()))

    return (has_empty_town or has_empty_county) and (street_has_commas or postcode_in_street)


# ---------------------------------------------------------------------------
# Fix leads (Opportunity_Details)
# ---------------------------------------------------------------------------

def fix_leads(conn, tenant_id: str = None, dry_run: bool = False):
    cur = conn.cursor()

    tenant_filter = "AND tenant_id = %s" if tenant_id else ""
    params = (tenant_id,) if tenant_id else ()

    cur.execute(f"""
        SELECT
            opportunity_id,
            address,
            town,
            county,
            postcode,
            door_number
        FROM "StreemLyne_MT"."Opportunity_Details"
        WHERE address IS NOT NULL
          AND address != ''
          {tenant_filter}
        ORDER BY opportunity_id
    """, params)

    rows = cur.fetchall()
    print(f"[Leads] Found {len(rows)} records with address data to check")

    updated = 0
    skipped = 0

    for row in rows:
        (
            opp_id, address, town,
            county, postcode, door_number
        ) = row

        needs_fix = is_bad_address(
            address or '',
            town or '',
            county or '',
            postcode or ''
        )

        if not needs_fix:
            skipped += 1
            continue

        raw = (address or '').strip()

        # Strip postcode from end if embedded in address string
        parsed_postcode = postcode
        postcode_match  = re.search(r'([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})', raw.upper())
        if postcode_match and not parsed_postcode:
            parsed_postcode = postcode_match.group(1)
            raw = raw[:postcode_match.start()].strip().rstrip(',').strip()

        parts = [p.strip() for p in raw.split(',') if p.strip() and p.strip().lower() not in ('nan', 'none')]

        parsed_door    = door_number
        parsed_street  = None
        parsed_town    = town
        parsed_county  = county

        if parts:
            addr_comps = parse_address_components(parts[0])
            if addr_comps['door_number'] and not parsed_door:
                parsed_door = addr_comps['door_number']
            parsed_street = addr_comps['street']

            # With 3+ parts: [...street parts..., town, county]
            if len(parts) >= 3 and not parsed_town:
                parsed_town = parts[-2]
            if len(parts) >= 2 and not parsed_county:
                parsed_county = parts[-1]

            # Middle parts append to street
            if len(parts) > 1:
                middle = parts[1:-2] if len(parts) > 3 else parts[1:-1] if len(parts) > 2 else []
                if middle:
                    parsed_street = ', '.join(
                        [parsed_street] + middle
                    ) if parsed_street else ', '.join(middle)

        # Build clean address from parsed street only (not town/county/postcode)
        clean_address = parsed_street or raw

        updates = {}
        if clean_address and clean_address != (address or ''):
            updates['address'] = clean_address
        if parsed_town and parsed_town != (town or ''):
            updates['town'] = parsed_town
        if parsed_county and parsed_county != (county or ''):
            updates['county'] = parsed_county
        if parsed_door and parsed_door != (door_number or ''):
            updates['door_number'] = parsed_door
        if parsed_postcode and parsed_postcode != (postcode or ''):
            updates['postcode'] = parsed_postcode

        if not updates:
            skipped += 1
            continue

        print(f"  [Lead {opp_id}] {updates}")

        if not dry_run:
            set_clause = ', '.join(f'"{k}" = %s' for k in updates)
            vals = list(updates.values()) + [opp_id]
            cur.execute(
                f'UPDATE "StreemLyne_MT"."Opportunity_Details" SET {set_clause} WHERE opportunity_id = %s',
                vals
            )

        updated += 1

    if not dry_run:
        conn.commit()

    cur.close()
    print(f"[Leads] Done — {updated} updated, {skipped} skipped")
    return updated

# ---------------------------------------------------------------------------
# Fix renewals (Client_Master + Project_Details)
# ---------------------------------------------------------------------------

def fix_renewals(conn, tenant_id: str = None, dry_run: bool = False):
    cur = conn.cursor()

    tenant_filter = "AND cm.tenant_id = %s" if tenant_id else ""
    params = (tenant_id,) if tenant_id else ()

    cur.execute(f"""
        SELECT
            cm.client_id,
            pd.project_id,
            cm.address         AS cm_address,
            pd.address         AS pd_address,
            pd.town,
            pd.county,
            pd.postcode,
            pd.door_number,
            pd.house_number,
            cm.post_code
        FROM "StreemLyne_MT"."Client_Master" cm
        JOIN "StreemLyne_MT"."Project_Details" pd
            ON cm.client_id = pd.client_id
        WHERE cm.is_deleted = FALSE
          AND (cm.address IS NOT NULL OR pd.address IS NOT NULL)
          {tenant_filter}
        ORDER BY cm.client_id
    """, params)

    rows = cur.fetchall()
    print(f"[Renewals] Found {len(rows)} records with address data to check")

    updated = 0
    skipped = 0

    for row in rows:
        (
            client_id, project_id,
            cm_address, pd_address,
            town, county, pd_postcode,
            door_number, house_number,
            cm_postcode
        ) = row

        postcode = pd_postcode or cm_postcode
        raw_addr = pd_address or cm_address or ''

        needs_fix = is_bad_address(
            raw_addr,
            town or '',
            county or '',
            postcode or ''
        )

        if not needs_fix:
            skipped += 1
            continue

        # Strip postcode from end of address string if embedded
        parsed_postcode = postcode
        postcode_match  = re.search(r'([A-Z]{1,2}\d{1,2}[A-Z]?\s*\d[A-Z]{2})', raw_addr.upper())
        if postcode_match and not parsed_postcode:
            parsed_postcode = postcode_match.group(1)
            raw_addr = raw_addr[:postcode_match.start()].strip().rstrip(',').strip()

        parts = [p.strip() for p in raw_addr.split(',') if p.strip() and p.strip().lower() not in ('nan', 'none')]

        parsed_door    = door_number
        parsed_street  = None
        parsed_town    = town
        parsed_county  = county

        if parts:
            addr_comps = parse_address_components(parts[0])
            if addr_comps['door_number'] and not parsed_door and not house_number:
                parsed_door = addr_comps['door_number']
            parsed_street = addr_comps['street']

            if len(parts) >= 3 and not parsed_town:
                parsed_town = parts[-2]
            if len(parts) >= 2 and not parsed_county:
                parsed_county = parts[-1]

            if len(parts) > 1:
                middle = parts[1:-2] if len(parts) > 3 else parts[1:-1] if len(parts) > 2 else []
                if middle:
                    parsed_street = ', '.join(
                        [parsed_street] + middle
                    ) if parsed_street else ', '.join(middle)

        # ── Update Project_Details ────────────────────────────────────────────
        pd_updates = {}
        if parsed_street and parsed_street != (pd_address or ''):
            pd_updates['address'] = parsed_street
        if parsed_town and parsed_town != (town or ''):
            pd_updates['town'] = parsed_town
        if parsed_county and parsed_county != (county or ''):
            pd_updates['county'] = parsed_county
        if parsed_door and parsed_door != (door_number or ''):
            pd_updates['door_number'] = parsed_door
        if parsed_postcode and parsed_postcode != (pd_postcode or ''):
            pd_updates['postcode'] = parsed_postcode

        # ── Update Client_Master ──────────────────────────────────────────────
        cm_updates = {}
        clean_cm_address = parsed_street or cm_address or ''
        if clean_cm_address != (cm_address or ''):
            cm_updates['address'] = clean_cm_address
        if parsed_postcode and parsed_postcode != (cm_postcode or ''):
            cm_updates['post_code'] = parsed_postcode

        if not pd_updates and not cm_updates:
            skipped += 1
            continue

        print(f"  [Renewal client={client_id} project={project_id}] "
              f"PD updates: {pd_updates} | CM updates: {cm_updates}")

        if not dry_run:
            if pd_updates:
                set_clause = ', '.join(f'"{k}" = %s' for k in pd_updates)
                vals = list(pd_updates.values()) + [project_id]
                cur.execute(
                    f'UPDATE "StreemLyne_MT"."Project_Details" SET {set_clause} WHERE project_id = %s',
                    vals
                )
            if cm_updates:
                set_clause = ', '.join(f'"{k}" = %s' for k in cm_updates)
                vals = list(cm_updates.values()) + [client_id]
                cur.execute(
                    f'UPDATE "StreemLyne_MT"."Client_Master" SET {set_clause} WHERE client_id = %s',
                    vals
                )

        updated += 1

    if not dry_run:
        conn.commit()

    cur.close()
    print(f"[Renewals] Done — {updated} updated, {skipped} skipped")
    return updated


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == '__main__':
    TENANT_ID = '2'

    conn = get_raw_connection()

    try:
        print("=== Fixing Leads ===")
        leads_updated = fix_leads(conn, tenant_id=TENANT_ID, dry_run=False)
        print(f"\n=== Complete — {leads_updated} leads fixed ===")

    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        conn.close()