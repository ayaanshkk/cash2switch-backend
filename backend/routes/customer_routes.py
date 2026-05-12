"""
Energy Tenant Customer Routes
Multi-table system integrating:
- Client_Master: Core client info
- Project_Details: Site addresses (Misc_Col2 = Annual Usage)
- Energy_Contract_Master: MPAN, Supplier, Contract dates
- Opportunity_Details: Sales pipeline, assigned employee
- Client_Interactions: Callback tracking
"""

from types import SimpleNamespace

from flask import Blueprint, request, jsonify, current_app
from .auth_helpers import token_required
from backend.crm.utils.role_helpers import is_admin_user, is_crm_leads_admin_role
from datetime import datetime
from sqlalchemy import and_, or_, func, text, cast, Float, String
from sqlalchemy.orm import aliased
from ..db import SessionLocal
from ..numeric_parse import safe_float
from ..dummy_local_dashboard_data import dummy_employees_list, local_demo_dashboard_enabled

# ✅ Import all models directly from backend.models
from backend.models import (
    UserMaster,
    Employee_Master,
    Client_Master,
    Project_Details,
    Energy_Contract_Master,
    Client_Interactions,
    Supplier_Master,
    Stage_Master,
    Role_Master
)

energy_customer_bp = Blueprint('energy_customers', __name__)


def _renewals_clients_see_entire_tenant(user) -> bool:
    """Align list visibility with Team Overview: admins see all assignments in tenant."""
    jwt_role = getattr(user, 'role', None)
    if is_crm_leads_admin_role(jwt_role):
        return True
    return bool(is_admin_user(user))


def _energy_contract_proxy_from_ecm_tuple(ecm_flat):
    """
    Stand-in for Energy_Contract_Master without loading full ORM rows (varchar vs Numeric in DB).

    ecm_flat order matches the 20 scalar columns selected from ``ecm_cast`` in ``get_energy_customers``:
    id, project_id, service_id, supplier_id, start, end, mpan, mpan_bottom, terms, aggregator,
    payment, old_supplier, unit_rate_s, standing_charge_s, rate_1_s..rate_3_s, net_notch_s, comms_paid_s, term_sold_s.
    """
    if not ecm_flat or ecm_flat[0] is None:
        return None

    def sf(i):
        return safe_float(ecm_flat[i])

    return SimpleNamespace(
        energy_contract_master_id=ecm_flat[0],
        project_id=ecm_flat[1],
        supplier_id=ecm_flat[3],
        contract_start_date=ecm_flat[4],
        contract_end_date=ecm_flat[5],
        mpan_number=ecm_flat[6],
        mpan_bottom=ecm_flat[7],
        terms_of_sale=ecm_flat[8],
        aggregator=ecm_flat[9],
        payment_type=ecm_flat[10],
        old_supplier_id=ecm_flat[11],
        unit_rate=sf(12),
        standing_charge=sf(13),
        rate_1=sf(14),
        rate_2=sf(15),
        rate_3=sf(16),
        net_notch=sf(17),
        comms_paid=sf(18),
        term_sold=sf(19),
    )


# Must match the scalar column count from ecm_cast in get_energy_customers
_ECM_SELECT_LEN = 20


# ==========================================
# HELPER FUNCTIONS
# ==========================================

def get_tenant_id_from_user(user):
    """Get tenant_id from authenticated user"""
    # ✅ The JWT already contains tenant_id, attached to user object by auth_helpers
    if hasattr(user, 'tenant_id') and user.tenant_id:
        return user.tenant_id
    
    # Fallback: query Employee_Master if not in user object
    session = SessionLocal()
    try:
        employee = session.query(Employee_Master).filter_by(
            employee_id=user.employee_id
        ).first()
        return employee.tenant_id if employee else None
    finally:
        session.close()


def build_customer_response(client, project=None, contract=None, opportunity=None, interaction=None, supplier=None, employee=None, old_supplier=None, stage=None):
    def safe_date_to_iso(date_value):
        if date_value is None:
            return None
        if isinstance(date_value, str):
            return date_value
        if hasattr(date_value, 'isoformat'):
            return date_value.isoformat()
        return str(date_value)
 
    response = {
        # From Client_Master
        'id': client.tenant_client_id,
        'client_id': client.client_id,
        'tenant_client_id': client.tenant_client_id,
        'display_id': client.display_id if hasattr(client, 'display_id') else None,
        'display_order': getattr(client, 'display_order', None),
        'assigned_employee_id': client.assigned_employee_id if hasattr(client, 'assigned_employee_id') else None,
        'name': client.client_contact_name or '',
        'business_name': client.client_company_name or '',
        'contact_person': client.client_contact_name or '',
        'phone': client.client_phone or '',
        'mobile_no': client.client_mobile or '',
        'email': client.client_email or '',
        'address': client.address or '',
        'post_code': client.post_code or '',
        'website': client.client_website or '',
        'created_at': safe_date_to_iso(client.created_at),
        'position': getattr(client, 'position', None),
        'company_number': getattr(client, 'company_number', None),
        'date_of_birth': safe_date_to_iso(getattr(client, 'date_of_birth', None)),
        'charity_ltd_company_number': getattr(client, 'charity_ltd_company_number', None),
        'partner_details': getattr(client, 'partner_details', None),
        'home_door_number': getattr(client, 'home_door_number', None),
        'home_street': getattr(client, 'home_street', None),
        'home_post_code': getattr(client, 'home_post_code', None),
 
        # From Project_Details
        'project_id': project.project_id if project else None,
        'site_address': project.address if project else (client.address if client else None),
        'annual_usage': project.Misc_Col2 if project else None,
        'project_title': project.project_title if project else None,
        'site_name': getattr(project, 'site_name', None) if project else None,
        'month_sold': getattr(project, 'month_sold', None) if project else None,
        'house_name': getattr(project, 'house_name', None) if project else None,
        'house_number': getattr(project, 'house_number', None) if project else None,
        'door_number': getattr(project, 'door_number', None) if project else None,
        'town': getattr(project, 'town', None) if project else None,
        'county': getattr(project, 'county', None) if project else None,
        'project_description': getattr(project, 'project_description', None) if project else None,
 
        # Bank details
        'bank_name': getattr(client, 'bank_name', None),
        'account_number': getattr(client, 'account_number', None),
        'sort_code': getattr(client, 'sort_code', None),
        'bank_account_number': getattr(client, 'account_number', None),
        'bank_sort_code': getattr(client, 'sort_code', None),
 
        # From Energy_Contract_Master
        'contract_id': contract.energy_contract_master_id if contract else None,
        'mpan_mpr': contract.mpan_number if contract else '',
        'mpan_top': contract.mpan_number if contract else None,
        'mpan_bottom': contract.mpan_bottom if contract else None,
        'start_date': safe_date_to_iso(contract.contract_start_date if contract else None),
        'end_date': safe_date_to_iso(contract.contract_end_date if contract else None),
        'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
        'terms_of_sale': contract.terms_of_sale if contract else None,
        'standing_charge': float(contract.standing_charge) if contract and hasattr(contract, 'standing_charge') and contract.standing_charge else None,
        'aggregator': getattr(contract, 'aggregator', None) if contract else None,
        'rate_1': float(contract.rate_1) if contract and hasattr(contract, 'rate_1') and contract.rate_1 else None,
        'payment_type': getattr(contract, 'payment_type', None) if contract else None,
        'net_notch': float(contract.net_notch) if contract and hasattr(contract, 'net_notch') and contract.net_notch else None,
        'term_sold': getattr(contract, 'term_sold', None) if contract else None,
        'rate_2': float(contract.rate_2) if contract and hasattr(contract, 'rate_2') and contract.rate_2 else None,
        'rate_3': float(contract.rate_3) if contract and hasattr(contract, 'rate_3') and contract.rate_3 else None,
        'comms_paid': float(contract.comms_paid) if contract and hasattr(contract, 'comms_paid') and contract.comms_paid else None,
        'document_details': getattr(contract, 'document_details', None) if contract else None,
 
        # From Supplier_Master
        'supplier_id': (supplier.supplier_id if supplier else
                        (contract.supplier_id if contract and hasattr(contract, 'supplier_id') else None)),
        'supplier_name': supplier.supplier_company_name if supplier else '',
        'supplier_contact': supplier.supplier_contact_name if supplier else '',
        'supplier_provisions': supplier.supplier_provisions if supplier else None,
        'old_supplier_id': (old_supplier.supplier_id if old_supplier else
                            (contract.old_supplier_id if contract and hasattr(contract, 'old_supplier_id') else None)),
        'old_supplier_name': old_supplier.supplier_company_name if old_supplier else '',
 
        # ✅ Status and assignment now come from Project_Details
        'status': project.status if project else None,
        'stage_id': None,  # No longer tracked on renewals
        'opportunity_id': None,
        'opportunity_value': None,
        'opportunity_title': None,
 
        # From Employee_Master (via Project_Details.assigned_employee_id)
        'assigned_to_id': employee.employee_id if employee else None,
        'assigned_to_name': employee.employee_name if employee else '',
 
        # From Client_Interactions
        'callback_date': safe_date_to_iso(interaction.reminder_date if interaction else None),
        'last_contact_date': safe_date_to_iso(interaction.contact_date if interaction else None),
        'interaction_notes': interaction.notes if interaction else None,
        'is_allocated': getattr(client, 'is_allocated', False) or False,
    }
 
    return response


