"""
Updated Callback Route - backend/routes/client_interactions_routes.py
✅ Status now stored in Project_Details.status (not Opportunity_Details.Misc_Col1)
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import and_, text
from backend.models import Client_Interactions, Client_Master, Energy_Contract_Master, Project_Details, Supplier_Master
from backend.db import SessionLocal
from backend.routes.auth_routes import token_required

client_interaction_bp = Blueprint('client_interactions', __name__)


def get_tenant_id_from_user(user):
    if hasattr(user, 'tenant_id'):
        return user.tenant_id
    elif hasattr(user, 'Tenant_ID'):
        return user.Tenant_ID
    return None


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

        print(f"📥 Callback for client {client_id} — status: {status}")

        status_config = {
            "Callback":          {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Not Answered":      {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Priced":            {"requires_date": False, "requires_sold": True,  "deletes_record": False, "requires_notes": False},
            "Lost":              {"requires_date": True,  "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Lost COT":          {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": True},
            "Already Renewed":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Invalid Number":    {"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Meter De-energised":{"requires_date": False, "requires_sold": False, "deletes_record": True,  "requires_notes": False},
            "Broker in Place":   {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "End Date Changed":  {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Complaint":         {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Email Only":        {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": False},
            "Renewed Directly":  {"requires_date": True,  "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Incorrect Supplier":{"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": True},
            "Converted":         {"requires_date": False, "requires_sold": False, "deletes_record": False, "requires_notes": False},
        }

        if not status:
            return jsonify({'error': 'Status is required'}), 400

        if status not in status_config:
            return jsonify({'error': 'Invalid status'}), 400

        config = status_config[status]

        if config["requires_notes"] and not notes.strip():
            return jsonify({'error': 'Please enter the reason why it was lost'}), 400

        date_required = False
        if config["requires_sold"]:
            if is_sold is None:
                return jsonify({'error': 'Please select if the contract was sold'}), 400
            date_required = is_sold
        else:
            date_required = config["requires_date"]

        if date_required and not callback_date:
            return jsonify({'error': 'Callback date is required for this status'}), 400

        # ── Soft delete (Lost, Invalid Number etc.) ────────────────────────────
        if config["deletes_record"]:
            client_query = session.query(Client_Master).filter(Client_Master.client_id == client_id)
            if tenant_id:
                client_query = client_query.filter(Client_Master.tenant_id == tenant_id)
            client = client_query.first()

            if not client:
                return jsonify({'error': 'Customer not found'}), 404

            try:
                client.is_deleted = True
                client.deleted_at = datetime.utcnow()
                client.deleted_reason = status

                # ✅ Update status on Project_Details
                project = session.query(Project_Details).filter_by(client_id=client_id).first()
                if project:
                    project.status = status

                formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
                session.add(Client_Interactions(
                    client_id=client_id,
                    contact_date=datetime.utcnow().date(),
                    contact_method=1,
                    reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                    notes=formatted_notes,
                    next_steps=status,
                    created_at=datetime.utcnow()
                ))

                session.commit()
                print(f"✅ Moved client {client_id} to recycle bin ({status})")
                return jsonify({
                    'success': True,
                    'message': f'Moved to recycle bin ({status})',
                    'deleted': False,
                    'moved_to_recycle_bin': True
                }), 200

            except Exception as e:
                session.rollback()
                print(f"❌ Error moving to recycle bin: {e}")
                return jsonify({'error': f'Failed to move to recycle bin: {str(e)}'}), 500

        # ── Already Renewed ────────────────────────────────────────────────────
        if status == "Already Renewed":
            try:
                client = session.query(Client_Master).filter(Client_Master.client_id == client_id).first()
                if not client:
                    return jsonify({'error': 'Client not found'}), 404

                changes_made = []

                contract = session.query(Energy_Contract_Master).select_from(Client_Master).join(
                    Project_Details, Client_Master.client_id == Project_Details.client_id
                ).join(
                    Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
                ).filter(Client_Master.client_id == client_id).first()

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
                    changes_made.append("Address updated")

                session.flush()

                if changes_made:
                    summary = " | ".join(changes_made)
                    notes = f"{notes.strip()} | {summary}".strip(" |") if notes.strip() else summary

                # ✅ Update Project_Details.status instead of Opportunity_Details.Misc_Col1
                project = session.query(Project_Details).filter_by(client_id=client_id).first()
                if project:
                    if renewed_by == 'customer':
                        project.status = 'Renewed Directly'
                        notes = f"[Renewed by Customer] {notes}".strip() if notes else "[Renewed by Customer]"
                        print(f"✅ Renewed by customer → status = 'Renewed Directly'")
                    elif renewed_by == 'agent':
                        project.status = 'Already Renewed'
                        notes = f"[Renewed by Agent] {notes}".strip() if notes else "[Renewed by Agent]"
                        print(f"✅ Renewed by agent → status = 'Already Renewed'")
                    else:
                        project.status = 'Already Renewed'
                        print(f"⚠️ No renewed_by — defaulting to 'Already Renewed'")

            except Exception as e:
                session.rollback()
                import traceback; traceback.print_exc()
                return jsonify({'error': f'Failed to update information: {str(e)}'}), 500

        # ── End Date Changed ───────────────────────────────────────────────────
        elif status == "End Date Changed" and new_end_date_str:
            try:
                new_end_date = datetime.strptime(new_end_date_str, '%Y-%m-%d').date()

                contract = session.query(Energy_Contract_Master).select_from(Client_Master).join(
                    Project_Details, Client_Master.client_id == Project_Details.client_id
                ).join(
                    Energy_Contract_Master, Project_Details.project_id == Energy_Contract_Master.project_id
                ).filter(Client_Master.client_id == client_id).first()

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

            except Exception as e:
                session.rollback()
                import traceback; traceback.print_exc()
                return jsonify({'error': f'Failed to update end date: {str(e)}'}), 500

        # ── Update Project_Details.status for all other statuses ───────────────
        if status != "Already Renewed":
            project = session.query(Project_Details).filter_by(client_id=client_id).first()
            if project:
                project.status = status

        # ── Priced with No (move to priced page) ───────────────────────────────
        if status == "Priced" and not is_sold:
            session.commit()
            return jsonify({
                'success': True,
                'message': 'Moved to Priced page',
                'moved_to_priced': True
            }), 200

        # ── Create interaction record ──────────────────────────────────────────
        formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
        session.add(Client_Interactions(
            client_id=client_id,
            contact_date=datetime.utcnow().date(),
            contact_method=1,
            reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
            notes=formatted_notes,
            next_steps=status,
            created_at=datetime.utcnow()
        ))

        session.commit()
        print(f"✅ Callback saved for client {client_id}, status: {status}")

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


@client_interaction_bp.route('/energy-clients/<int:client_id>/history', methods=['GET'])
@token_required
def get_interaction_history(client_id):
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