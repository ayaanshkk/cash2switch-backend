# backend/routes/energy_renewals_routes.py

from flask import Blueprint, jsonify, request
from datetime import datetime, timedelta
from sqlalchemy import text
from ..db import SessionLocal
from .auth_helpers import token_required

renewals_bp = Blueprint("renewals", __name__)

@renewals_bp.route("/energy-renewals", methods=["GET"])
@token_required
def get_renewals():
    """
    Get all clients with energy contracts expiring in the next 90 days
    Uses proper schema: Client_Master -> Project_Details -> Energy_Contract_Master
    """
    try:
        db = SessionLocal()
        
        # Get current date and 90 days from now
        today = datetime.now().date()
        ninety_days_later = today + timedelta(days=90)
        
        # Query using your actual schema structure with proper joins
        query = text("""
            SELECT 
                cm.client_id,
                cm.client_contact_name as contact_person,
                cm.client_company_name as business_name,
                cm.client_phone as phone,
                cm.client_email as email,
                sm.supplier_company_name as supplier_name,
                ecm.contract_end_date as end_date,
                pd.Misc_Col2 as annual_usage,
                (ecm.contract_end_date - CURRENT_DATE) as days_until_expiry,
                COALESCE(
                    (SELECT ci.notes 
                     FROM "StreemLyne_MT"."Client_Interactions" ci 
                     WHERE ci.client_id = cm.client_id 
                     ORDER BY ci.contact_date DESC 
                     LIMIT 1),
                    'Pending'
                ) as status,
                em.employee_name as assigned_to_name,
                ecm.unit_rate,
                ecm.mpan_number
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON ecm.employee_id = em.employee_id
            WHERE ecm.contract_end_date IS NOT NULL
            AND ecm.contract_end_date BETWEEN :today AND :ninety_days_later
            ORDER BY ecm.contract_end_date ASC
        """)
        
        result = db.execute(query, {
            "today": today,
            "ninety_days_later": ninety_days_later
        })
        
        renewals = []
        for row in result:
            renewals.append({
                "client_id": row.client_id,
                "contact_person": row.contact_person or "Unknown",
                "business_name": row.business_name or "",
                "phone": row.phone or "",
                "email": row.email or "",
                "supplier_name": row.supplier_name or "Unknown",
                "end_date": row.end_date.isoformat() if row.end_date else None,
                "annual_usage": float(row.annual_usage) if row.annual_usage else 0,
                "days_until_expiry": row.days_until_expiry,
                "status": row.status or "Pending",
                "assigned_to_name": row.assigned_to_name or "Unassigned",
                "mpan_number": row.mpan_number or ""
            })
        
        db.close()
        print(f"✅ Found {len(renewals)} renewals due in next 90 days")
        return jsonify(renewals), 200
        
    except Exception as e:
        print(f"❌ Error fetching renewals: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@renewals_bp.route("/energy-renewals/stats", methods=["GET"])
@token_required
def get_renewal_stats():
    """
    Get renewal statistics for dashboard cards
    """
    try:
        db = SessionLocal()
        today = datetime.now().date()
        
        # Renewals in different time periods with revenue calculations
        stats_query = text("""
            SELECT 
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days' THEN 1 END) as total_renewals_30_days,
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '60 days' THEN 1 END) as total_renewals_60_days,
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days' THEN 1 END) as total_renewals_90_days,
                COALESCE(SUM(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days' 
                    THEN COALESCE(pd.Misc_Col2, 0) * COALESCE(ecm.unit_rate, 0) 
                    ELSE 0 END), 0) as total_revenue_at_risk
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
            WHERE ecm.contract_end_date IS NOT NULL
            AND ecm.contract_end_date >= CURRENT_DATE
        """)
        
        stats_result = db.execute(stats_query).first()
        
        # Contact status from Client_Interactions
        contact_query = text("""
            SELECT 
                COUNT(CASE WHEN latest_interaction.contact_date IS NOT NULL THEN 1 END) as contacted_count,
                COUNT(CASE WHEN latest_interaction.contact_date IS NULL THEN 1 END) as not_contacted_count,
                COUNT(CASE WHEN latest_interaction.notes ILIKE '%renewed%' OR latest_interaction.notes ILIKE '%priced%' THEN 1 END) as renewed_count,
                COUNT(CASE WHEN latest_interaction.notes ILIKE '%lost%' THEN 1 END) as lost_count
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN LATERAL (
                SELECT contact_date, notes
                FROM "StreemLyne_MT"."Client_Interactions" ci
                WHERE ci.client_id = cm.client_id
                ORDER BY ci.contact_date DESC
                LIMIT 1
            ) latest_interaction ON true
            WHERE ecm.contract_end_date IS NOT NULL
            AND ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days'
        """)
        
        contact_result = db.execute(contact_query).first()
        
        stats = {
            "total_renewals_30_days": stats_result.total_renewals_30_days or 0,
            "total_renewals_60_days": stats_result.total_renewals_60_days or 0,
            "total_renewals_90_days": stats_result.total_renewals_90_days or 0,
            "total_revenue_at_risk": float(stats_result.total_revenue_at_risk or 0),
            "contacted_count": contact_result.contacted_count or 0,
            "not_contacted_count": contact_result.not_contacted_count or 0,
            "renewed_count": contact_result.renewed_count or 0,
            "lost_count": contact_result.lost_count or 0
        }
        
        print(f"✅ Stats calculated: {stats}")
        db.close()
        return jsonify(stats), 200
        
    except Exception as e:
        print(f"❌ Error fetching renewal stats: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@renewals_bp.route("/energy-renewals/supplier-breakdown", methods=["GET"])
@token_required
def get_supplier_breakdown():
    """
    Get breakdown of renewals by supplier from Supplier_Master
    """
    try:
        db = SessionLocal()
        
        query = text("""
            SELECT 
                COALESCE(sm.supplier_company_name, 'Unknown') as supplier_name,
                COUNT(*) as renewal_count,
                COALESCE(SUM(COALESCE(pd.Misc_Col2, 0) * COALESCE(ecm.unit_rate, 0)), 0) as total_value
            FROM "StreemLyne_MT"."Energy_Contract_Master" ecm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON ecm.project_id = pd.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            WHERE ecm.contract_end_date IS NOT NULL
            AND ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days'
            GROUP BY sm.supplier_company_name
            ORDER BY total_value DESC
            LIMIT 10
        """)
        
        result = db.execute(query)
        
        breakdown = []
        for row in result:
            breakdown.append({
                "supplier_name": row.supplier_name or "Unknown",
                "renewal_count": row.renewal_count,
                "total_value": float(row.total_value or 0)
            })
        
        print(f"✅ Supplier breakdown: {len(breakdown)} suppliers")
        db.close()
        return jsonify(breakdown), 200
        
    except Exception as e:
        print(f"❌ Error fetching supplier breakdown: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@renewals_bp.route("/energy-renewals/test", methods=["GET"])
def test_renewals_endpoint():
    """
    Test endpoint to verify database connection and schema
    No authentication required for testing
    """
    try:
        db = SessionLocal()
        
        # Test query with proper joins
        test_query = text("""
            SELECT 
                COUNT(DISTINCT cm.client_id) as total_clients,
                COUNT(DISTINCT ecm.energy_contract_master_id) as total_contracts,
                COUNT(CASE WHEN ecm.contract_end_date IS NOT NULL THEN 1 END) as contracts_with_end_date,
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days' THEN 1 END) as renewals_due_90_days,
                COUNT(CASE WHEN ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '30 days' THEN 1 END) as renewals_due_30_days
            FROM "StreemLyne_MT"."Client_Master" cm
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
        """)
        
        result = db.execute(test_query).first()
        
        # Sample data query
        sample_query = text("""
            SELECT 
                cm.client_company_name,
                ecm.contract_end_date,
                sm.supplier_company_name,
                (ecm.contract_end_date - CURRENT_DATE) as days_until_expiry
            FROM "StreemLyne_MT"."Client_Master" cm
            INNER JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            INNER JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm ON pd.project_id = ecm.project_id
            LEFT JOIN "StreemLyne_MT"."Supplier_Master" sm ON ecm.supplier_id = sm.supplier_id
            WHERE ecm.contract_end_date IS NOT NULL
            AND ecm.contract_end_date BETWEEN CURRENT_DATE AND CURRENT_DATE + INTERVAL '90 days'
            ORDER BY ecm.contract_end_date
            LIMIT 5
        """)
        
        sample_result = db.execute(sample_query)
        sample_data = []
        for row in sample_result:
            sample_data.append({
                "company": row.client_company_name,
                "end_date": row.contract_end_date.isoformat() if row.contract_end_date else None,
                "supplier": row.supplier_company_name,
                "days_until_expiry": row.days_until_expiry
            })
        
        response = {
            "status": "success",
            "schema": "StreemLyne_MT",
            "total_clients": result.total_clients,
            "total_contracts": result.total_contracts,
            "contracts_with_end_date": result.contracts_with_end_date,
            "renewals_due_90_days": result.renewals_due_90_days,
            "renewals_due_30_days": result.renewals_due_30_days,
            "sample_renewals": sample_data,
            "message": "Database connection successful! Schema verified."
        }
        
        print(f"✅ Test endpoint result: {response}")
        db.close()
        return jsonify(response), 200
        
    except Exception as e:
        print(f"❌ Test endpoint error: {str(e)}")
        import traceback
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "error": str(e),
            "message": "Database connection failed. Check schema structure."
        }), 500