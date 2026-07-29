"""
Updated Callback Route - backend/routes/client_interactions_routes.py
✅ Status now stored in Project_Details.status (not Opportunity_Details.Misc_Col1)
✅ Invalid Number + Incorrect Supplier → soft-delete with is_cleansing=True (go to Cleansing page, not recycle bin)
✅ FIX: OPTIONS preflight requests pass through before @token_required check
"""
 
from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import and_, text
from backend.models import Client_Interactions, Client_Master, Energy_Contract_Master, Project_Details, Supplier_Master
from backend.db import SessionLocal, safe_add_with_sequence_retry
from backend.routes.auth_routes import token_required
 
client_interaction_bp = Blueprint('client_interactions', __name__)
 
 
def get_tenant_id_from_user(user):
    for attr in ('tenant_id', 'Tenant_ID', 'tenantId', 'tenant'):
        val = getattr(user, attr, None)
        if val is not None:
            return val
    # Fallback: check __dict__ directly
    if hasattr(user, '__dict__'):
        for k, v in user.__dict__.items():
            if 'tenant' in k.lower() and v is not None:
                return v
    return None
 
 
# ── Statuses that go to Cleansing page (soft-delete with is_cleansing=True) ──
CLEANSING_STATUSES = {"Invalid Number", "Incorrect Supplier"}
 
# ── Statuses that go to Recycle Bin (soft-delete with is_cleansing=False) ────
RECYCLE_BIN_STATUSES = {"Lost", "Lost COT", "Meter De-energised", "Complaint", "Duplicate", "Dead"}


# ── Helper: return CORS preflight response immediately (before auth check) ──
def _preflight():
    """Return a 200 OK for OPTIONS preflight requests."""
    resp = jsonify({})
    resp.status_code = 200
    return resp


