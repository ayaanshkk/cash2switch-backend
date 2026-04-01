import logging
from backend.crm.repositories.lead_repository import LeadRepository

logger = logging.getLogger(__name__)

def migrate_to_per_employee_display_ids(tenant_id: int):
    """
    One-time migration: convert existing display_order to per-employee display_id
    """
    repo = LeadRepository()
    
    try:
        # Get all employees who have leads
        employees_query = '''
            SELECT DISTINCT "opportunity_owner_employee_id"
            FROM "StreemLyne_MT"."Opportunity_Details"
            WHERE "tenant_id" = %s
            AND "opportunity_owner_employee_id" IS NOT NULL
            AND "deleted_at" IS NULL
        '''
        
        employees = repo.db.execute_query(employees_query, (tenant_id,))
        
        if not employees:
            logger.info('No employees with leads found for tenant %s', tenant_id)
            return
        
        total_recalculated = 0
        
        for emp_row in employees:
            employee_id = emp_row.get('opportunity_owner_employee_id')
            logger.info('Processing employee %s...', employee_id)
            
            result = repo.recalculate_display_ids_for_employee(tenant_id, employee_id)
            
            if result.get('success'):
                count = result.get('recalculated_count', 0)
                total_recalculated += count
                logger.info('  ✅ Assigned %d display_ids to employee %s', count, employee_id)
            else:
                logger.error('  ❌ Failed for employee %s: %s', employee_id, result.get('error'))
        
        logger.info('✅ Migration complete! Total recalculated: %d', total_recalculated)
        
    except Exception as e:
        logger.exception('Migration failed: %s', e)
        raise

if __name__ == '__main__':
    # Run for your tenant (Energy broker CRM is tenant 2)
    logging.basicConfig(level=logging.INFO)
    migrate_to_per_employee_display_ids(tenant_id=2)