def get_user_role_name(user, session):
    """Get the role name for a user from User_Role_Mapping and Role_Master"""
    try:
        from backend.models import Role_Master
        
        # Query User_Role_Mapping to get role_id for this user
        result = session.execute(text("""
            SELECT rm.role_name
            FROM "StreemLyne_MT"."User_Role_Mapping" urm
            JOIN "StreemLyne_MT"."Role_Master" rm ON urm.role_id = rm.role_id
            WHERE urm.user_id = :user_id
            LIMIT 1
        """), {'user_id': user.user_id}).fetchone()
        
        if result:
            return result[0]  # Returns "Platform Admin" or "Salesperson" etc.
        
        return None
        
    except Exception as e:
        current_app.logger.error(f"Error getting user role: {e}")
        return None

# ==========================================
# GET ALL CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
 
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400

        see_all_tenant_clients = _renewals_clients_see_entire_tenant(user)
        if getattr(user, 'employee_id', None) is None and not see_all_tenant_clients:
            return jsonify({'error': 'User has no employee_id; cannot load renewals assignments'}), 400

        # Align with /energy-clients/stats-by-employee and recycle-bin (utilities = 1, water = 2, gas = 3).
        service_param = request.args.get('service') or 'utilities'
        svc = service_param.strip().lower() if isinstance(service_param, str) else 'utilities'
        service_id_map = {'utilities': 1, 'water': 2, 'gas': 3, 'electricity': 1}
        _service_id = service_id_map.get(svc, 1)

        _nm = Energy_Contract_Master
        _ecm_sq = (
            session.query(
                _nm.energy_contract_master_id,
                _nm.project_id,
                _nm.service_id,
                _nm.supplier_id,
                _nm.contract_start_date,
                _nm.contract_end_date,
                _nm.mpan_number,
                _nm.mpan_bottom,
                _nm.terms_of_sale,
                _nm.aggregator,
                _nm.payment_type,
                _nm.old_supplier_id,
                cast(_nm.unit_rate, String).label("unit_rate_s"),
                cast(_nm.standing_charge, String).label("standing_charge_s"),
                cast(_nm.rate_1, String).label("rate_1_s"),
                cast(_nm.rate_2, String).label("rate_2_s"),
                cast(_nm.rate_3, String).label("rate_3_s"),
                cast(_nm.net_notch, String).label("net_notch_s"),
                cast(_nm.comms_paid, String).label("comms_paid_s"),
                cast(_nm.term_sold, String).label("term_sold_s"),
            ).subquery("ecm_cast")
        )
        _ecm_cols = (
            _ecm_sq.c.energy_contract_master_id,
            _ecm_sq.c.project_id,
            _ecm_sq.c.service_id,
            _ecm_sq.c.supplier_id,
            _ecm_sq.c.contract_start_date,
            _ecm_sq.c.contract_end_date,
            _ecm_sq.c.mpan_number,
            _ecm_sq.c.mpan_bottom,
            _ecm_sq.c.terms_of_sale,
            _ecm_sq.c.aggregator,
            _ecm_sq.c.payment_type,
            _ecm_sq.c.old_supplier_id,
            _ecm_sq.c.unit_rate_s,
            _ecm_sq.c.standing_charge_s,
            _ecm_sq.c.rate_1_s,
            _ecm_sq.c.rate_2_s,
            _ecm_sq.c.rate_3_s,
            _ecm_sq.c.net_notch_s,
            _ecm_sq.c.comms_paid_s,
            _ecm_sq.c.term_sold_s,
        )

        latest_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )
        LatestInteraction = aliased(Client_Interactions)

        # ✅ EVERYONE (including admins) only sees their own NON-ALLOCATED contacts
        query = session.query(
            Client_Master,
            Project_Details,
            *_ecm_cols,
            LatestInteraction,
            Supplier_Master,
            Employee_Master,
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            _ecm_sq,
            and_(
                Project_Details.project_id == _ecm_sq.c.project_id,
                _ecm_sq.c.service_id == _service_id,
            ),
        ).outerjoin(
            latest_sq,
            Client_Master.client_id == latest_sq.c.client_id
        ).outerjoin(
            LatestInteraction,
            LatestInteraction.interaction_id == latest_sq.c.max_id
        ).outerjoin(
            Supplier_Master,
            _ecm_sq.c.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                cast(Client_Master.tenant_id, String) == str(tenant_id),
                Client_Master.is_deleted == False,
                Client_Master.is_archived == False,
                *(
                    ()
                    if see_all_tenant_clients
                    else (Project_Details.assigned_employee_id == user.employee_id,)
                ),
                # ✅ CRITICAL: Only show NON-ALLOCATED contacts (not reassigned)
                or_(
                    Client_Master.is_allocated == False,
                    Client_Master.is_allocated == None
                ),
                or_(
                    Project_Details.status == None,
                    ~func.lower(Project_Details.status).in_(['priced', 'lost', 'lost_cot', 'lost cot'])
                ),
            )
        ).order_by(Client_Master.created_at.desc())
 
        results = query.all()
 
        client_ids = list(set(r[0].client_id for r in results))
        assignment_notes_map = {}
        if client_ids:
            try:
                notes_rows = (
                    session.query(Client_Interactions)
                    .filter(
                        Client_Interactions.client_id.in_(client_ids),
                        Client_Interactions.next_steps == 'Assignment',
                    )
                    .order_by(
                        Client_Interactions.client_id,
                        Client_Interactions.created_at.desc().nullslast(),
                    )
                    .all()
                )
                seen_nid = set()
                for nrow in notes_rows:
                    cid = nrow.client_id
                    if cid in seen_nid:
                        continue
                    seen_nid.add(cid)
                    if nrow.notes:
                        parts = nrow.notes.split(' - ', 1)
                        assignment_notes_map[cid] = parts[1] if len(parts) > 1 else nrow.notes
            except Exception as notes_error:
                current_app.logger.warning("assignment notes skipped: %s", notes_error)
 
        customers = []
        seen_clients = set()
 
        n = _ECM_SELECT_LEN
        for row in results:
            client = row[0]
            project = row[1]
            ecm_flat = row[2 : 2 + n]
            interaction = row[2 + n]
            supplier = row[3 + n]
            employee = row[4 + n]
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)

            contract = _energy_contract_proxy_from_ecm_tuple(ecm_flat)
            customer_data = build_customer_response(
                client, project, contract, None, interaction, supplier, employee
            )
            customer_data['assignment_notes'] = assignment_notes_map.get(client.client_id)
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': 'Failed to fetch energy customers'}), 500
    finally:
        session.close()
 
# ==========================================
# GET SINGLE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)

        # Subquery: get only the latest interaction_id per client
        latest_interaction_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )

        LatestInteraction = aliased(Client_Interactions)

        result = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            LatestInteraction,
            Supplier_Master,
            Employee_Master
        ).join(
            Project_Details,
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            latest_interaction_sq,
            Client_Master.client_id == latest_interaction_sq.c.client_id
        ).outerjoin(
            LatestInteraction,
            LatestInteraction.interaction_id == latest_interaction_sq.c.max_id
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master,
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            )
        ).first()

        if not result:
            return jsonify({'error': 'Customer not found'}), 404

        client, project, contract, interaction, supplier, employee = result

        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()

        customer_data = build_customer_response(
            client, project, contract, None, interaction, supplier, employee, old_supplier
        )

        return jsonify(customer_data), 200

    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching energy customer {client_id}: {e}")
        return jsonify({'error': 'Failed to fetch customer'}), 500
    finally:
        session.close()

