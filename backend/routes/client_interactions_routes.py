"""
Updated Callback Route - backend/routes/client_interactions_routes.py
✅ BOTH "Lost" and "Lost COT" now move to recycle bin with soft delete
"""

from flask import Blueprint, request, jsonify, current_app
from datetime import datetime, timedelta
from sqlalchemy import and_, text
from backend.models import Client_Interactions, Client_Master, Opportunity_Details, Energy_Contract_Master, Project_Details, Supplier_Master
from backend.db import SessionLocal
from backend.routes.auth_routes import token_required

client_interaction_bp = Blueprint('client_interactions', __name__)


def get_tenant_id_from_user(user):
    """Helper to get tenant_id from user object"""
    if hasattr(user, 'tenant_id'):
        return user.tenant_id
    elif hasattr(user, 'Tenant_ID'):
        return user.Tenant_ID
    else:
        return None


@client_interaction_bp.route('/energy-clients/<int:client_id>/callback', methods=['POST', 'OPTIONS'])
@token_required
def add_callback(client_id):
    """
    Add callback with conditional logic
    ✅ NEW: Soft delete for Lost, Lost COT, Invalid Number, Meter De-energised
    ✅ NEW: Notes field is REQUIRED for Lost and Lost COT statuses
    ✅ NEW: Update end date for "End Date Changed" status
    """
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
        
        print(f"📥 Received callback request for client {client_id}")
        print(f"📥 Status: {status}")
        print(f"📥 New end date: {new_end_date_str}")
        
        # ✅ Status configurations
        status_config = {
            "Callback": {"requires_date": True, "requires_sold": False, "deletes_record": False, "misc_col1": None, "requires_notes": False},
            "Called": {"requires_date": True, "requires_sold": False, "deletes_record": False, "misc_col1": None, "requires_notes": False},
            "Not Answered": {"requires_date": True, "requires_sold": False, "deletes_record": False, "misc_col1": None, "requires_notes": False},
            "Priced": {"requires_date": False, "requires_sold": True, "deletes_record": False, "misc_col1": "priced", "requires_notes": False},
            "Lost": {"requires_date": True, "requires_sold": False, "deletes_record": True, "misc_col1": "lost", "requires_notes": True},
            "Lost COT": {"requires_date": False, "requires_sold": False, "deletes_record": True, "misc_col1": None, "requires_notes": True},
            "Already Renewed": {"requires_date": True, "requires_sold": False, "deletes_record": False, "misc_col1": "renewed", "requires_notes": False},
            "Invalid Number": {"requires_date": False, "requires_sold": False, "deletes_record": True, "misc_col1": None, "requires_notes": False},
            "Meter De-energised": {"requires_date": False, "requires_sold": False, "deletes_record": True, "misc_col1": None, "requires_notes": False},
            "Broker in Place": {"requires_date": True, "requires_sold": False, "deletes_record": False, "misc_col1": None, "requires_notes": False},
            "End Date Changed": {"requires_date": True, "requires_sold": False, "deletes_record": False, "misc_col1": None, "requires_notes": False},
        }
        
        # Validation
        if not status:
            return jsonify({'error': 'Status is required'}), 400
        
        if status not in status_config:
            return jsonify({'error': 'Invalid status'}), 400
        
        config = status_config[status]
        
        # ✅ Validate notes for Lost/Lost COT
        if config["requires_notes"] and not notes.strip():
            return jsonify({'error': 'Please enter the reason why it was lost'}), 400
        
        # Check if date is required
        date_required = False
        if config["requires_sold"]:
            if is_sold is None:
                return jsonify({'error': 'Please select if the contract was sold'}), 400
            date_required = is_sold
        else:
            date_required = config["requires_date"]
        
        if date_required and not callback_date:
            return jsonify({'error': 'Callback date is required for this status'}), 400
        
        # ✅ Handle deletion statuses with SOFT DELETE
        if config["deletes_record"]:
            client_query = session.query(Client_Master).filter(Client_Master.client_id == client_id)
            if tenant_id:
                client_query = client_query.filter(Client_Master.tenant_id == tenant_id)
            
            client = client_query.first()
            
            if not client:
                return jsonify({'error': 'Customer not found'}), 404
            
            try:
                # ✅ SOFT DELETE: Mark as deleted instead of removing from database
                client.is_deleted = True
                client.deleted_at = datetime.utcnow()
                client.deleted_reason = status
                
                # Update Opportunity status to track the reason
                opportunity = session.query(Opportunity_Details).filter_by(client_id=client_id).first()
                if opportunity:
                    opportunity.Misc_Col1 = status
                
                # ✅ Create interaction with notes (will be visible in history)
                formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
                new_interaction = Client_Interactions(
                    client_id=client_id,
                    contact_date=datetime.utcnow().date(),
                    contact_method=1,
                    reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
                    notes=formatted_notes,
                    next_steps=status,
                    created_at=datetime.utcnow()
                )
                session.add(new_interaction)
                
                session.commit()
                
                print(f"✅ Moved client {client_id} to recycle bin ({status})")
                
                return jsonify({
                    'success': True,
                    'message': f'Moved to recycle bin ({status})',
                    'deleted': False,
                    'moved_to_recycle_bin': True
                }), 200
                
            except Exception as delete_error:
                session.rollback()
                print(f"❌ Error moving to recycle bin: {delete_error}")
                return jsonify({'error': f'Failed to move to recycle bin: {str(delete_error)}'}), 500

        if status == "Already Renewed":
            try:
                client = session.query(Client_Master).filter(Client_Master.client_id == client_id).first()
                
                if not client:
                    print(f"❌ No client found for client {client_id}")
                    return jsonify({'error': 'Client not found'}), 404
                
                changes_made = []
                
                # ✅ Get the contract first (we'll need it for both end date and supplier updates)
                contract = session.query(Energy_Contract_Master).select_from(Client_Master).join(
                    Project_Details,
                    Client_Master.client_id == Project_Details.client_id
                ).join(
                    Energy_Contract_Master,
                    Project_Details.project_id == Energy_Contract_Master.project_id
                ).filter(
                    Client_Master.client_id == client_id
                ).first()
                
                if not contract:
                    print(f"❌ No contract found for client {client_id}")
                    return jsonify({'error': 'Contract not found'}), 404
                
                # ✅ Update contract end date if provided
                if new_end_date_str:
                    new_end_date = datetime.strptime(new_end_date_str, '%Y-%m-%d').date()
                    old_end_date = contract.contract_end_date
                    contract.contract_end_date = new_end_date
                    contract.updated_at = datetime.utcnow()
                    session.flush()
                    print(f"✅ Updated contract end date from {old_end_date} to {new_end_date}")
                    
                    # ✅ Track changes
                    old_date_formatted = old_end_date.strftime('%d/%m/%Y') if old_end_date else 'None'
                    new_date_formatted = new_end_date.strftime('%d/%m/%Y')
                    changes_made.append(f"End date: {old_date_formatted} → {new_date_formatted}")
                
                # ✅ Update supplier if provided (supplier is on the contract, not the client)
                if new_supplier and new_supplier.strip():
                    print(f"🔍 Attempting to update supplier to: {new_supplier}")
                    
                    # Find or create supplier
                    supplier = session.query(Supplier_Master).filter(
                        Supplier_Master.supplier_company_name.ilike(new_supplier.strip())
                    ).first()
                    
                    if not supplier:
                        # Create new supplier if doesn't exist
                        supplier = Supplier_Master(
                            supplier_company_name=new_supplier.strip(),
                            supplier_contact_name=new_supplier.strip(),
                            supplier_provisions=0,
                            created_at=datetime.utcnow()
                        )
                        session.add(supplier)
                        session.flush()
                        print(f"✅ Created new supplier: {new_supplier}")
                    
                    # Get old supplier name for tracking
                    old_supplier = None
                    if contract.supplier_id:
                        old_supplier = session.query(Supplier_Master).filter(
                            Supplier_Master.supplier_id == contract.supplier_id
                        ).first()
                    
                    old_supplier_name = old_supplier.supplier_company_name if old_supplier else 'None'
                    
                    # ✅ Update the CONTRACT's supplier (not the client's)
                    contract.supplier_id = supplier.supplier_id
                    contract.updated_at = datetime.utcnow()
                    session.flush()
                    print(f"✅ Updated supplier from {old_supplier_name} to: {new_supplier}")
                    changes_made.append(f"Supplier: {old_supplier_name} → {new_supplier}")
                
                # ✅ Update address if provided (address IS on the client)
                if new_address and new_address.strip():
                    old_address = client.address or 'N/A'
                    client.address = new_address.strip()
                    print(f"✅ Updated address")
                    changes_made.append(f"Address updated")
                
                session.flush()
                
                # ✅ Add changes summary to notes
                if changes_made:
                    changes_summary = " | ".join(changes_made)
                    if notes.strip():
                        notes = f"{notes.strip()} | {changes_summary}"
                    else:
                        notes = f"{changes_summary}"
                
                print(f"✅ Already Renewed - Changes: {changes_made}")
                
            except Exception as e:
                session.rollback()
                print(f"❌ Failed to update Already Renewed info: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Failed to update information: {str(e)}'}), 500
        
        # ✅ Handle End Date Changed - DO THIS FIRST before updating Misc_Col1
        elif status == "End Date Changed" and new_end_date_str:
            try:
                new_end_date = datetime.strptime(new_end_date_str, '%Y-%m-%d').date()
                
                print(f"🔍 Updating end date for client {client_id}")
                print(f"📅 New end date: {new_end_date}")
                
                # ✅ FIX: Use explicit join conditions with select_from
                contract = session.query(Energy_Contract_Master).select_from(Client_Master).join(
                    Project_Details,
                    Client_Master.client_id == Project_Details.client_id
                ).join(
                    Energy_Contract_Master,
                    Project_Details.project_id == Energy_Contract_Master.project_id
                ).filter(
                    Client_Master.client_id == client_id
                ).first()
                
                if contract:
                    old_end_date = contract.contract_end_date
                    contract.contract_end_date = new_end_date
                    contract.updated_at = datetime.utcnow()
                    session.flush()  # ✅ Force write to DB immediately
                    print(f"✅ Updated contract end date from {old_end_date} to {new_end_date}")
                    
                    # ✅ CRITICAL: Verify the update worked
                    session.refresh(contract)
                    print(f"🔍 Verified contract end date is now: {contract.contract_end_date}")
                    
                    # ✅ ADD THIS: Format the old and new dates for the interaction notes
                    old_date_formatted = old_end_date.strftime('%d/%m/%Y') if old_end_date else 'None'
                    new_date_formatted = new_end_date.strftime('%d/%m/%Y')
                    
                    # ✅ UPDATE: Store the date change info in notes
                    notes = f"Old end date: {old_date_formatted} → New end date: {new_date_formatted}"
                    if data.get('notes', '').strip():
                        notes = f"{data.get('notes').strip()} | {notes}"
                        
                else:
                    print(f"❌ No contract found for client {client_id}")
                    
            except Exception as e:
                session.rollback()
                print(f"❌ Failed to update end date: {e}")
                import traceback
                traceback.print_exc()
                return jsonify({'error': f'Failed to update end date: {str(e)}'}), 500
        
        # Update Misc_Col1 based on status
        opportunity = session.query(Opportunity_Details).filter_by(client_id=client_id).first()
        if opportunity:
            opportunity.Misc_Col1 = status
        
        # For "Priced" status with "No" - don't set callback date
        if status == "Priced" and not is_sold:
            session.commit()
            return jsonify({
                'success': True,
                'message': 'Moved to Priced page',
                'moved_to_priced': True
            }), 200
        
        # ✅ CRITICAL: ALWAYS create a NEW interaction entry (never update)
        formatted_notes = f"[{status}] {notes}" if notes else f"[{status}]"
        
        new_interaction = Client_Interactions(
            client_id=client_id,
            contact_date=datetime.utcnow().date(),
            contact_method=1,
            reminder_date=datetime.strptime(callback_date, '%Y-%m-%d').date() if callback_date else None,
            notes=formatted_notes,
            next_steps=status,
            created_at=datetime.utcnow()
        )
        session.add(new_interaction)
        
        session.commit()
        
        print(f"✅ Callback saved successfully for client {client_id}, status: {status}")
        
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
    """Get all interactions for a client"""
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        query = session.query(Client_Interactions)
        
        if tenant_id:
            query = query.join(
                Client_Master,
                Client_Interactions.client_id == Client_Master.client_id
            ).filter(
                and_(
                    Client_Interactions.client_id == client_id,
                    Client_Master.tenant_id == tenant_id
                )
            )
        else:
            query = query.filter(Client_Interactions.client_id == client_id)
        
        interactions = query.order_by(Client_Interactions.created_at.desc()).all()
        
        result = []
        for interaction in interactions:
            result.append({
                'interaction_id': interaction.interaction_id,
                'interaction_type': interaction.next_steps or 'Unknown',
                'contact_date': interaction.contact_date.isoformat() if interaction.contact_date else None,
                'reminder_date': interaction.reminder_date.isoformat() if interaction.reminder_date else None,
                'notes': interaction.notes,
                'employee_id': None,
                'created_at': interaction.created_at.isoformat() if interaction.created_at else None
            })
        
        return jsonify({'interactions': result}), 200
        
    except Exception as e:
        current_app.logger.exception(f"❌ Error fetching interaction history: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()


@client_interaction_bp.route('/energy-clients/<int:client_id>/history/<int:interaction_id>', methods=['DELETE', 'OPTIONS'])
@token_required
def delete_interaction(client_id, interaction_id):
    """
    Delete a specific interaction from history
    Admin or owner can delete their own interactions
    """
    if request.method == 'OPTIONS':
        return jsonify({}), 200
    
    session = SessionLocal()
    
    try:
        tenant_id = get_tenant_id_from_user(request.current_user)
        
        # Build query with tenant filtering
        query = session.query(Client_Interactions).filter(
            Client_Interactions.interaction_id == interaction_id,
            Client_Interactions.client_id == client_id
        )
        
        if tenant_id:
            query = query.join(
                Client_Master,
                Client_Interactions.client_id == Client_Master.client_id
            ).filter(Client_Master.tenant_id == tenant_id)
        
        interaction = query.first()
        
        if not interaction:
            return jsonify({'error': 'Interaction not found'}), 404
        
        # Delete the interaction
        session.delete(interaction)
        session.commit()
        
        current_app.logger.info(f"✅ Deleted interaction {interaction_id} for client {client_id}")
        
        return jsonify({
            'success': True,
            'message': 'Interaction deleted successfully'
        }), 200
        
    except Exception as e:
        session.rollback()
        current_app.logger.exception(f"❌ Error deleting interaction: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        session.close()