@client_interaction_bp.route('/energy-clients/<int:client_id>/callback', methods=['POST', 'OPTIONS'])
@token_required
def add_callback(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()

    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        data = request.get_json()

        status = data.get('status')
        callback_date = data.get('callback_date')
        notes = data.get('notes', '')
        is_sold = data.get('is_sold')
        new_end_date_str = data.get('new_end_date')
        new_supplier = data.get('new_supplier')
        new_address = data.get('new_address')
        renewed_by = data.get('renewed_by')

        print(f"📥 Callback for client_id param {client_id} — status: {status}")

        # ✅ Resolve real client — URL param may be display_order or tenant_client_id
        client = session.query(Client_Master).filter(
            Client_Master.client_id == client_id
        ).first()

        if not client:
            row = session.execute(text("""
                SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                WHERE display_order = :did
                AND (:tid IS NULL OR CAST(tenant_id AS VARCHAR) = CAST(:tid AS VARCHAR))
                LIMIT 1
            """), {'did': client_id, 'tid': str(tenant_id) if tenant_id else None}).fetchone()
            if row:
                client = session.query(Client_Master).filter(
                    Client_Master.client_id == row[0]
                ).first()

        if not client:
            row = session.execute(text("""
                SELECT client_id FROM "StreemLyne_MT"."Client_Master"
                WHERE tenant_client_id = :tid_cid
                AND (:tid IS NULL OR CAST(tenant_id AS VARCHAR) = CAST(:tid AS VARCHAR))
                LIMIT 1
            """), {'tid_cid': client_id, 'tid': str(tenant_id) if tenant_id else None}).fetchone()
            if row:
                client = session.query(Client_Master).filter(
                    Client_Master.client_id == row[0]
                ).first()

        if not client:
            print(f"❌ Client not found for id={client_id}, tenant={tenant_id}")
            return jsonify({'error': f'Customer not found (id={client_id})'}), 404

        # ✅ Use real client_id for ALL subsequent DB operations
        real_client_id = client.client_id
        print(f"✅ Resolved client_id param {client_id} → real client_id {real_client_id}")



        status_config = {
            "Callback":           {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Not Answered":       {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Priced":             {"requires_date": False, "requires_sold": True,  "deletes_record": False, "requires_notes": False},
            "Sold":               {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Lost":               {"requires_date": True,  "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Lost COT":           {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Already Renewed":    {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Invalid Number":     {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Meter De-energised": {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Broker in Place":    {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "End Date Changed":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Complaint":          {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Email Only":         {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Renewed Directly":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Incorrect Supplier": {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Converted":          {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Not Called":         {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Dead":               {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Duplicate":          {"requires_date": False, "requires_sold": False, "deletes_record": True, "requires_notes": False},
        }

        if not status:
            return jsonify({'error': 'Status is required'}), 400

        if status not in status_config:
            return jsonify({'error': 'Invalid status'}), 400

        config = status_config[status]

        if config["requires_notes"] and not notes.strip():
            return jsonify({'error': f'Please enter the reason for {status}'}), 400

        if status == "Renewed Directly" and not new_end_date_str:
            return jsonify({'error': 'Please enter the new contract end date'}), 400

        date_required = False
        if config["requires_sold"]:
            if is_sold is None:
                return jsonify({'error': 'Please select if the contract was sold'}), 400
            date_required = is_sold
        else:
            date_required = config["requires_date"]

        if date_required and not callback_date:
            return jsonify({'error': 'Callback date is required for this status'}), 400

        # ── Fetch project once, used throughout ───────────────────────────────
        project = session.query(Project_Details).filter_by(client_id=real_client_id).first()
        old_status = project.status if project else None

        # ── Soft delete: Cleansing OR Recycle Bin ─────────────────────────────
        if config["deletes_record"]:
            try:
                is_cleansing = status in CLEANSING_STATUSES

                client.is_deleted = True
                client.deleted_at = datetime.utcnow()
                client.deleted_reason = status
                if hasattr(client, 'is_cleansing'):
                    client.is_cleansing = is_cleansing

                if project:
                    project.status = status

                formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
                if old_status != status:
                    formatted_notes = f"[{status}] Status: {old_status or 'None'} → {status}" + (f" | {notes}" if notes else "")

                safe_add_with_sequence_retry(
                    session,
                    Client_Interactions(
                        client_id=real_client_id,
                        contact_date=datetime.utcnow().date(),
                        contact_method=1,
                        reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                        notes=formatted_notes,
                        next_steps=status,
                        created_at=datetime.utcnow()
                    ))

                session.commit()

                if is_cleansing:
                    print(f"✅ Moved client {real_client_id} to Cleansing ({status})")
                    return jsonify({
                        'success': True,
                        'message': f'Moved to Cleansing ({status})',
                        'deleted': False,
                        'moved_to_cleansing': True,
                        'moved_to_recycle_bin': False,
                    }), 200
                else:
                    print(f"✅ Moved client {real_client_id} to recycle bin ({status})")
                    return jsonify({
                        'success': True,
                        'message': f'Moved to recycle bin ({status})',
                        'deleted': False,
                        'moved_to_cleansing': False,
                        'moved_to_recycle_bin': True,
                    }), 200

            except Exception as e:
                session.rollback()
                print(f"❌ Error moving to cleansing/recycle bin: {e}")
                return jsonify({'error': f'Failed to move record: {str(e)}'}), 500

        # ── Already Renewed ────────────────────────────────────────────────────
        if status == "Already Renewed":
            try:
                changes_made = []

                contract = session.query(Energy_Contract_Master).select_from(Client_Master).join(
                    Project_Details, Client_Master.client_id == Project_Details.client_id
                ).join(
                    Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
                ).filter(Client_Master.client_id == real_client_id).first()

                if not contract:
                    return jsonify({'error': 'Contract not found'}), 404

                if new_end_date_str:
                    new_end_date = datetime.strptime(new_end_date_str, '%Y-%m-%d').date()
                    old_end_date = contract.contract_end_date
                    contract.contract_end_date = new_end_date
                    contract.updated_at = datetime.utcnow()
                    session.flush()
                    changes_made.append(
                        f"End date: {old_end_date.strftime('%d/%m/%Y') if old_end_date else 'None'} → {new_end_date.strftime('%d/%m/%Y')}"
                    )

                if new_supplier and new_supplier.strip():
                    supplier = session.query(Supplier_Master).filter(
                        Supplier_Master.supplier_company_name.ilike(new_supplier.strip())
                    ).first()
                    if not supplier:
                        supplier = Supplier_Master(
                            supplier_company_name=new_supplier.strip(),
                            supplier_contact_name=new_supplier.strip(),
                            supplier_provisions=0,
                            created_at=datetime.utcnow()
                        )
                        session.add(supplier)
                        session.flush()

                    old_sup = session.query(Supplier_Master).filter_by(
                        supplier_id=contract.supplier_id
                    ).first() if contract.supplier_id else None
                    old_supplier_name = old_sup.supplier_company_name if old_sup else 'None'

                    contract.supplier_id = supplier.supplier_id
                    contract.updated_at = datetime.utcnow()
                    session.flush()
                    changes_made.append(f"Supplier: {old_supplier_name} → {new_supplier}")

                if new_address and new_address.strip():
                    client.address = new_address.strip()
                    if project:
                        project.address = new_address.strip()
                    changes_made.append("Address updated")

                session.flush()

                if changes_made:
                    summary = " | ".join(changes_made)
                    notes = f"{notes.strip()} | {summary}".strip(" |") if notes.strip() else summary

                final_status = None
                if renewed_by == 'customer':
                    final_status = 'Renewed Directly'
                    notes = f"[Renewed by Customer] {notes}".strip() if notes else "[Renewed by Customer]"
                elif renewed_by == 'agent':
                    final_status = 'Already Renewed'
                    notes = f"[Renewed by Agent] {notes}".strip() if notes else "[Renewed by Agent]"
                else:
                    final_status = 'Already Renewed'

                if project:
                    project.status = final_status
                    if old_status != final_status:
                        changes_made.append(f"Status: {old_status or 'None'} → {final_status}")

                formatted_notes = f"[{final_status}] {notes}" if notes else f"[{final_status}]"
                safe_add_with_sequence_retry(
                    session,
                    Client_Interactions(
                        client_id=real_client_id,
                        contact_date=datetime.utcnow().date(),
                        contact_method=1,
                        reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                        notes=formatted_notes,
                        next_steps=final_status,
                        created_at=datetime.utcnow()
                    ))

                session.commit()
                print(f"✅ Callback saved for real_client_id {real_client_id}, status: {final_status}")
                return jsonify({
                    'success': True,
                    'message': 'Callback saved successfully',
                    'status': final_status,
                    'callback_date': callback_date
                }), 200

            except Exception as e:
                session.rollback()
                import traceback; traceback.print_exc()
                return jsonify({'error': f'Failed to update information: {str(e)}'}), 500

        # ── End Date Changed ───────────────────────────────────────────────────
        elif status in ("End Date Changed", "Renewed Directly") and new_end_date_str:
            try:
                new_end_date = datetime.strptime(new_end_date_str, '%Y-%m-%d').date()

                contract = session.query(Energy_Contract_Master).select_from(Client_Master).join(
                    Project_Details, Client_Master.client_id == Project_Details.client_id
                ).join(
                    Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
                ).filter(Client_Master.client_id == real_client_id).first()

                if contract:
                    old_end_date = contract.contract_end_date
                    contract.contract_end_date = new_end_date
                    contract.updated_at = datetime.utcnow()
                    session.flush()
                    session.refresh(contract)

                    old_fmt = old_end_date.strftime('%d/%m/%Y') if old_end_date else 'None'
                    new_fmt = new_end_date.strftime('%d/%m/%Y')
                    notes = f"Old end date: {old_fmt} → New end date: {new_fmt}"
                    if data.get('notes', '').strip():
                        notes = f"{data.get('notes').strip()} | {notes}"

                    if status == "End Date Changed":
                        callback_date = new_end_date_str

            except Exception as e:
                session.rollback()
                import traceback; traceback.print_exc()
                return jsonify({'error': f'Failed to update end date: {str(e)}'}), 500

        # ── Update Project_Details.status for all remaining statuses ──────────
        if project:
            project.status = status

        # ── Priced with No (move to priced page) ──────────────────────────────
        if status == "Priced" and not is_sold:
            formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
            if old_status != status:
                formatted_notes = f"[{status}] Status: {old_status or 'None'} → {status}" + (f" | {notes}" if notes else "")
            safe_add_with_sequence_retry(
                session,
                Client_Interactions(
                    client_id=real_client_id,
                    contact_date=datetime.utcnow().date(),
                    contact_method=1,
                    notes=formatted_notes,
                    next_steps=status,
                    created_at=datetime.utcnow()
                ))
            session.commit()
            return jsonify({
                'success': True,
                'message': 'Moved to Priced page',
                'moved_to_priced': True
            }), 200

        # ── Create interaction record ──────────────────────────────────────────
        formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
        if old_status != status:
            transition = f"Status: {old_status or 'None'} → {status}"
            formatted_notes = f"[{status}] {transition}" + (f" | {notes}" if notes else "")

        safe_add_with_sequence_retry(
            session,
            Client_Interactions(
                client_id=real_client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                notes=formatted_notes,
                next_steps=status,
                created_at=datetime.utcnow()
            )
        )

        session.commit()
        print(f"✅ Callback saved for real_client_id {real_client_id}, status: {status}")

        return jsonify({
            'success': True,
            'message': 'Callback saved successfully',
            'status': status,
            'callback_date': callback_date
        }), 200

    except Exception as e:
        session.rollback()
        print(f"❌ Error saving callback: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
 
# ══════════════════════════════════════════════════════════════════
# GET /api/energy-clients/cleansing
# ══════════════════════════════════════════════════════════════════
 
@client_interaction_bp.route('/energy-clients/cleansing', methods=['GET', 'OPTIONS'])
@token_required
def get_energy_clients_for_cleansing(client_id=None):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        query = session.query(
            Client_Master,
            Energy_Contract_Master,
            Supplier_Master,
        ).outerjoin(
            Project_Details, Client_Master.client_id == Project_Details.client_id
        ).outerjoin(
            Energy_Contract_Master,
            Project_Details.project_id == Energy_Contract_Master.project_id,
        ).outerjoin(
            Supplier_Master,
            Energy_Contract_Master.supplier_id == Supplier_Master.supplier_id,
        ).filter(
            Client_Master.is_deleted == True,
            Client_Master.deleted_reason.in_(CLEANSING_STATUSES),
        )
 
        if tenant_id:
            query = query.filter(Client_Master.tenant_id == tenant_id)
 
        rows = query.all()
 
        records = []
        for client, contract, supplier in rows:
            records.append({
                'id': client.client_id,
                'client_id': client.client_id,
                'display_id': getattr(client, 'display_id', None),
                'display_order': getattr(client, 'display_order', None),
                'business_name': getattr(client, 'client_company_name', None) or 'Unknown',
                'contact_person': getattr(client, 'client_contact_name', None),
                'phone': getattr(client, 'client_phone', None),
                'mobile_no': getattr(client, 'mobile_no', None),
                'mpan_mpr': getattr(contract, 'mpan_mpr', None) if contract else None,
                'mpan_top': getattr(contract, 'mpan_top', None) if contract else None,
                'supplier_id': contract.supplier_id if contract else None,
                'supplier_name': supplier.supplier_company_name if supplier else None,
                'annual_usage': getattr(contract, 'annual_usage', None) if contract else None,
                'start_date': contract.contract_start_date.isoformat() if contract and contract.contract_start_date else None,
                'end_date': contract.contract_end_date.isoformat() if contract and contract.contract_end_date else None,
                'cleansing_reason': client.deleted_reason,
                'flagged_at': client.deleted_at.isoformat() if client.deleted_at else None,
                'notes': getattr(client, 'deleted_notes', None),
                'assigned_to_id': getattr(client, 'assigned_to_id', None),
                'assigned_to_name': None,
                'source': 'energy_client',
            })
 
        return jsonify({'records': records, 'total': len(records)}), 200
 
    except Exception as e:
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
 
# ══════════════════════════════════════════════════════════════════
# POST /energy-clients/<client_id>/cleanse
# ══════════════════════════════════════════════════════════════════
 
@client_interaction_bp.route('/energy-clients/<int:client_id>/cleanse', methods=['POST', 'OPTIONS'])
@token_required
def energy_client_cleanse_action(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        data = request.get_json(force=True, silent=True) or {}
        action = data.get('action')
 
        if action not in ('fix', 'delete'):
            return jsonify({'error': 'action must be fix or delete'}), 400
 
        query = session.query(Client_Master).filter(
            Client_Master.client_id == client_id,
            Client_Master.is_deleted == True,
            Client_Master.deleted_reason.in_(CLEANSING_STATUSES),
        )
        if tenant_id:
            query = query.filter(Client_Master.tenant_id == tenant_id)
 
        client = query.first()
        if not client:
            return jsonify({'error': 'Client not found in cleansing'}), 404
 
        # ── HARD DELETE ────────────────────────────────────────────────────────
        if action == 'delete':
            from backend.models import Client_Interactions as CI
            session.query(CI).filter(CI.client_id == client_id).delete()
            session.delete(client)
            session.commit()
            return jsonify({'success': True, 'message': 'Client permanently deleted'}), 200
 
        # ── FIX & RESTORE ──────────────────────────────────────────────────────
        tel_number = (data.get('tel_number') or '').strip()
        new_supplier_name = (data.get('new_supplier') or '').strip()
        notes = (data.get('notes') or '').strip()
 
        if not tel_number and not new_supplier_name:
            return jsonify({'error': 'Provide tel_number or new_supplier to fix'}), 400
 
        if tel_number:
            client.client_phone = tel_number
 
        if new_supplier_name:
            contract = (
                session.query(Energy_Contract_Master)
                .join(Project_Details, Project_Details.project_id == Energy_Contract_Master.project_id)
                .filter(Project_Details.client_id == client_id)
                .first()
            )
            if contract:
                supplier = (
                    session.query(Supplier_Master)
                    .filter(Supplier_Master.supplier_company_name.ilike(new_supplier_name))
                    .first()
                )
                if not supplier:
                    supplier = Supplier_Master(
                        supplier_company_name=new_supplier_name,
                        supplier_contact_name=new_supplier_name,
                        supplier_provisions=0,
                        created_at=datetime.utcnow(),
                    )
                    session.add(supplier)
                    session.flush()
                contract.supplier_id = supplier.supplier_id
                contract.updated_at = datetime.utcnow()
 
        client.is_deleted = False
        client.deleted_at = None
        client.deleted_reason = None
        if hasattr(client, 'is_cleansing'):
            client.is_cleansing = False
 
        project = session.query(Project_Details).filter_by(client_id=client_id).first()
        if project:
            project.status = 'Active'
 
        fix_notes = f"[Cleansing Fix] {notes}" if notes else "[Cleansing Fix] Record corrected and restored"
        safe_add_with_sequence_retry(
            session,
            Client_Interactions(
                client_id=client_id,
                contact_date=datetime.utcnow().date(),
                contact_method=1,
                notes=fix_notes,
                next_steps='Restored',
                created_at=datetime.utcnow(),
            ))
 
        session.commit()
        print(f"✅ Client {client_id} fixed and restored to Renewals")
        return jsonify({'success': True, 'message': 'Client fixed and restored to Renewals'}), 200
 
    except Exception as e:
        session.rollback()
        import traceback; traceback.print_exc()
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
 
# ══════════════════════════════════════════════════════════════════
# UNCHANGED ROUTES BELOW
# ══════════════════════════════════════════════════════════════════
 
@client_interaction_bp.route('/energy-clients/<int:client_id>/history', methods=['GET', 'OPTIONS'])
@token_required
def get_interaction_history(client_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200

    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        query = session.query(Client_Interactions)
        if tenant_id:
            query = query.join(
                Client_Master, Client_Interactions.client_id == Client_Master.client_id
            ).filter(and_(
                Client_Interactions.client_id == client_id,
                Client_Master.tenant_id == tenant_id
            ))
        else:
            query = query.filter(Client_Interactions.client_id == client_id)
 
        interactions = query.order_by(Client_Interactions.created_at.desc()).all()
 
        return jsonify({'interactions': [{
            'interaction_id': i.interaction_id,
            'interaction_type': i.next_steps or 'Unknown',
            'contact_date': i.contact_date.isoformat() if i.contact_date else None,
            'reminder_date': i.reminder_date.isoformat() if i.reminder_date else None,
            'notes': i.notes,
            'employee_id': None,
            'created_at': i.created_at.isoformat() if i.created_at else None
        } for i in interactions]}), 200
 
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching interaction history: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
 
 
@client_interaction_bp.route('/energy-clients/<int:client_id>/history/<int:interaction_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_interaction(client_id, interaction_id):
    if request.method == 'OPTIONS':
        return jsonify({}), 200
 
    session = SessionLocal()
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
 
        query = session.query(Client_Interactions).filter(
            Client_Interactions.interaction_id == interaction_id,
            Client_Interactions.client_id == client_id
        )
        if tenant_id:
            query = query.join(
                Client_Master, Client_Interactions.client_id == Client_Master.client_id
            ).filter(Client_Master.tenant_id == tenant_id)
 
        interaction = query.first()
        if not interaction:
            return jsonify({'error': 'Interaction not found'}), 404
 
        session.delete(interaction)
        session.commit()
 
        return jsonify({'success': True, 'message': 'Interaction deleted successfully'}), 200
 
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting interaction: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()
