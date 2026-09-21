from sqlalchemy import text

from backend.models import (
    UserMaster,
    Employee_Master,
    UserCRMSearchPermission,
    CRMSearchPermissionAudit,
)


ADMIN_ROLES = {
    "platform admin",
    "tenant super admin",
}


def _get_role_name(user, session):
    """
    Get the effective CRM role for the authenticated user.
    """
    role = getattr(user, "role", None)

    if role:
        return str(role).strip().lower()

    user_id = getattr(user, "user_id", None)
    if not user_id:
        return ""

    row = session.execute(
        text("""
            SELECT rm.role_name
            FROM "StreemLyne_MT"."User_Role_Mapping" urm
            JOIN "StreemLyne_MT"."Role_Master" rm
              ON urm.role_id = rm.role_id
            WHERE urm.user_id = :user_id
            LIMIT 1
        """),
        {"user_id": user_id},
    ).mappings().first()

    return str(row["role_name"]).strip().lower() if row else ""


def _is_admin(user, session):
    role = _get_role_name(user, session)
    return role in ADMIN_ROLES


def get_search_permissions(user_id, session=None):
    """
    Return the two search permissions for a user.

    Missing permission row means both permissions are False.
    """
    owns_session = session is None

    if owns_session:
        from backend.db import SessionLocal
        session = SessionLocal()

    try:
        permission = (
            session.query(UserCRMSearchPermission)
            .filter(
                UserCRMSearchPermission.user_id == user_id
            )
            .first()
        )

        if not permission:
            return {
                "can_search_all_leads": False,
                "can_search_all_renewals": False,
            }

        return {
            "can_search_all_leads": bool(
                permission.can_search_all_leads
            ),
            "can_search_all_renewals": bool(
                permission.can_search_all_renewals
            ),
        }

    finally:
        if owns_session:
            session.close()


def can_search_all_leads(user, session=None):
    """
    Return whether the authenticated user can search
    all leads inside their own tenant.
    """
    owns_session = session is None

    if owns_session:
        from backend.db import SessionLocal
        session = SessionLocal()

    try:
        if _is_admin(user, session):
            return True

        user_id = getattr(user, "user_id", None)

        if not user_id:
            return False

        permissions = get_search_permissions(
            user_id,
            session=session,
        )

        return permissions["can_search_all_leads"]

    finally:
        if owns_session:
            session.close()


def can_search_all_renewals(user, session=None):
    """
    Return whether the authenticated user can search
    all renewals inside their own tenant.
    """
    owns_session = session is None

    if owns_session:
        from backend.db import SessionLocal
        session = SessionLocal()

    try:
        if _is_admin(user, session):
            return True

        user_id = getattr(user, "user_id", None)

        if not user_id:
            return False

        permissions = get_search_permissions(
            user_id,
            session=session,
        )

        return permissions["can_search_all_renewals"]

    finally:
        if owns_session:
            session.close()


def update_search_permissions(
    admin_user,
    target_user_id,
    leads_value,
    renewals_value,
    request_ip=None,
):
    """
    Update both search permissions for a target user.

    The permission update and audit record are committed
    together in one transaction.
    """

    from backend.db import SessionLocal

    session = SessionLocal()

    try:
        # --------------------------------------------------
        # 1. Validate boolean values
        # --------------------------------------------------
        if not isinstance(leads_value, bool):
            raise ValueError("can_search_all_leads must be a boolean")

        if not isinstance(renewals_value, bool):
            raise ValueError("can_search_all_renewals must be a boolean")

        # --------------------------------------------------
        # 2. Get admin tenant
        # --------------------------------------------------
        admin_user_id = getattr(admin_user, "user_id", None)

        if not admin_user_id:
            raise PermissionError("Authenticated user not found")

        admin_employee_id = getattr(
            admin_user,
            "employee_id",
            None,
        )

        if not admin_employee_id:
            raise PermissionError("Employee not found")

        admin_employee = (
            session.query(Employee_Master)
            .filter(
                Employee_Master.employee_id == admin_employee_id
            )
            .first()
        )

        if not admin_employee:
            raise PermissionError("Employee not found")

        admin_tenant_id = admin_employee.tenant_id

        # --------------------------------------------------
        # 3. Verify admin role
        # --------------------------------------------------
        if not _is_admin(admin_user, session):
            raise PermissionError("Admin access required")

        # --------------------------------------------------
        # 4. Find target user
        # --------------------------------------------------
        target = (
            session.query(
                UserMaster,
                Employee_Master,
            )
            .join(
                Employee_Master,
                UserMaster.employee_id
                == Employee_Master.employee_id,
            )
            .filter(
                UserMaster.user_id == target_user_id,
                Employee_Master.tenant_id == admin_tenant_id,
            )
            .first()
        )

        if not target:
            raise LookupError("Target user not found")

        target_user, target_employee = target

        # --------------------------------------------------
        # 5. Read old permission values
        # --------------------------------------------------
        permission = (
            session.query(UserCRMSearchPermission)
            .filter(
                UserCRMSearchPermission.user_id
                == target_user_id
            )
            .first()
        )

        if permission:
            old_leads = bool(
                permission.can_search_all_leads
            )
            old_renewals = bool(
                permission.can_search_all_renewals
            )
        else:
            old_leads = False
            old_renewals = False

            permission = UserCRMSearchPermission(
                user_id=target_user_id,
                updated_by_user_id=admin_user_id,
                can_search_all_leads=leads_value,
                can_search_all_renewals=renewals_value,
            )

            session.add(permission)

        # --------------------------------------------------
        # 6. Update permissions
        # --------------------------------------------------
        permission.can_search_all_leads = leads_value
        permission.can_search_all_renewals = renewals_value
        permission.updated_by_user_id = admin_user_id

        # --------------------------------------------------
        # 7. Create audit record
        # --------------------------------------------------
        audit = CRMSearchPermissionAudit(
            tenant_id=admin_tenant_id,
            target_user_id=target_user_id,
            old_search_all_leads=old_leads,
            new_search_all_leads=leads_value,
            old_search_all_renewals=old_renewals,
            new_search_all_renewals=renewals_value,
            changed_by_user_id=admin_user_id,
            request_ip=request_ip,
        )

        session.add(audit)

        # --------------------------------------------------
        # 8. Commit both together
        # --------------------------------------------------
        session.commit()

        return {
            "user_id": target_user_id,
            "can_search_all_leads": leads_value,
            "can_search_all_renewals": renewals_value,
        }

    except Exception:
        session.rollback()
        raise

    finally:
        session.close()