# ==========================================
# CREATE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients', methods=['POST'])
@token_required
def create_energy_customer():
    session = SessionLocal()
    try:
        data = request.get_json()
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        if not data.get('business_name') and not data.get('contact_person'):
            return jsonify({'error': 'Business name or contact person is required'}), 400
        if not data.get('phone'):
            return jsonify({'error': 'Phone is required'}), 400
 
        assigned_employee_id = data.get('assigned_to_id') or request.current_user.employee_id
        service_string = data.get('service', 'utilities')
        service_id = 1 if service_string == 'utilities' else 2
 
        should_archive, archive_reason = auto_archive_older_contracts(
            session=session,
            tenant_id=tenant_id,
            business_name=data.get('business_name', ''),
            mpan_top=data.get('mpan_top', ''),
            mpan_bottom=data.get('mpan_bottom', ''),
            new_end_date=data.get('end_date'),
            service_id=service_id
        )
 
        # 1. Create Client_Master
        new_client = Client_Master(
            tenant_id=tenant_id,
            assigned_employee_id=assigned_employee_id,
            client_company_name=data.get('business_name', ''),
            client_contact_name=data.get('contact_person', ''),
            address=data.get('address', ''),
            post_code=data.get('post_code', ''),
            client_phone=data.get('phone'),
            client_email=data.get('email', ''),
            client_website=data.get('website', ''),
            default_currency_id=data.get('currency_id', 1),
            is_archived=should_archive,
            archived_at=datetime.utcnow() if should_archive else None,
            archived_reason=archive_reason,
            created_at=datetime.utcnow()
        )
        session.add(new_client)
        session.flush()
        client_id = new_client.client_id

        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
            session.flush()
 
        # 2. Create Project_Details (with assigned_employee_id and status)
        project = Project_Details(
            client_id=client_id,
            project_title=f"Site - {data.get('business_name', 'Unknown')}",
            project_description='Primary site location',
            address=data.get('site_address') or data.get('address', ''),
            Misc_Col2=data.get('annual_usage'),
            employee_id=request.current_user.employee_id,
            assigned_employee_id=assigned_employee_id,
            status=None,                                 
            start_date=data.get('start_date'),
            created_at=datetime.utcnow()
        )
        session.add(project)
        session.flush()
 
        # 3. Create Energy_Contract_Master
        mpan_top = data.get('mpan_top', '').strip()
        mpan_bottom = data.get('mpan_bottom', '').strip()
 
        contract = Energy_Contract_Master(
            project_id=project.project_id,
            employee_id=request.current_user.employee_id,
            supplier_id=data.get('supplier_id'),
            mpan_number=mpan_top,
            mpan_bottom=mpan_bottom,
            contract_start_date=data.get('start_date'),
            contract_end_date=data.get('end_date'),
            unit_rate=data.get('unit_rate') or 0,
            currency_id=data.get('currency_id', 1),
            service_id=service_id,
            terms_of_sale=data.get('terms_of_sale', ''),
            created_at=datetime.utcnow()
        )
        session.add(contract)
        session.flush()
 
        # 4. Client_Interactions (optional)
        if data.get('callback_date'):
            interaction = Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=data.get('notes', 'Initial contact'),
                reminder_date=data.get('callback_date'),
                created_at=datetime.utcnow()
            )
            session.add(interaction)
 
        session.commit()
        session.refresh(new_client)
 
        response_data = build_customer_response(new_client, project, contract)
 
        return jsonify({
            'success': True,
            'message': 'Energy customer created successfully',
            'customer': response_data
        }), 201
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error creating energy customer: {e}")
        return jsonify({'error': f'Failed to create customer: {str(e)}'}), 500
    finally:
        session.close()
        
