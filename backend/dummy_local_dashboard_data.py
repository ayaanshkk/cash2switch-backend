"""
Mock dashboard payloads for local UI testing only.

Covers:
  - GET /energy-renewals, /stats, /supplier-breakdown, /period-breakdown,
    /salesperson-performance, /aq-breakdown, /performance, /staff-status-counts
  - GET /employees (admin filters / modals)

Enable in `.env` (do not commit enabled in production):
  LOCAL_DEMO_DASHBOARD=1

Disabled automatically when FLASK_ENV=production.
"""

from __future__ import annotations

import os
from datetime import date, datetime, timedelta
from typing import Any


def local_demo_dashboard_enabled() -> bool:
    if os.getenv("FLASK_ENV", "").strip().lower() == "production":
        return False
    v = os.getenv("LOCAL_DEMO_DASHBOARD", "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _d(days: int) -> date:
    return date.today() + timedelta(days=days)


def _iso(d: date) -> str:
    return d.isoformat()


def dummy_employees_list() -> list[dict[str, Any]]:
    """GET /employees — admin assignment / modal filters."""
    return [
        {"employee_id": 101, "employee_name": "Jordan Lee", "email": "jordan.lee@demo.local"},
        {"employee_id": 102, "employee_name": "Taylor Kim", "email": "taylor.kim@demo.local"},
    ]


def dummy_energy_renewals_list() -> list[dict[str, Any]]:
    """GET /energy-renewals — rows within next 90 days."""
    rows = [
        (9001, "Alex Smith", "Smith Bakery Ltd", "07123456789", "alex@smithbakery.test", "EDF", 22, "Contacted", "Jordan Lee"),
        (9002, "Sam Jones", "Jones Motors", "07211112222", "sam@jones.test", "Yu Energy", 38, "Pending", "Jordan Lee"),
        (9003, "Riley Brown", "Brown Offices", "07333334444", "r@brown.test", "SSE", 55, "Called", "Taylor Kim"),
        (9004, "Morgan White", "White Cold Store", "07444445555", "m.white@test", "BGR Lite", 72, "Not contacted", "Taylor Kim"),
        (9005, "Casey Green", "Green Retail", "07555556666", "casey@green.test", "EDF Energy", 85, "Priced", "Jordan Lee"),
    ]
    out = []
    for cid, contact, biz, phone, email, supplier, days, status, assigned in rows:
        end = _d(days)
        out.append({
            "client_id": cid,
            "contact_person": contact,
            "business_name": biz,
            "phone": phone,
            "mobile_no": "",
            "email": email,
            "supplier_name": supplier,
            "end_date": _iso(end),
            "start_date": _iso(end - timedelta(days=365)),
            "annual_usage": 45000 + (cid % 7) * 1200,
            "days_until_expiry": days,
            "status": status,
            "assigned_to_name": assigned,
            "assigned_to_id": 101 if "Jordan" in assigned else 102,
            "mpan_number": f"00{cid}12345678901",
        })
    return out


def dummy_renewal_stats() -> dict[str, Any]:
    """GET /energy-renewals/stats"""
    return {
        "total_renewals_30_60_days": 107,
        "total_renewals_61_90_days": 80,
        "total_renewals_90_plus_days": 184,
        "expired_contracts": 14,
        "not_due_contracts": 1267,
        "total_revenue_at_risk": 52072000,
        "total_aq": 125000000,
        "contacted_count": 293,
        "not_contacted_count": 4303,
        "renewed_count": 394,
        "lost_count": 16,
    }


def dummy_supplier_breakdown() -> list[dict[str, Any]]:
    """GET /energy-renewals/supplier-breakdown"""
    return [
        {"supplier_name": "EDF", "renewal_count": 412, "total_value": 18500000},
        {"supplier_name": "Yu Energy", "renewal_count": 288, "total_value": 12200000},
        {"supplier_name": "SSE", "renewal_count": 201, "total_value": 9800000},
        {"supplier_name": "BGR Lite", "renewal_count": 156, "total_value": 7600000},
        {"supplier_name": "EDF Energy", "renewal_count": 134, "total_value": 4972000},
    ]


def dummy_period_breakdown(period: str | None) -> dict[str, Any]:
    """GET /energy-renewals/period-breakdown"""
    today = date.today()
    if period == "expired":
        start_date = today - timedelta(days=365 * 5)
        end_date = today - timedelta(days=1)
        renewals = [
            {
                "client_id": 8001,
                "business_name": "Expired Demo Ltd",
                "contact_person": "Pat Expired",
                "phone": "07000000001",
                "email": "pat@expired.test",
                "supplier_name": "EDF",
                "contract_end_date": _iso(today - timedelta(days=12)),
                "days_until_expiry": -12,
                "mpan_number": "0080012345678901",
                "annual_usage": 52000.0,
                "estimated_revenue": 12400.0,
                "assigned_to": "Jordan Lee",
                "status": "Pending",
            }
        ]
    elif period == "30-60":
        start_date = today + timedelta(days=30)
        end_date = today + timedelta(days=60)
        renewals = [
            {
                "client_id": 9001,
                "business_name": "Smith Bakery Ltd",
                "contact_person": "Alex Smith",
                "phone": "07123456789",
                "email": "alex@smithbakery.test",
                "supplier_name": "EDF",
                "contract_end_date": _iso(today + timedelta(days=45)),
                "days_until_expiry": 45,
                "mpan_number": "0090012345678901",
                "annual_usage": 48000.0,
                "estimated_revenue": 15200.0,
                "assigned_to": "Jordan Lee",
                "status": "Contacted",
            }
        ]
    elif period == "61-90":
        start_date = today + timedelta(days=61)
        end_date = today + timedelta(days=90)
        renewals = [
            {
                "client_id": 9004,
                "business_name": "White Cold Store",
                "contact_person": "Morgan White",
                "phone": "07444445555",
                "email": "m.white@test",
                "supplier_name": "BGR Lite",
                "contract_end_date": _iso(today + timedelta(days=72)),
                "days_until_expiry": 72,
                "mpan_number": "0090042345678901",
                "annual_usage": 91000.0,
                "estimated_revenue": 22100.0,
                "assigned_to": "Taylor Kim",
                "status": "Not contacted",
            }
        ]
    elif period == "91-180":
        start_date = today + timedelta(days=91)
        end_date = today + timedelta(days=180)
        renewals = [
            {
                "client_id": 9010,
                "business_name": "Pipeline Demo Co",
                "contact_person": "Jamie Pipe",
                "phone": "07666667777",
                "email": "jamie@pipe.test",
                "supplier_name": "SSE",
                "contract_end_date": _iso(today + timedelta(days=120)),
                "days_until_expiry": 120,
                "mpan_number": "0090102345678901",
                "annual_usage": 67000.0,
                "estimated_revenue": 18900.0,
                "assigned_to": "Jordan Lee",
                "status": "Pending",
            }
        ]
    elif period == "not-due":
        start_date = today + timedelta(days=365)
        end_date = today + timedelta(days=365 * 20)
        renewals = [
            {
                "client_id": 9301,
                "business_name": "Long Term Holdings Ltd",
                "contact_person": "Jamie Long",
                "phone": "07123000001",
                "email": "jamie@longterm.test",
                "supplier_name": "EDF Energy",
                "contract_end_date": _iso(today + timedelta(days=420)),
                "days_until_expiry": 420,
                "mpan_number": "0093012345678901",
                "annual_usage": 48000.0,
                "estimated_revenue": 10080.0,
                "assigned_to": "Jordan Lee",
                "status": "Pending",
            }
        ]
    else:
        start_date = end_date = today
        renewals = []

    total_rev = sum(item["estimated_revenue"] for item in renewals)
    return {
        "period": period or "",
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "total_count": len(renewals),
        "total_revenue": round(total_rev, 2),
        "renewals": renewals,
    }


def dummy_salesperson_performance(period: str) -> dict[str, Any]:
    """GET /energy-renewals/salesperson-performance"""
    today = date.today()
    if period == "week":
        start_date = today - timedelta(days=7)
        period_label = "This Week"
    else:
        start_date = today - timedelta(days=30)
        period_label = "This Month"
    demo_customers = [
        {
            "client_id": 9001,
            "business_name": "Smith Bakery Ltd",
            "contact_person": "Alex Smith",
            "phone": "07123456789",
            "contact_date": datetime.utcnow().isoformat() + "Z",
            "notes": "Demo callback",
            "status": "Contacted",
            "supplier": "EDF",
            "contract_end_date": _iso(_d(40)),
            "annual_usage": 48000.0,
            "estimated_revenue": 15200.0,
        }
    ]
    performance = [
        {
            "employee_id": 101,
            "employee_name": "Jordan Lee",
            "total_contacts": 12,
            "converted_count": 4,
            "total_value_touched": 88000.0,
            "conversion_rate": 33.3,
            "customers_contacted": demo_customers,
        },
        {
            "employee_id": 102,
            "employee_name": "Taylor Kim",
            "total_contacts": 9,
            "converted_count": 3,
            "total_value_touched": 62100.0,
            "conversion_rate": 33.3,
            "customers_contacted": demo_customers,
        },
    ]
    return {
        "period": period,
        "period_label": period_label,
        "start_date": start_date.isoformat(),
        "end_date": today.isoformat(),
        "performance": performance,
    }


def dummy_aq_breakdown() -> dict[str, Any]:
    """GET /energy-renewals/aq-breakdown"""
    return {
        "total_aq": 125000000,
        "total_revenue": 52072000,
        "total_customers": 1204,
        "salesperson_count": 2,
        "breakdown": [
            {
                "employee_id": 101,
                "employee_name": "Jordan Lee",
                "customer_count": 620,
                "total_aq": 68000000,
                "total_revenue": 28200000,
                "average_aq_per_customer": 109677.42,
            },
            {
                "employee_id": 102,
                "employee_name": "Taylor Kim",
                "customer_count": 584,
                "total_aq": 57000000,
                "total_revenue": 23872000,
                "average_aq_per_customer": 97568.49,
            },
        ],
    }


def dummy_renewal_performance() -> dict[str, Any]:
    """GET /energy-renewals/performance"""
    return {
        "renewed_count": 394,
        "contacted_count": 293,
        "not_contacted_count": 4303,
        "lost_count": 16,
        "success_rate": 7.9,
        "total_customers": 5006,
        "employee_id": None,
        "renewed_directly_count": 12,
        "end_date_changed_count": 8,
        "priced_count": 45,
    }


def dummy_staff_status_counts(period: str = "daily") -> list[dict[str, Any]]:
    """GET /energy-renewals/staff-status-counts"""
    key = (period or "daily").strip().lower()
    multiplier = 7 if key == "weekly" else 30 if key == "monthly" else 1
    key = key if key in ("daily", "weekly", "monthly") else "daily"
    return [
        {
            "employee_id": 101,
            "employee_name": "Jordan Lee",
            "total_contacts": 220 * multiplier,
            "renewed_count": 45 * multiplier,
            "converted_count": 45 * multiplier,
            "in_progress_count": 80 * multiplier,
            "not_contacted_count": 85 * multiplier,
            "lost_count": 10 * multiplier,
            "renewed_directly_count": 2,
            "end_date_changed_count": 3,
            "priced_count": 12,
            "conversion_rate": 20,
            "goal_target": 25 * multiplier,
            "goal_achieved": 45 * multiplier,
            "goal_progress_pct": 100,
            "goal_hit": True,
            "period": key,
        },
        {
            "employee_id": 102,
            "employee_name": "Taylor Kim",
            "total_contacts": 198 * multiplier,
            "renewed_count": 18 * multiplier,
            "converted_count": 18 * multiplier,
            "in_progress_count": 72 * multiplier,
            "not_contacted_count": 98 * multiplier,
            "lost_count": 10 * multiplier,
            "renewed_directly_count": 1,
            "end_date_changed_count": 2,
            "priced_count": 9,
            "conversion_rate": 9,
            "goal_target": 25 * multiplier,
            "goal_achieved": 18 * multiplier,
            "goal_progress_pct": 72,
            "goal_hit": False,
            "period": key,
        },
    ]


def _dummy_leads_base() -> list[dict[str, Any]]:
    today = date.today()
    return [
        {
            "opportunity_id": 12001,
            "tenant_lead_id": 5001,
            "business_name": "Atlas Grocers Ltd",
            "contact_person": "Liam Carter",
            "tel_number": "07123400001",
            "mobile_no": "07123400001",
            "email": "liam@atlasgrocers.test",
            "stage_name": "Callback",
            "supplier_name": "EDF",
            "assigned_to_id": 101,
            "assigned_to_name": "Jordan Lee",
            "annual_usage": 52000,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "end_date": (today + timedelta(days=45)).isoformat(),
            "service_name": "utilities",
        },
        {
            "opportunity_id": 12002,
            "tenant_lead_id": 5002,
            "business_name": "Northside Dental",
            "contact_person": "Emma Stone",
            "tel_number": "07123400002",
            "mobile_no": "07123400002",
            "email": "emma@northsidedental.test",
            "stage_name": "Not Answered",
            "supplier_name": "SSE",
            "assigned_to_id": 101,
            "assigned_to_name": "Jordan Lee",
            "annual_usage": 34000,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "end_date": (today + timedelta(days=78)).isoformat(),
            "service_name": "utilities",
        },
        {
            "opportunity_id": 12003,
            "tenant_lead_id": 5003,
            "business_name": "Brookline Pharmacy",
            "contact_person": "Noah Miles",
            "tel_number": "07123400003",
            "mobile_no": "07123400003",
            "email": "noah@brookline.test",
            "stage_name": "Converted",
            "supplier_name": "Yu Energy",
            "assigned_to_id": 102,
            "assigned_to_name": "Taylor Kim",
            "annual_usage": 61000,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "end_date": (today + timedelta(days=110)).isoformat(),
            "service_name": "utilities",
        },
        {
            "opportunity_id": 12004,
            "tenant_lead_id": 5004,
            "business_name": "City Fitness Club",
            "contact_person": "Ava Green",
            "tel_number": "07123400004",
            "mobile_no": "07123400004",
            "email": "ava@cityfitness.test",
            "stage_name": "Lost",
            "supplier_name": "BGR Lite",
            "assigned_to_id": 102,
            "assigned_to_name": "Taylor Kim",
            "annual_usage": 45500,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "end_date": (today + timedelta(days=33)).isoformat(),
            "service_name": "utilities",
        },
        {
            "opportunity_id": 12005,
            "tenant_lead_id": 5005,
            "business_name": "Prime Kitchens",
            "contact_person": "Mason Reed",
            "tel_number": "07123400005",
            "mobile_no": "07123400005",
            "email": "mason@primekitchens.test",
            "stage_name": "Priced",
            "supplier_name": "EDF Energy",
            "assigned_to_id": 101,
            "assigned_to_name": "Jordan Lee",
            "annual_usage": 48900,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "end_date": (today + timedelta(days=390)).isoformat(),
            "service_name": "utilities",
        },
        {
            "opportunity_id": 12006,
            "tenant_lead_id": 5006,
            "business_name": "Westbridge School",
            "contact_person": "Sophia Lane",
            "tel_number": "07123400006",
            "mobile_no": "07123400006",
            "email": "sophia@westbridge.test",
            "stage_name": "Email Only",
            "supplier_name": "EDF",
            "assigned_to_id": 103,
            "assigned_to_name": "Ari Offshore",
            "annual_usage": 92000,
            "created_at": datetime.utcnow().isoformat() + "Z",
            "end_date": (today + timedelta(days=165)).isoformat(),
            "service_name": "utilities",
            "role_id": 5,
        },
    ]


def dummy_leads_list(employee_id: int | None = None) -> list[dict[str, Any]]:
    rows = _dummy_leads_base()
    if employee_id:
        filtered = [r for r in rows if r.get("assigned_to_id") == employee_id]
        if filtered:
            return filtered
        # Fallback for real test accounts not present in static dummy IDs.
        # Use offshore-flavored sample rows but remap assignment to requested employee.
        offshore_seed = [r for r in rows if int(r.get("role_id") or 0) == 5] or rows[:2]
        remapped = []
        for r in offshore_seed:
            x = dict(r)
            x["assigned_to_id"] = employee_id
            x["assigned_to_name"] = x.get("assigned_to_name") or "Offshore Agent"
            x["role_id"] = 5
            remapped.append(x)
        return remapped
    return rows


def dummy_leads_stats(employee_id: int | None = None) -> dict[str, Any]:
    rows = dummy_leads_list(employee_id)
    today = date.today()
    converted = 0
    in_progress = 0
    lost = 0
    new_leads = 0
    stage_breakdown: dict[str, int] = {}
    d_30_60 = d_61_90 = d_91_180 = not_due = 0
    total_usage = 0.0
    for r in rows:
        s = (r.get("stage_name") or "").strip().lower()
        if s in ("converted", "already renewed", "renewed", "renewed directly"):
            converted += 1
        elif s in ("lost", "lost cot", "invalid number", "meter de-energised"):
            lost += 1
        elif s in ("callback", "not answered", "broker in place", "email only", "complaint", "incorrect supplier", "priced", "end date changed"):
            in_progress += 1
        else:
            new_leads += 1
        stage_breakdown[r.get("stage_name") or "Unknown"] = stage_breakdown.get(r.get("stage_name") or "Unknown", 0) + 1
        total_usage += float(r.get("annual_usage") or 0)
        end = date.fromisoformat(r["end_date"])
        days = (end - today).days
        if 30 <= days <= 60:
            d_30_60 += 1
        elif 61 <= days <= 90:
            d_61_90 += 1
        elif 91 <= days <= 180:
            d_91_180 += 1
        elif days >= 365:
            not_due += 1

    total = len(rows)
    return {
        "total_leads": total,
        "active_leads": max(0, total - lost),
        "converted_leads": converted,
        "new_leads": new_leads,
        "in_progress": in_progress,
        "lost_leads": lost,
        "conversion_rate": round((converted / total) * 100, 1) if total else 0,
        "total_value": 0,
        "recent_leads_30d": total,
        "allocated_leads": 0,
        "unallocated_leads": total,
        "stage_breakdown": stage_breakdown,
        "leads_30_60_days": d_30_60,
        "leads_61_90_days": d_61_90,
        "leads_91_180_days": d_91_180,
        "not_due_leads": not_due,
        "total_annual_usage": total_usage,
    }


def dummy_leads_stage_breakdown(employee_id: int | None = None) -> list[dict[str, Any]]:
    stats = dummy_leads_stats(employee_id)
    items = []
    for i, (name, count) in enumerate(stats["stage_breakdown"].items()):
        items.append({"stage_id": i + 1, "stage_name": name, "count": count, "total_value": 0})
    return sorted(items, key=lambda x: x["count"], reverse=True)


def dummy_leads_supplier_breakdown(employee_id: int | None = None) -> list[dict[str, Any]]:
    rows = dummy_leads_list(employee_id)
    m: dict[str, int] = {}
    for r in rows:
        k = r.get("supplier_name") or "Unknown"
        m[k] = m.get(k, 0) + 1
    out = [{"supplier_name": k, "lead_count": v, "total_value": 0} for k, v in m.items()]
    return sorted(out, key=lambda x: x["lead_count"], reverse=True)


def dummy_leads_salesperson_breakdown() -> list[dict[str, Any]]:
    by_emp: dict[int, dict[str, Any]] = {}
    for r in _dummy_leads_base():
        eid = int(r["assigned_to_id"])
        if eid not in by_emp:
            by_emp[eid] = {
                "employee_id": eid,
                "employee_name": r["assigned_to_name"],
                "total_leads": 0,
                "converted_count": 0,
                "in_progress_count": 0,
                "not_contacted_count": 0,
                "lost_count": 0,
                "conversion_rate": 0,
                "total_value": 0,
            }
        by_emp[eid]["total_leads"] += 1
        s = (r.get("stage_name") or "").strip().lower()
        if s in ("converted", "already renewed", "renewed", "renewed directly"):
            by_emp[eid]["converted_count"] += 1
        elif s in ("lost", "lost cot", "invalid number", "meter de-energised"):
            by_emp[eid]["lost_count"] += 1
        elif s in ("callback", "not answered", "broker in place", "email only", "complaint", "incorrect supplier", "priced", "end date changed"):
            by_emp[eid]["in_progress_count"] += 1
        else:
            by_emp[eid]["not_contacted_count"] += 1
    out = []
    for v in by_emp.values():
        total = v["total_leads"] or 1
        v["conversion_rate"] = round((v["converted_count"] / total) * 100, 1)
        out.append(v)
    return sorted(out, key=lambda x: x["total_leads"], reverse=True)


def dummy_leads_by_stage(stage: str, employee_id: int | None = None) -> dict[str, Any]:
    rows = dummy_leads_list(employee_id)
    s = (stage or "").strip().lower()
    out = []
    for r in rows:
        r_stage = (r.get("stage_name") or "").strip().lower()
        if s == "in_progress":
            ok = r_stage in ("callback", "not answered", "broker in place", "email only", "complaint", "incorrect supplier", "priced", "end date changed")
        elif s == "lost":
            ok = r_stage in ("lost", "lost cot", "invalid number", "meter de-energised")
        else:
            ok = r_stage == s
        if ok:
            out.append({
                **r,
                "opportunity_value": 0,
                "days_until_due": (date.fromisoformat(r["end_date"]) - date.today()).days if r.get("end_date") else None,
            })
    return {"leads": out}


def dummy_leads_period_breakdown(period: str, employee_id: int | None = None) -> dict[str, Any]:
    rows = dummy_leads_list(employee_id)
    p = (period or "").strip().lower()
    out = []
    for r in rows:
        if not r.get("end_date"):
            continue
        days = (date.fromisoformat(r["end_date"]) - date.today()).days
        if p == "30-60" and not (30 <= days <= 60):
            continue
        if p == "61-90" and not (61 <= days <= 90):
            continue
        if p == "91-180" and not (91 <= days <= 180):
            continue
        if p == "not-due" and not (days >= 365):
            continue
        out.append({**r, "opportunity_value": 0, "days_until_due": days})
    return {"period": p, "leads": out}


def dummy_leads_staff_performance(period: str = "daily", employee_id: int | None = None) -> list[dict[str, Any]]:
    key = (period or "daily").strip().lower()
    multiplier = 7 if key == "weekly" else 30 if key == "monthly" else 1
    key = key if key in ("daily", "weekly", "monthly") else "daily"
    base = [
        {
            "employee_id": 101,
            "employee_name": "Jordan Lee",
            "role_id": None,
            "total_contacts": 112 * multiplier,
            "converted_count": 36 * multiplier,
            "renewed_count": 36 * multiplier,
            "in_progress_count": 54 * multiplier,
            "not_contacted_count": 18 * multiplier,
            "lost_count": 4 * multiplier,
            "renewed_directly_count": 2 * multiplier,
            "end_date_changed_count": 0,
            "priced_count": 22 * multiplier,
            "conversion_rate": 32,
            "goal_target": 100 * multiplier,
            "goal_achieved": 112 * multiplier,
            "goal_progress_pct": 100,
            "goal_hit": True,
            "period": key,
        },
        {
            "employee_id": 103,
            "employee_name": "Ari Offshore",
            "role_id": 5,
            "total_contacts": 156 * multiplier,
            "converted_count": 44 * multiplier,
            "renewed_count": 44 * multiplier,
            "in_progress_count": 86 * multiplier,
            "not_contacted_count": 20 * multiplier,
            "lost_count": 6 * multiplier,
            "renewed_directly_count": 1 * multiplier,
            "end_date_changed_count": 0,
            "priced_count": 32 * multiplier,
            "conversion_rate": 28,
            "goal_target": 180 * multiplier,
            "goal_achieved": 156 * multiplier,
            "goal_progress_pct": 87,
            "goal_hit": False,
            "period": key,
        },
    ]
    if employee_id:
        matched = [r for r in base if r["employee_id"] == employee_id]
        if matched:
            return matched
        # Ensure demo still works for real offshore accounts with different employee IDs.
        offshore = dict(base[1])
        offshore["employee_id"] = employee_id
        offshore["employee_name"] = "Offshore Agent"
        offshore["role_id"] = 5
        return [offshore]
    return base