# ==========================================
# UPDATE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['PUT', 'OPTIONS'])
@token_required
def update_energy_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        data = request.get_json() or {}
        print(f"\n{'='*60}")
        print(f"🔧 UPDATE REQUEST for client {client_id}")
        print(f"   Data: {data}")
        print(f"   User: {request.current_user.employee_id}")
        
        # ✅ CHECK DATABASE BEFORE ANY CHANGES
        check_query = session.execute(text("""
            SELECT cm.assigned_employee_id, pd.assigned_employee_id, cm.is_allocated
            FROM "StreemLyne_MT"."Client_Master" cm
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd ON cm.client_id = pd.client_id
            WHERE cm.client_id = :cid
        """), {'cid': client_id}).fetchone()
        print(f"   DB BEFORE: client_assigned={check_query[0]}, project_assigned={check_query[1]}, is_allocated={check_query[2]}")
        print(f"{'='*60}\n")
        print(f"🔧 UPDATE REQUEST for client {client_id}: {data}")
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id
        ).first()
        if not client:
            return jsonify({'error': 'Customer not found'}), 404

        # Resolve actual client_id for downstream use
        client_id = client.client_id

        # Snapshot latest interaction BEFORE this request mutates history (for append-only updates)
        prev_hist = (
            session.query(Client_Interactions)
            .filter(Client_Interactions.client_id == client_id)
            .order_by(Client_Interactions.interaction_id.desc())
            .first()
        )
        prev_notes_hist = (prev_hist.notes or "") if prev_hist else ""
        prev_reminder_hist = (
            prev_hist.reminder_date.isoformat()[:10]
            if prev_hist and prev_hist.reminder_date
            else None
        )
 
        # Update Client_Master fields
        for field, col in [
            ('business_name', 'client_company_name'),
            ('contact_person', 'client_contact_name'),
            ('phone', 'client_phone'),
            ('mobile_no', 'client_mobile'),
            ('email', 'client_email'),
            ('address', 'address'),
            ('post_code', 'post_code'),
            ('website', 'client_website'),
            ('position', 'position'),
            ('company_number', 'company_number'),
            ('charity_ltd_company_number', 'charity_ltd_company_number'),
            ('partner_details', 'partner_details'),
            ('bank_name', 'bank_name'),
        ]:
            if field in data:
                setattr(client, col, data[field])

        if 'bank_account_number' in data:
            client.account_number = data['bank_account_number']
        elif 'account_number' in data:
            client.account_number = data['account_number']

        if 'bank_sort_code' in data:
            client.sort_code = data['bank_sort_code']
        elif 'sort_code' in data:
            client.sort_code = data['sort_code']

        if 'date_of_birth' in data:
            dob = data['date_of_birth']
            if not dob:
                client.date_of_birth = None
            else:
                if isinstance(dob, str):
                    client.date_of_birth = datetime.fromisoformat(
                        dob.replace('Z', '').split('T')[0]
                    ).date()
                else:
                    client.date_of_birth = dob

        # Update Project_Details
        project = session.query(Project_Details).filter_by(client_id=client_id).first()
        if project:
            for field, col in [('site_address', 'address'), ('annual_usage', 'Misc_Col2'),
                                ('site_name', 'site_name'), ('month_sold', 'month_sold'),
                                ('house_name', 'house_name'), ('house_number', 'house_number'),
                                ('door_number', 'door_number'), ('town', 'town'), ('county', 'county'),
                                ('project_description', 'project_description')]:
                if field in data:
                    setattr(project, col, data[field])

            # ✅ Status now on Project_Details
            if 'status' in data:
                status_value = data['status']
                project.status = None if status_value in ['None', 'null', '', None] else status_value

            # ✅ CRITICAL: Handle assignment SEPARATELY - query fresh data
            if 'assigned_to_id' in data:
                # Flush any pending changes FIRST
                session.flush()
                
                # ✅ RE-QUERY to get fresh assignment data from DB
                fresh_project = session.query(Project_Details).filter_by(client_id=client_id).first()
                old_assigned_to = fresh_project.assigned_employee_id
                new_assigned_to = data['assigned_to_id']
                current_user_employee_id = request.current_user.employee_id
                assignment_notes = data.get('assignment_notes')
                
                print(f"\n📝 Assignment check:")
                print(f"   Old: {old_assigned_to}")
                print(f"   New: {new_assigned_to}")
                print(f"   Current user: {current_user_employee_id}")
                
                # Update assignment on BOTH tables
                project.assigned_employee_id = new_assigned_to
                project.updated_at = datetime.utcnow()
                client.assigned_employee_id = new_assigned_to
                
                # ✅ Determine is_allocated flag
                if new_assigned_to is None:
                    client.is_allocated = False
                    print(f"   ✅ Unassigned - is_allocated = False")
                elif old_assigned_to == new_assigned_to:
                    print(f"   ℹ️  No change in assignment")
                elif new_assigned_to == current_user_employee_id:
                    client.is_allocated = False
                    print(f"   ✅ Assigned to self - is_allocated = False")
                else:
                    client.is_allocated = True
                    print(f"   ✅ Assigned to someone else ({new_assigned_to}) - is_allocated = True")
            else:
                project.updated_at = datetime.utcnow()
                old_assigned_to = None
                new_assigned_to = None
                assignment_notes = None
 
        elif data.get('site_address') or data.get('annual_usage'):
            project = Project_Details(
                client_id=client_id,
                project_title=f"Site - {client.client_company_name}",
                address=data.get('site_address', ''),
                Misc_Col2=data.get('annual_usage'),
                employee_id=request.current_user.employee_id,
                assigned_employee_id=client.assigned_employee_id,
                created_at=datetime.utcnow()
            )
            session.add(project)
            session.flush()
            old_assigned_to = None
            new_assigned_to = None
            assignment_notes = None
        else:
            old_assigned_to = None
            new_assigned_to = None
            assignment_notes = None
 
        # Update Energy_Contract_Master
        if project:
            contract = session.query(Energy_Contract_Master).filter_by(
                project_id=project.project_id
            ).first()
            if contract:
                if 'mpan_mpr' in data: contract.mpan_number = data['mpan_mpr']
                if 'mpan_top' in data: contract.mpan_number = data['mpan_top']
                if 'mpan_bottom' in data: contract.mpan_bottom = data['mpan_bottom']
                if 'supplier_id' in data: contract.supplier_id = data['supplier_id']
                if 'new_supplier' in data and data['new_supplier']:
                    new_supplier_name = data['new_supplier'].strip()
                    matched = session.query(Supplier_Master).filter(
                        Supplier_Master.supplier_company_name.ilike(f'%{new_supplier_name}%')
                    ).first()
                    if matched:
                        if contract.supplier_id and contract.supplier_id != matched.supplier_id:
                            contract.old_supplier_id = contract.supplier_id
                        contract.supplier_id = matched.supplier_id
                    else:
                        new_sup = Supplier_Master(
                            supplier_company_name=new_supplier_name,
                            supplier_contact_name='Auto-created',
                            supplier_provisions=3,
                            created_at=datetime.utcnow()
                        )
                        session.add(new_sup)
                        session.flush()
                        contract.old_supplier_id = contract.supplier_id
                        contract.supplier_id = new_sup.supplier_id
                if 'old_supplier_id' in data:
                    val = data['old_supplier_id']
                    contract.old_supplier_id = None if (val is None or val == 0) else val
                if 'start_date' in data and data['start_date']:
                    contract.contract_start_date = datetime.fromisoformat(
                        data['start_date'].replace('Z', '')
                    ).date() if isinstance(data['start_date'], str) else data['start_date']
                if 'end_date' in data and data['end_date']:
                    contract.contract_end_date = datetime.fromisoformat(
                        data['end_date'].replace('Z', '')
                    ).date() if isinstance(data['end_date'], str) else data['end_date']
                if 'unit_rate' in data and data['unit_rate'] is not None:
                    contract.unit_rate = data['unit_rate']
                if 'terms_of_sale' in data:
                    contract.terms_of_sale = data['terms_of_sale']
                if 'payment_type' in data:
                    contract.payment_type = data['payment_type']
                if 'rate_1' in data and hasattr(contract, 'rate_1'):
                    contract.rate_1 = data['rate_1']
                if 'rate_2' in data and hasattr(contract, 'rate_2'):
                    contract.rate_2 = data['rate_2']
                if 'rate_3' in data and hasattr(contract, 'rate_3'):
                    contract.rate_3 = data['rate_3']
                if 'net_notch' in data and hasattr(contract, 'net_notch'):
                    contract.net_notch = data['net_notch']
                if 'term_sold' in data and hasattr(contract, 'term_sold'):
                    contract.term_sold = data['term_sold']
                if 'comms_paid' in data and hasattr(contract, 'comms_paid'):
                    contract.comms_paid = data['comms_paid']
                if 'aggregator' in data and hasattr(contract, 'aggregator'):
                    contract.aggregator = data['aggregator']
                if 'standing_charge' in data and hasattr(contract, 'standing_charge'):
                    sc = data['standing_charge']
                    contract.standing_charge = None if sc is None else str(sc).strip()
                if 'document_details' in data and hasattr(contract, 'document_details'):
                    contract.document_details = data['document_details']
                contract.updated_at = datetime.utcnow()
 
        # Create assignment interaction if assignment changed
        if 'assigned_to_id' in data and old_assigned_to != new_assigned_to:
            emp = session.query(Employee_Master).filter_by(employee_id=new_assigned_to).first() if new_assigned_to else None
            emp_name = emp.employee_name if emp else "Unassigned"
            note = f"Assigned to {emp_name}"
            if assignment_notes:
                note += f" - {assignment_notes}"
            session.add(Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=note,
                next_steps="Assignment",
                created_at=datetime.utcnow()
            ))
 
        # Append-only history for callback_date / interaction_notes (never UPDATE latest row)
        def _day_only(val):
            if val is None or val == "":
                return None
            s = str(val).replace("Z", "").split("T")[0].strip()
            return s[:10] if len(s) >= 10 else (s or None)

        new_notes = data.get("interaction_notes")
        new_rem = _day_only(data.get("callback_date"))
        notes_changed = (new_notes or "").strip() != prev_notes_hist.strip()
        rd_changed = new_rem != prev_reminder_hist
        if notes_changed or rd_changed:
            note_out = (new_notes or "").strip() if notes_changed else prev_notes_hist.strip()
            rd_obj = None
            if new_rem:
                rd_obj = datetime.fromisoformat(new_rem).date()
            session.add(
                Client_Interactions(
                    client_id=client_id,
                    contact_date=datetime.utcnow().date(),
                    contact_method=1,
                    notes=note_out,
                    reminder_date=rd_obj,
                    next_steps="Record update",
                    created_at=datetime.utcnow(),
                )
            )
 
        session.commit()
        session.expire_all()
 
        # Fetch updated data
        latest_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )
        LatestInteraction = aliased(Client_Interactions)

        updated = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            LatestInteraction, Supplier_Master, Employee_Master
        ).outerjoin(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(latest_sq, Client_Master.client_id == latest_sq.c.client_id
        ).outerjoin(LatestInteraction, LatestInteraction.interaction_id == latest_sq.c.max_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(Client_Master.client_id == client_id).first()

        client, project, contract, interaction, supplier, employee = updated
 
        old_supplier = None
        if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
            old_supplier = session.query(Supplier_Master).filter_by(
                supplier_id=contract.old_supplier_id
            ).first()
 
        response_data = build_customer_response(
            client, project, contract, None, interaction, supplier, employee, old_supplier
        )
 
        return jsonify({'success': True, 'message': 'Customer updated successfully', 'customer': response_data}), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error updating energy customer {client_id}: {e}")
        return jsonify({'error': f'Failed to update customer: {str(e)}'}), 500
    finally:
        session.close()

# ==========================================
# DELETE CUSTOMER
# ==========================================

@energy_customer_bp.route('/energy-clients/<int:client_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_energy_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        # ✅ Try multiple ID fields (display_order, tenant_client_id, client_id)
        client = (
            session.query(Client_Master).filter(
                and_(
                    Client_Master.display_order == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            ).first() or
            session.query(Client_Master).filter(
                and_(
                    Client_Master.tenant_client_id == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            ).first() or
            session.query(Client_Master).filter(
                and_(
                    Client_Master.client_id == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            ).first()
        )
 
        if not client:
            current_app.logger.warning(f"Customer {client_id} not found for deletion")
            return jsonify({'error': 'Customer not found'}), 404
        
        # ✅ Soft delete the customer (move to recycle bin)
        actual_client_id = client.client_id
        
        # Get reason from request body if provided
        try:
            data = request.get_json(silent=True) or {}
            deletion_reason = data.get('reason', 'Manually deleted')
        except Exception:
            deletion_reason = 'Manually deleted'
        
        # Soft delete
        client.is_deleted = True
        client.deleted_at = datetime.utcnow()
        client.deleted_reason = deletion_reason

        session.commit()
        
        current_app.logger.info(f"✅ Soft deleted customer {actual_client_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer moved to recycle bin successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting customer {client_id}: {e}")
        return jsonify({'error': f'Failed to delete customer: {str(e)}'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/drafts', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_draft_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400

        data = request.get_json(silent=True) or {}
        raw_ids = data.get('client_ids') or []
        try:
            client_ids = sorted({int(client_id) for client_id in raw_ids})
        except (TypeError, ValueError):
            return jsonify({'error': 'client_ids must be a list of numbers'}), 400

        if not client_ids:
            return jsonify({'error': 'client_ids are required'}), 400

        deleted_ids = []
        skipped_ids = []

        for client_id in client_ids:
            client = session.query(Client_Master).filter(
                Client_Master.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            ).first()

            if not client:
                skipped_ids.append(client_id)
                continue

            projects = session.query(Project_Details).filter(
                Project_Details.client_id == client.client_id
            ).all()

            client_assigned = bool(getattr(client, 'assigned_employee_id', None))
            project_assigned = any(bool(getattr(project, 'assigned_employee_id', None)) for project in projects)
            if client_assigned or project_assigned:
                skipped_ids.append(client_id)
                continue

            project_ids = [project.project_id for project in projects]
            if project_ids:
                session.query(Energy_Contract_Master).filter(
                    Energy_Contract_Master.project_id.in_(project_ids)
                ).delete(synchronize_session=False)

            session.query(Client_Interactions).filter(
                Client_Interactions.client_id == client.client_id
            ).delete(synchronize_session=False)

            session.query(Project_Details).filter(
                Project_Details.client_id == client.client_id
            ).delete(synchronize_session=False)

            session.delete(client)
            deleted_ids.append(client_id)

        session.commit()

        return jsonify({
            'success': True,
            'deleted_count': len(deleted_ids),
            'deleted_ids': deleted_ids,
            'skipped_ids': skipped_ids,
            'message': f'Deleted {len(deleted_ids)} draft renewals'
        }), 200
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"Error deleting draft energy customers: {e}")
        return jsonify({'error': f'Failed to delete draft renewals: {str(e)}'}), 500
    finally:
        session.close()

# ==========================================
# SEARCH CUSTOMERS
# ==========================================

@energy_customer_bp.route('/energy-clients/search', methods=['GET', 'OPTIONS'])
@token_required
def search_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        if not query_param:
            return jsonify([]), 200
 
        results = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Client_Interactions,
            Supplier_Master,
            Employee_Master,
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_deleted == False,
                or_(
                    Client_Master.client_company_name.ilike(f'%{query_param}%'),
                    Client_Master.client_contact_name.ilike(f'%{query_param}%'),
                    Client_Master.client_phone.ilike(f'%{query_param}%'),
                    Client_Master.client_email.ilike(f'%{query_param}%'),
                    Client_Master.post_code.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_number.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_bottom.ilike(f'%{query_param}%'),
                    Project_Details.site_name.ilike(f'%{query_param}%'),
                    Supplier_Master.supplier_company_name.ilike(f'%{query_param}%')
                )
            )
        ).order_by(Client_Master.client_id.desc()).limit(50).all()
 
        customers = []
        seen_clients = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
 
            old_supplier = None
            if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
                old_supplier = session.query(Supplier_Master).filter_by(
                    supplier_id=contract.old_supplier_id
                ).first()
 
            customer_data = build_customer_response(
                client, project, contract, None, interaction, supplier, employee, old_supplier
            )
 
            if contract:
                customer_data['mpan_top'] = contract.mpan_number or ''
                customer_data['mpan_bottom'] = contract.mpan_bottom or ''
 
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error searching energy customers: {e}")
        return jsonify({'error': 'Failed to search customers'}), 500
    finally:
        session.close()

# ==========================================
# GET STATISTICS
# ==========================================

@energy_customer_bp.route('/energy-clients/stats', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_customer_stats():
    """Get customer statistics"""
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        # Total customers
        total = session.query(Client_Master).filter_by(tenant_id=tenant_id).count()
        
        stage_counts = {}
        
        # By supplier
        supplier_counts = dict(
            session.query(Supplier_Master.supplier_company_name, func.count(Energy_Contract_Master.energy_contract_master_id))
            .join(Energy_Contract_Master, Supplier_Master.supplier_id == Energy_Contract_Master.supplier_id)
            .join(Project_Details, Energy_Contract_Master.project_id == Project_Details.project_id)
            .join(Client_Master, Project_Details.client_id == Client_Master.client_id)
            .filter(Client_Master.tenant_id == tenant_id)
            .group_by(Supplier_Master.supplier_company_name)
            .all()
        )
        
        # Total annual usage (Misc_Col2 may be varchar in DB)
        misc_sq = cast(
            func.nullif(
                func.replace(func.trim(cast(Project_Details.Misc_Col2, String)), ",", ""),
                "",
            ),
            Float,
        )
        total_usage = (
            session.query(func.sum(misc_sq))
            .select_from(Project_Details)
            .join(Client_Master, Project_Details.client_id == Client_Master.client_id)
            .filter(Client_Master.tenant_id == tenant_id)
            .scalar()
            or 0
        )
        
        stats = {
            'total': total,
            'by_stage': stage_counts,
            'by_supplier': supplier_counts,
            'total_annual_usage': float(total_usage)
        }
        
        return jsonify(stats), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching energy customer stats: {e}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500
    finally:
        session.close()

# ==========================================
# HELPER ENDPOINTS
# ==========================================

@energy_customer_bp.route('/suppliers', methods=['GET'])
@token_required
def get_suppliers():
    """Get all energy suppliers"""
    session = SessionLocal()
    try:
        suppliers = session.query(Supplier_Master).all()
        result = [{
            'supplier_id': s.supplier_id,
            'supplier_name': s.supplier_company_name,
            'contact_name': s.supplier_contact_name,
            'provisions': s.supplier_provisions,
            'provisions_text': {
                0: 'Generic',
                1: 'Electricity Only',
                2: 'Gas Only',
                3: 'Electricity & Gas'
            }.get(s.supplier_provisions, 'Unknown')
        } for s in suppliers]
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching suppliers: {e}")
        return jsonify({'error': 'Failed to fetch suppliers'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/stages', methods=['GET'])
@token_required
def get_stages():
    """Get all opportunity stages"""
    session = SessionLocal()
    try:
        stages = session.query(Stage_Master).order_by(Stage_Master.stage_id).all()
        result = [{
            'stage_id': s.stage_id,
            'stage_name': s.stage_name,
            'description': s.stage_description
        } for s in stages]
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching stages: {e}")
        return jsonify({'error': 'Failed to fetch stages'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/employees', methods=['GET'])
@token_required
def get_employees():
    """Get all employees for assignment"""
    if local_demo_dashboard_enabled():
        return jsonify(dummy_employees_list()), 200
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        employees = session.query(Employee_Master).filter_by(tenant_id=tenant_id).all()
        
        result = [{
            'employee_id': e.employee_id,
            'employee_name': e.employee_name,
            'email': e.email
        } for e in employees]
        
        return jsonify(result), 200
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching employees: {e}")
        return jsonify({'error': 'Failed to fetch employees'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/reset-sequence', methods=['POST'])
@token_required
def reset_client_sequence():
    """Reset the client_id sequence to start from 1"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # ✅ FIX: Get user role from User_Role_Mapping
        user_role = get_user_role_name(request.current_user, session)
        
        # Check if user has permission (Platform Admin or Tenant Super Admin)
        if user_role not in ['Platform Admin', 'Tenant Super Admin']:
            return jsonify({'error': 'Permission denied'}), 403
        
        # Get the maximum client_id for this tenant
        max_id = session.query(func.max(Client_Master.client_id)).filter(
            Client_Master.tenant_id == tenant_id
        ).scalar()
        
        # If no clients exist, reset to 1
        if max_id is None:
            max_id = 0
        
        # Reset the sequence
        session.execute(text(
            f'ALTER SEQUENCE "StreemLyne_MT"."Client_Master_client_id_seq" RESTART WITH {max_id + 1}'
        ))
        session.commit()
        
        return jsonify({
            'message': 'Sequence reset successfully',
            'next_id': max_id + 1
        })
        
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error resetting sequence: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/bulk-assign', methods=['POST', 'OPTIONS'])
@token_required
def bulk_assign_clients():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
 
        data = request.get_json()
        client_ids = data.get('client_ids', [])
        employee_id = data.get('employee_id')
        assignment_notes = data.get('assignment_notes')
 
        if not client_ids or not employee_id:
            return jsonify({'error': 'client_ids and employee_id are required'}), 400
 
        employee = session.query(Employee_Master).filter(
            Employee_Master.employee_id == employee_id,
            Employee_Master.tenant_id == tenant_id
        ).first()
        if not employee:
            return jsonify({'error': 'Employee not found'}), 404
 
        old_employee_ids = set()
        updated_count = 0
 
        for cid in client_ids:
            client = session.query(Client_Master).filter(
                Client_Master.client_id == cid,
                Client_Master.tenant_id == tenant_id
            ).first()
            if client:
                if client.assigned_employee_id and client.assigned_employee_id != employee_id:
                    old_employee_ids.add(client.assigned_employee_id)
                    client.is_allocated = True
                client.assigned_employee_id = employee_id
                updated_count += 1
 
            # ✅ Update Project_Details.assigned_employee_id
            projects = session.query(Project_Details).filter(
                Project_Details.client_id == cid
            ).all()
            for project in projects:
                project.assigned_employee_id = employee_id
 
            note = f"Assigned to {employee.employee_name}"
            if assignment_notes:
                note += f" - {assignment_notes}"
            session.add(Client_Interactions(
                client_id=cid,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=note,
                next_steps="Assignment",
                created_at=datetime.utcnow()
            ))
 
        session.commit()
 
        for old_emp_id in old_employee_ids:
            recalculate_display_order(session, tenant_id, old_emp_id)
        recalculate_display_order(session, tenant_id, employee_id)
        session.commit()
 
        return jsonify({
            'success': True,
            'message': f'Successfully assigned {len(client_ids)} clients to {employee.employee_name}',
            'updated_count': updated_count,
            'employee_name': employee.employee_name
        }), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.error(f"Error bulk assigning clients: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/search-all', methods=['GET', 'OPTIONS'])
@token_required
def search_all_energy_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        query_param = request.args.get('q', '').strip()
        service_param = request.args.get('service', 'utilities').strip().lower()
 
        if not query_param:
            return jsonify([]), 200
 
        service_id = {'utilities': 1, 'electricity': 1, 'water': 2, 'gas': 3}.get(service_param, 1)
 
        results = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            Client_Interactions,
            Supplier_Master,
            Employee_Master,
        ).join(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(
            Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.is_deleted == False,
                or_(
                    Energy_Contract_Master.service_id == service_id,
                    Energy_Contract_Master.service_id == None
                ),
                or_(
                    Client_Master.client_company_name.ilike(f'%{query_param}%'),
                    Client_Master.client_contact_name.ilike(f'%{query_param}%'),
                    Client_Master.client_phone.ilike(f'%{query_param}%'),
                    Client_Master.client_email.ilike(f'%{query_param}%'),
                    Client_Master.post_code.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_number.ilike(f'%{query_param}%'),
                    Energy_Contract_Master.mpan_bottom.ilike(f'%{query_param}%'),
                    Project_Details.site_name.ilike(f'%{query_param}%'),
                    Supplier_Master.supplier_company_name.ilike(f'%{query_param}%')
                )
            )
        ).order_by(Client_Master.client_id.desc()).limit(50).all()
 
        customers = []
        seen_clients = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
 
            old_supplier = None
            if contract and hasattr(contract, 'old_supplier_id') and contract.old_supplier_id:
                old_supplier = session.query(Supplier_Master).filter_by(
                    supplier_id=contract.old_supplier_id
                ).first()
 
            customer_data = {
                'id': client.client_id,
                'client_id': client.client_id,
                'display_id': client.tenant_client_id if hasattr(client, 'tenant_client_id') else None,
                'display_order': client.display_order,
                'name': client.client_contact_name or '',
                'business_name': client.client_company_name or '',
                'contact_person': client.client_contact_name or '',
                'phone': client.client_phone or '',
                'email': client.client_email or '',
                'address': client.address or '',
                'site_address': project.address if project else '',
                'mpan_mpr': contract.mpan_number if contract else '',
                'mpan_top': contract.mpan_number if contract else '',
                'mpan_bottom': contract.mpan_bottom if contract else '',
                'supplier_id': contract.supplier_id if contract else None,
                'supplier_name': supplier.supplier_company_name if supplier else '',
                'annual_usage': project.Misc_Col2 if project else None,
                'start_date': contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,
                'end_date': contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
                'unit_rate': float(contract.unit_rate) if contract and contract.unit_rate else None,
                'status': project.status if project else None,  # ✅ from Project_Details
                'stage_id': None,
                'opportunity_id': None,
                'assigned_to_id': project.assigned_employee_id if project else client.assigned_employee_id,  # ✅
                'assigned_to_name': employee.employee_name if employee else None,
                'created_at': client.created_at.isoformat() if client.created_at else None,
                'is_archived': client.is_archived if hasattr(client, 'is_archived') else False,
                'position': getattr(client, 'position', None),
                'company_number': getattr(client, 'company_number', None),
                'site_name': project.site_name if project and hasattr(project, 'site_name') else None,
                'old_supplier_name': old_supplier.supplier_company_name if old_supplier else None,
            }
 
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error in cross-tenant search: {e}")
        return jsonify({'error': 'Failed to search customers'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/priced', methods=['GET', 'OPTIONS'])
@token_required
def get_priced_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
 
        _service_id = None
        service_param = request.args.get('service')
        if service_param:
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc in ('electricity', 'utilities') else None)
 
        salesperson_param = request.args.get('salesperson')
 
        query = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            Client_Interactions, Supplier_Master, Employee_Master
        ).join(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(Client_Interactions, Client_Master.client_id == Client_Interactions.client_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(and_(
            Client_Master.tenant_id == tenant_id,
            func.lower(Project_Details.status) == 'priced',  # ✅ Changed
            *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
        ))
 
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
 
        if is_admin:
            if salesperson_param and salesperson_param != "All":
                try:
                    query = query.filter(
                        Project_Details.assigned_employee_id == int(salesperson_param)  # ✅ Changed
                    )
                except ValueError:
                    pass
        else:
            query = query.filter(
                Project_Details.assigned_employee_id == user.employee_id  # ✅ Changed
            )
 
        results = query.order_by(Client_Master.created_at.desc()).all()
 
        customers = []
        seen_clients = set()
        for client, project, contract, interaction, supplier, employee in results:
            if client.tenant_client_id in seen_clients:
                continue
            seen_clients.add(client.tenant_client_id)
            customers.append(build_customer_response(
                client, project, contract, None, interaction, supplier, employee
            ))
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching priced customers: {e}")
        return jsonify({'error': 'Failed to fetch priced customers'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/stats-by-employee', methods=['GET'])
@token_required
def get_stats_by_employee():
    """Get customer count per employee for Platform Admin"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        if not tenant_id:
            return jsonify({'error': 'Tenant not found'}), 400
        
        # user_role = get_user_role_name(request.current_user, session)
        
        # if user_role not in ['Platform Admin', 'Tenant Super Admin']:
        #     return jsonify({'error': 'Unauthorized - Admin only'}), 403
        
        service_param = request.args.get('service', 'utilities')
        service_id_map = {'utilities': 1, 'water': 2, 'gas': 3}
        service_id = service_id_map.get(service_param.strip().lower(), 1)
        
        sql = text('''
            SELECT 
                em.employee_id,
                em.employee_name,
                COUNT(DISTINCT cm.client_id) as count
            FROM "StreemLyne_MT"."Employee_Master" em
            LEFT JOIN "StreemLyne_MT"."Client_Master" cm 
                ON em.employee_id = cm.assigned_employee_id
                AND cm.tenant_id = :tenant_id
                AND cm.client_company_name != '[IMPORTED LEADS]'
            LEFT JOIN "StreemLyne_MT"."Project_Details" pd 
                ON cm.client_id = pd.client_id
            LEFT JOIN "StreemLyne_MT"."Energy_Contract_Master" ecm 
                ON pd.project_id = ecm.project_id 
                AND ecm.service_id = :service_id
            WHERE em.tenant_id = :tenant_id
                AND ecm.energy_contract_master_id IS NOT NULL
            GROUP BY em.employee_id, em.employee_name
            HAVING COUNT(DISTINCT cm.client_id) > 0
            ORDER BY em.employee_name ASC
        ''')
        
        results = session.execute(sql, {
            'tenant_id': tenant_id,
            'service_id': service_id
        }).mappings().all()
        
        stats = [
            {
                'employee_id': row['employee_id'],
                'employee_name': row['employee_name'],
                'count': int(row['count']) if row['count'] else 0
            }
            for row in results
        ]
        
        return jsonify({'stats': stats}), 200
        
    except Exception as e:
        current_app.logger.error(f"Error fetching employee stats: {str(e)}")
        return jsonify({'error': str(e), 'stats': []}), 500
    finally:
        session.close()

# ==========================================
# RECYCLE BIN ENDPOINTS
# ==========================================

@energy_customer_bp.route('/energy-clients/recycle-bin', methods=['GET', 'OPTIONS'])
@token_required
def get_recycle_bin():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
 
        service_param = request.args.get('service', 'utilities')
        service_id = {'utilities': 1, 'water': 2, 'gas': 3}.get(service_param.strip().lower(), 1)
 
        query = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            Supplier_Master, Employee_Master
        ).join(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id  # ✅ Changed
        ).filter(and_(
            Client_Master.tenant_id == tenant_id,
            Client_Master.is_deleted == True,
            *([Energy_Contract_Master.service_id == service_id] if service_id is not None else [])
        )).filter(
            Project_Details.assigned_employee_id == user.employee_id  # ✅ Changed
        ).order_by(Client_Master.deleted_at.desc())
 
        results = query.all()
        customers = []
        seen_clients = set()
 
        for client, project, contract, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            customer_data = build_customer_response(
                client, project, contract, None, None, supplier, employee
            )
            customer_data['is_deleted'] = True
            customer_data['deleted_at'] = client.deleted_at.isoformat() if client.deleted_at else None
            customer_data['deleted_reason'] = client.deleted_reason
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching recycle bin: {e}")
        return jsonify({'error': 'Failed to fetch recycle bin'}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/restore', methods=['POST', 'OPTIONS'])
@token_required
def restore_customer(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        client = (
            session.query(Client_Master).filter_by(display_order=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(tenant_client_id=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(client_id=client_id, tenant_id=tenant_id).first()
        )
        if client and not client.is_deleted:
            client = None
        if not client:
            return jsonify({'error': 'Customer not found in recycle bin'}), 404

        # Resolve actual client_id for downstream use
        actual_client_id = client.client_id

        assigned_employee_id = client.assigned_employee_id
        client.is_deleted = False
        client.deleted_at = None
        client.deleted_reason = None

        project = session.query(Project_Details).filter_by(client_id=actual_client_id).first()
        if project and project.status:
            project.status = None
 
        session.flush()
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        session.commit()
 
        return jsonify({'success': True, 'message': 'Customer restored successfully'}), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error restoring customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/permanent-delete', methods=['DELETE', 'OPTIONS'])
@token_required
def permanent_delete_customer(client_id):
    """
    Permanently delete a customer from recycle bin.
    HARD DELETE — only works on records already in recycle bin (is_deleted = TRUE).
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)

        client = (
            session.query(Client_Master).filter_by(display_order=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(tenant_client_id=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(client_id=client_id, tenant_id=tenant_id).first()
        )
        # For restore/permanent-delete, also verify the is_deleted flag:
        if client and not client.is_deleted:
            client = None

        if not client:
            return jsonify({'error': 'Customer not found in recycle bin'}), 404

        actual_client_id = client.client_id
        current_app.logger.info(f"🗑️ Permanently deleting customer {client_id}: {client.client_company_name}")

        # 1. Find project IDs
        projects = session.query(Project_Details).filter_by(client_id=client_id).all()
        project_ids = [p.project_id for p in projects]

        # 2. Delete Energy_Contract_Master
        contracts_deleted = 0
        if project_ids:
            contracts_deleted = session.query(Energy_Contract_Master).filter(
                Energy_Contract_Master.project_id.in_(project_ids)
            ).delete(synchronize_session=False)
            current_app.logger.info(f"   📋 Deleted {contracts_deleted} contracts")

        # 3. Delete Client_Interactions
        interactions_deleted = session.query(Client_Interactions).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {interactions_deleted} interactions")

        # 4. Delete Project_Details
        projects_deleted = session.query(Project_Details).filter_by(
            client_id=actual_client_id
        ).delete(synchronize_session=False)
        current_app.logger.info(f"   📋 Deleted {projects_deleted} projects")

        # 5. Delete Client_Master
        session.delete(client)

        session.commit()

        current_app.logger.info(f"✅ Permanently deleted customer {client_id} from recycle bin")

        return jsonify({
            'success': True,
            'message': 'Customer permanently deleted',
            'deleted': {
                'contracts': contracts_deleted,
                'interactions': interactions_deleted,
                'projects': projects_deleted,
                'client': 1
            }
        }), 200

    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error permanently deleting customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/archives', methods=['GET', 'OPTIONS'])
@token_required
def get_archived_customers():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
 
        service_param = request.args.get('service', 'utilities')
        service_id = {'utilities': 1, 'water': 2, 'gas': 3}.get(service_param.strip().lower(), 1)
        salesperson_param = request.args.get('salesperson')
 
        query = session.query(
            Client_Master, Project_Details, Energy_Contract_Master,
            Supplier_Master, Employee_Master
        ).join(Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(Supplier_Master, Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(Employee_Master, Project_Details.assigned_employee_id == Employee_Master.employee_id  # ✅ Changed
        ).filter(and_(
            Client_Master.tenant_id == tenant_id,
            Client_Master.is_archived == True,
            *([Energy_Contract_Master.service_id == service_id] if service_id is not None else [])
        ))
 
        user_role = get_user_role_name(user, session)
        is_admin = user_role in ['Platform Admin', 'Tenant Super Admin']
 
        if is_admin:
            if salesperson_param and salesperson_param != "All":
                try:
                    query = query.filter(
                        Project_Details.assigned_employee_id == int(salesperson_param)  # ✅ Changed
                    )
                except ValueError:
                    pass
        else:
            query = query.filter(
                Project_Details.assigned_employee_id == user.employee_id  # ✅ Changed
            )
 
        results = query.order_by(Energy_Contract_Master.contract_end_date.desc()).all()
        customers = []
        seen_clients = set()
 
        for client, project, contract, supplier, employee in results:
            if client.client_id in seen_clients:
                continue
            seen_clients.add(client.client_id)
            customer_data = build_customer_response(
                client, project, contract, None, None, supplier, employee
            )
            customer_data['is_archived'] = True
            customer_data['archived_at'] = client.archived_at.isoformat() if client.archived_at else None
            customer_data['archived_reason'] = client.archived_reason
            customers.append(customer_data)
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching archives: {e}")
        return jsonify({'error': 'Failed to fetch archives'}), 500
    finally:
        session.close()

@energy_customer_bp.route('/energy-clients/<int:client_id>/archive', methods=['POST', 'OPTIONS'])
@token_required
def archive_customer(client_id):
    """
    Archive a customer record
    Sets is_archived = TRUE and recalculates display_order
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the client
        client = (
            session.query(Client_Master).filter_by(display_order=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(tenant_client_id=client_id, tenant_id=tenant_id).first() or
            session.query(Client_Master).filter_by(client_id=client_id, tenant_id=tenant_id).first()
        )
        # Must not already be archived
        if client and client.is_archived:
            client = None

        if not client:
            return jsonify({'error': 'Customer not found'}), 404
        
        # ✅ Get employee_id BEFORE archiving (for display_order recalculation)
        assigned_employee_id = client.assigned_employee_id
        
        # Archive the customer
        client.is_archived = True
        client.archived_at = datetime.utcnow()
        
        # Get reason from request body if provided
        data = request.get_json() or {}
        client.archived_reason = data.get('reason', 'Manually archived')
        
        # Commit the archive change
        session.flush()
        
        # ✅ Recalculate display_order for the employee who lost this record
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        
        session.commit()
        
        current_app.logger.info(f"✅ Archived customer {client_id}")
        current_app.logger.info(f"✅ Recalculated display_order for employee_id={assigned_employee_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer archived successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error archiving customer: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@energy_customer_bp.route('/energy-clients/<int:client_id>/unarchive', methods=['POST', 'OPTIONS'])
@token_required
def unarchive_customer(client_id):
    """
    Restore a customer from archives
    Sets is_archived = FALSE, clears archive metadata, and recalculates display_order
    """
    
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Find the archived client
        client = session.query(Client_Master).filter_by(
            client_id=client_id,
            tenant_id=tenant_id,
            is_archived=True  # Must be in archives
        ).first()
        
        if not client:
            return jsonify({'error': 'Customer not found in archives'}), 404
        
        # ✅ Get employee_id for display_order recalculation
        assigned_employee_id = client.assigned_employee_id
        
        # Restore the customer
        client.is_archived = False
        client.archived_at = None
        client.archived_reason = None
        
        # Commit the unarchive change
        session.flush()
        
        # ✅ Recalculate display_order for the employee who gained this record
        if assigned_employee_id:
            recalculate_display_order(session, tenant_id, assigned_employee_id)
        
        session.commit()
        
        current_app.logger.info(f"✅ Restored customer {client_id} from archives")
        current_app.logger.info(f"✅ Recalculated display_order for employee_id={assigned_employee_id}")
        
        return jsonify({
            'success': True,
            'message': 'Customer restored from archives successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error restoring customer from archives: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


def auto_archive_older_contracts(session, tenant_id, business_name, mpan_top, mpan_bottom, new_end_date, service_id, new_client_id=None):
    """
    Automatically archive older contracts when a newer one is created
    Returns: (should_archive_new, reason)
    """
    if not new_end_date:
        return False, None
    
    # Find existing records for this customer (by MPAN or business name)
    existing_query = session.query(
        Client_Master,
        Project_Details,
        Energy_Contract_Master
    ).join(
        Project_Details,
        Client_Master.client_id == Project_Details.client_id
    ).join(
        Energy_Contract_Master,
        Project_Details.project_id == Energy_Contract_Master.project_id
    ).filter(
        Client_Master.tenant_id == tenant_id,
        Energy_Contract_Master.service_id == service_id,
        Client_Master.is_deleted == False  # Don't consider deleted records
    )
    
    # Exclude the new client if it already exists (for updates)
    if new_client_id:
        existing_query = existing_query.filter(Client_Master.client_id != new_client_id)
    
    # Match by MPAN or business name
    if mpan_top or mpan_bottom:
        existing_query = existing_query.filter(
            or_(
                Energy_Contract_Master.mpan_number == mpan_top,
                Energy_Contract_Master.mpan_bottom == mpan_bottom
            )
        )
    elif business_name:
        existing_query = existing_query.filter(
            Client_Master.client_company_name == business_name
        )
    else:
        return False, None
    
    existing_records = existing_query.all()
    
    if not existing_records:
        return False, None
    
    # Convert new_end_date to date object if it's a string
    if isinstance(new_end_date, str):
        try:
            new_end_date = datetime.fromisoformat(new_end_date.replace('Z', '+00:00')).date()
        except:
            return False, None
    
    # Find the latest end date among existing records
    latest_end_date = None
    latest_client = None
    
    for client, project, contract in existing_records:
        if contract.contract_end_date:
            if latest_end_date is None or contract.contract_end_date > latest_end_date:
                latest_end_date = contract.contract_end_date
                latest_client = client
    
    if not latest_end_date:
        return False, None
    
    # If this NEW record's end date is OLDER than the latest existing, archive the NEW one
    if new_end_date < latest_end_date:
        current_app.logger.info(
            f"📦 Auto-archiving NEW record: {business_name} - "
            f"End date {new_end_date} is older than existing {latest_end_date}"
        )
        return True, f"Older contract - superseded by existing contract ending {latest_end_date}"
    
    # If this NEW record's end date is NEWER than existing, archive the OLD ones
    elif new_end_date > latest_end_date:
        archived_count = 0
        # ✅ Track employee IDs for display_order recalculation
        affected_employee_ids = set()
        
        for client, project, contract in existing_records:
            if not client.is_archived and contract.contract_end_date and contract.contract_end_date < new_end_date:
                # ✅ Track the employee ID before archiving
                if client.assigned_employee_id:
                    affected_employee_ids.add(client.assigned_employee_id)
                
                client.is_archived = True
                client.archived_at = datetime.utcnow()
                client.archived_reason = f"Superseded by newer contract ending {new_end_date}"
                archived_count += 1
                current_app.logger.info(
                    f"📦 Auto-archiving OLD record: {business_name} (ID: {client.client_id}) - "
                    f"Old end date {contract.contract_end_date} < New end date {new_end_date}"
                )
        
        if archived_count > 0:
            current_app.logger.info(f"✅ Archived {archived_count} older contract(s)")
            
            # ✅ Recalculate display_order for all affected employees
            session.flush()
            for employee_id in affected_employee_ids:
                recalculate_display_order(session, tenant_id, employee_id)
                current_app.logger.info(f"✅ Recalculated display_order for employee_id={employee_id} after auto-archive")
    
    return False, None

def recalculate_display_order(session, tenant_id, employee_id=None):
    """
    Recalculate display_order starting from 1 PER EMPLOYEE.
    Uses ROW_NUMBER() OVER (PARTITION BY assigned_employee_id ORDER BY created_at)
    so each salesperson's list always starts at 1.
    """
    if employee_id:
        # Recalculate only for this specific employee
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Client_Master" cm
            SET display_order = sub.rn
            FROM (
                SELECT client_id,
                       ROW_NUMBER() OVER (ORDER BY created_at ASC) AS rn
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                  AND assigned_employee_id = :employee_id
                  AND is_deleted = FALSE
                  AND is_archived = FALSE
            ) sub
            WHERE cm.client_id = sub.client_id
        """), {'tenant_id': tenant_id, 'employee_id': employee_id})
    else:
        # Recalculate for ALL employees at once using PARTITION BY
        session.execute(text("""
            UPDATE "StreemLyne_MT"."Client_Master" cm
            SET display_order = sub.rn
            FROM (
                SELECT client_id,
                       ROW_NUMBER() OVER (
                           PARTITION BY assigned_employee_id
                           ORDER BY created_at ASC
                       ) AS rn
                FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_id = :tenant_id
                  AND is_deleted = FALSE
                  AND is_archived = FALSE
            ) sub
            WHERE cm.client_id = sub.client_id
        """), {'tenant_id': tenant_id})
    
    session.flush()
    current_app.logger.info(
        f"✅ Recalculated display_order per-employee "
        f"(tenant={tenant_id}, employee={employee_id or 'ALL'})"
    )

@energy_customer_bp.route('/energy-clients/allocated', methods=['GET', 'OPTIONS'])
@token_required
def get_allocated_contacts():
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        user = request.current_user
        
        if not tenant_id:
            return jsonify({'error': 'Tenant not found for user'}), 400
        
        _service_id = None
        service_param = request.args.get('service')
        if service_param and isinstance(service_param, str):
            svc = service_param.strip().lower()
            _service_id = 2 if svc == 'water' else (1 if svc == 'electricity' else None)
 
        latest_sq = (
            session.query(
                Client_Interactions.client_id,
                func.max(Client_Interactions.interaction_id).label('max_id')
            )
            .group_by(Client_Interactions.client_id)
            .subquery()
        )
        LatestInteraction = aliased(Client_Interactions)

        # ✅ Show contacts that are:
        # 1. Assigned to THIS user (Project_Details.assigned_employee_id)
        # 2. Marked as allocated (is_allocated = True)
        query = session.query(
            Client_Master,
            Project_Details,
            Energy_Contract_Master,
            LatestInteraction,
            Supplier_Master,
            Employee_Master
        ).join(
            Project_Details, 
            Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master, 
            Project_Details.project_id == Energy_Contract_Master.project_id
        ).outerjoin(
            latest_sq,
            Client_Master.client_id == latest_sq.c.client_id
        ).outerjoin(
            LatestInteraction,
            LatestInteraction.interaction_id == latest_sq.c.max_id
        ).outerjoin(
            Supplier_Master, 
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id
        ).outerjoin(
            Employee_Master, 
            Project_Details.assigned_employee_id == Employee_Master.employee_id
        ).filter(
            and_(
                Client_Master.tenant_id == tenant_id,
                Client_Master.is_deleted == False,
                Client_Master.is_archived == False,
                # ✅ Assigned to THIS user
                Project_Details.assigned_employee_id == user.employee_id,
                # ✅ Marked as allocated
                Client_Master.is_allocated == True,
                or_(
                    Project_Details.status == None,
                    ~func.lower(Project_Details.status).in_(['priced', 'lost', 'lost_cot', 'lost cot'])
                ),
                *([Energy_Contract_Master.service_id == _service_id] if _service_id is not None else [])
            )
        ).order_by(Client_Master.display_order.asc())
 
        results = query.all()
        
        customers = []
        seen = set()
 
        for client, project, contract, interaction, supplier, employee in results:
            if client.tenant_client_id in seen:
                continue
            seen.add(client.tenant_client_id)
            customers.append(build_customer_response(
                client, project, contract, None, interaction, supplier, employee
            ))
 
        return jsonify(customers), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching allocated contacts: {e}")
        return jsonify({'error': 'Failed to fetch allocated contacts'}), 500
    finally:
        session.close()
