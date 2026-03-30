"""
Complete Models File
Contains both legacy auth models (User) and CRM models (UserMaster, Client_Master, etc.)
"""

import uuid
import secrets
from datetime import datetime, timedelta
from sqlalchemy import (
    Column, Integer, SmallInteger, String, Boolean, DateTime, Date, 
    ForeignKey, Text, Float, Numeric
)
from sqlalchemy.orm import relationship
from werkzeug.security import generate_password_hash, check_password_hash

from backend.db import Base

# ==========================================
# LEGACY AUTH MODELS
# ==========================================

class User(Base):
    """Legacy local auth user model"""
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    phone = Column(String(50), nullable=True)
    role = Column(String(50), nullable=False, default='Staff')
    department = Column(String(100), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_verified = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login = Column(DateTime, nullable=True)
    reset_token = Column(String(255), nullable=True)
    reset_token_expires = Column(DateTime, nullable=True)
    verification_token = Column(String(255), nullable=True)
    is_invited = Column(Boolean, default=False)
    invitation_token = Column(String(255), nullable=True)
    invited_at = Column(DateTime, nullable=True)

    def __repr__(self):
        return f'<User {self.email}>'

    def set_password(self, password: str) -> None:
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"

    def generate_reset_token(self) -> str:
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expires = datetime.utcnow() + timedelta(hours=1)
        return self.reset_token

    def generate_verification_token(self) -> str:
        self.verification_token = secrets.token_urlsafe(32)
        return self.verification_token

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'email': self.email,
            'first_name': self.first_name,
            'last_name': self.last_name,
            'full_name': self.full_name,
            'phone': self.phone,
            'role': self.role,
            'department': self.department,
            'is_active': self.is_active,
            'is_invited': self.is_invited,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


class LoginAttempt(Base):
    __tablename__ = 'login_attempts'

    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    success = Column(Boolean, default=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)


class Session(Base):
    __tablename__ = 'user_sessions'

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45))
    user_agent = Column(Text)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship('User', backref='sessions')


# ==========================================
# CRM AUTH MODEL
# ==========================================

class UserMaster(Base):
    """CRM User Master (StreemLyne_MT.User_Master)"""
    __tablename__ = 'User_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}

    user_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    employee_id = Column(SmallInteger, nullable=True, index=True)
    user_name = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=True)
    updated_at = Column(Date, nullable=True)

    def __repr__(self) -> str:
        return f"<UserMaster {self.user_id} {self.user_name}>"

    @property
    def is_active(self) -> bool:
        return True

    @property
    def id(self):
        return self.employee_id

    def check_password(self, password: str) -> bool:
        return self.password == password if self.password else False

    @property
    def roles(self):
        return []

    def to_dict(self) -> dict:
        return {
            'user_id': self.user_id,
            'employee_id': self.employee_id,
            'user_name': self.user_name,
            'role': getattr(self, 'role', None),
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'is_active': self.is_active,
        }


# ==========================================
# CRM MODELS (StreemLyne_MT Schema)
# ==========================================

SCHEMA = 'StreemLyne_MT'


class Tenant_Master(Base):
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': SCHEMA}
    
    tenant_id = Column('tenant_id', SmallInteger, primary_key=True, autoincrement=True)
    tenant_company_name = Column(String(255))
    tenant_contact_name = Column(String(255))
    onboarding_Date = Column('onboarding_Date', Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Employee_Master(Base):
    __tablename__ = 'Employee_Master'
    __table_args__ = {'schema': SCHEMA}
    
    employee_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=True)  # bigint in DB
    employee_name = Column(String(255))
    employee_designation_id = Column(SmallInteger)
    phone = Column(String(50))
    email = Column(String(255))
    date_of_birth = Column(Date)
    date_of_joining = Column(Date)
    id_type = Column(String(50))
    id_number = Column(String(100))
    role_ids = Column(String(255))
    created_on = Column(DateTime)
    updated_on = Column(DateTime)
    commission_percentage = Column(Float)


class Client_Master(Base):
    __tablename__ = 'Client_Master'
    __table_args__ = {'schema': SCHEMA}    
    
    client_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_client_id = Column(SmallInteger, nullable=True)
    tenant_id = Column(SmallInteger, nullable=True)
    display_id = Column(Integer, nullable=True)
    assigned_employee_id = Column(SmallInteger, nullable=True)
    client_company_name = Column(String(255))
    client_contact_name = Column(String(255))
    address = Column(String(500))
    country_id = Column(SmallInteger)
    post_code = Column(String(20))
    client_phone = Column(String(50))
    client_mobile = Column(String(50), nullable=True)
    client_email = Column(String(255))
    client_website = Column(String(255))
    default_currency_id = Column(SmallInteger)
    created_at = Column(DateTime)
    position = Column(String(100))
    company_number = Column(String(50))
    date_of_birth = Column(Date)
    charity_ltd_company_number = Column(String(50))
    partner_details = Column(Text)
    bank_name = Column(String(255))
    account_number = Column(String(50))
    sort_code = Column(String(20))
    home_door_number = Column(String(20))
    home_street = Column(String(255))
    partner_dob = Column(Date)
    credit_score = Column(Integer)
    is_deleted = Column(Boolean, default=False, nullable=False)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    deleted_reason = Column(String(100), nullable=True)
    is_archived = Column(Boolean, default=False)
    archived_at = Column(DateTime)
    archived_reason = Column(String(255))
    display_order = Column(Integer, nullable=True)
    is_allocated = Column(Boolean, default=False, nullable=True)


class Project_Details(Base):
    __tablename__ = 'Project_Details'
    __table_args__ = {'schema': SCHEMA}
    
    project_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    client_id = Column(SmallInteger, nullable=True)
    opportunity_id = Column(SmallInteger)
    project_title = Column(String(255))
    project_description = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    employee_id = Column(SmallInteger, nullable=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    address = Column(String(500))
    Misc_Col1 = Column(String(255))
    Misc_Col2 = Column(Integer)
    site_name = Column(String(255))
    month_sold = Column(String(50))
    house_name = Column(String(255))
    house_number = Column(String(20))
    door_number = Column(String(20))
    town = Column(String(100))
    county = Column(String(100))
    assigned_employee_id = Column(SmallInteger, nullable=True)
    status = Column(String(255), nullable=True) 


class Energy_Contract_Master(Base):
    __tablename__ = 'Energy_Contract_Master'
    __table_args__ = {'schema': SCHEMA}
    
    energy_contract_master_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    project_id = Column(SmallInteger, nullable=True)
    employee_id = Column(SmallInteger, nullable=True)
    supplier_id = Column(SmallInteger, nullable=True)
    contract_start_date = Column(Date)
    contract_end_date = Column(Date)
    terms_of_sale = Column(String(500))
    service_id = Column(SmallInteger)
    unit_rate = Column(Float)
    currency_id = Column(SmallInteger)
    document_details = Column(String(500))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    mpan_number = Column(String(100))
    mpan_bottom = Column(String(100))
    old_supplier_id = Column(Integer, ForeignKey('StreemLyne_MT.Supplier_Master.supplier_id'))
    net_notch = Column(Numeric(10, 2))
    term_sold = Column(Integer)
    rate_2 = Column(Numeric(10, 4))
    rate_3 = Column(Numeric(10, 4))
    comms_paid = Column(Numeric(10, 2))
    term_sold = Column(Numeric(10, 2))
    standing_charge = Column(String(50))
    aggregator = Column(String(255))
    rate_1 = Column(Numeric(10, 4))
    payment_type = Column(String(50))


class Opportunity_Details(Base):
    """
    ✅ CORRECTED: Added all missing columns that are queried in crm_routes.py
    This model now matches the actual database schema after ALTER TABLE migrations.
    """
    __tablename__ = 'Opportunity_Details'
    __table_args__ = {'schema': SCHEMA}
    
    # ── Core fields ──────────────────────────────────────────────────────────
    opportunity_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_opportunity_id = Column(SmallInteger, nullable=True)
    tenant_lead_id = Column(SmallInteger, nullable=True)  # Display ID for leads
    tenant_id = Column(SmallInteger, nullable=True)  # ✅ REQUIRED for tenant filtering
    client_id = Column(SmallInteger, nullable=True)
    opportunity_title = Column(String(255))
    opportunity_description = Column(Text)
    opportunity_date = Column(Date)
    opportunity_owner_employee_id = Column(SmallInteger, nullable=True)
    stage_id = Column(SmallInteger, nullable=True)
    opportunity_value = Column(SmallInteger)
    currency_id = Column(SmallInteger)
    created_at = Column(DateTime)
    Misc_Col1 = Column(String(255))
    
    # ── Lead-specific fields (from ALTER TABLE migrations) ──────────────────
    service_id = Column(SmallInteger, nullable=True)  # ✅ 1=electricity, 2=water
    business_name = Column(String(255), nullable=True)  # ✅ Required for display
    contact_person = Column(String(255), nullable=True)
    tel_number = Column(String(50), nullable=True)
    mobile_no = Column(String(50), nullable=True)
    email = Column(String(255), nullable=True)
    mpan_mpr = Column(String(100), nullable=True)
    mpan_bottom = Column(String(100), nullable=True)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    
    # ── Contract details ─────────────────────────────────────────────────────
    supplier_id = Column(SmallInteger, nullable=True)  # ✅ Required for filtering
    annual_usage = Column(Numeric(10, 2), nullable=True)
    stand_charge = Column(Numeric(10, 4), nullable=True)
    rate_1 = Column(Numeric(10, 4), nullable=True)
    rate_2 = Column(Numeric(10, 4), nullable=True)
    rate_3 = Column(Numeric(10, 4), nullable=True)
    net_notch = Column(Numeric(10, 2), nullable=True)
    payment_type = Column(String(50), nullable=True)
    
    # ── Address fields ───────────────────────────────────────────────────────
    postcode = Column(String(20), nullable=True)
    house_name = Column(String(255), nullable=True)
    house_number = Column(String(50), nullable=True)
    door_number = Column(String(50), nullable=True)
    address = Column(String(500), nullable=True)
    town = Column(String(100), nullable=True)
    county = Column(String(100), nullable=True)
    
    # ── Personal details ─────────────────────────────────────────────────────
    position = Column(String(100), nullable=True)
    company_number = Column(String(50), nullable=True)
    date_of_birth = Column(Date, nullable=True)
    
    # ── Banking ──────────────────────────────────────────────────────────────
    bank_name = Column(String(255), nullable=True)
    bank_account_number = Column(String(50), nullable=True)
    bank_sort_code = Column(String(20), nullable=True)
    charity_ltd_company_number = Column(String(50), nullable=True)
    partner_details = Column(Text, nullable=True)
    
    # ── Additional fields ────────────────────────────────────────────────────
    meter_ref = Column(String(100), nullable=True)
    uplift = Column(Numeric(10, 2), nullable=True)
    comments = Column(Text, nullable=True)
    document_details = Column(String(500), nullable=True)
    site_name = Column(String(255), nullable=True)
    month_sold = Column(String(50), nullable=True)
    term_sold = Column(Numeric(10, 2), nullable=True)
    aggregator = Column(String(255), nullable=True)
    other_charges_1 = Column(Numeric(10, 4), nullable=True)
    other_charges_2 = Column(Numeric(10, 4), nullable=True)
    other_charges_3 = Column(Numeric(10, 4), nullable=True)
    night_charge = Column(Numeric(10, 4), nullable=True)
    eve_weekend_charge = Column(Numeric(10, 4), nullable=True)
    
    # ── Assignment tracking (mirrors Client_Master.is_allocated behavior) ───
    is_allocated = Column(Boolean, default=False, nullable=True)  # ✅ Required
    notes = Column(Text, nullable=True)


class Client_Interactions(Base):
    __tablename__ = 'Client_Interactions'
    __table_args__ = {'schema': SCHEMA}
    
    interaction_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    client_id = Column(SmallInteger, nullable=True)
    contact_date = Column(Date)
    contact_method = Column(SmallInteger)
    notes = Column(String(1000))
    next_steps = Column(String(500))
    reminder_date = Column(Date)
    created_at = Column(DateTime)


class Supplier_Master(Base):
    __tablename__ = 'Supplier_Master'
    __table_args__ = {'schema': SCHEMA}
    
    supplier_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = Column(String(255))
    supplier_contact_name = Column(String(255))
    supplier_provisions = Column(SmallInteger)
    created_at = Column(DateTime)


class Stage_Master(Base):
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': SCHEMA}
    stage_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    stage_name = Column(String(100))
    stage_description = Column(String(255))
    preceding_stage_id = Column(SmallInteger)
    stage_type = Column(SmallInteger)

class Role_Master(Base):
    __tablename__ = 'Role_Master'
    __table_args__ = {'schema': SCHEMA}
    
    role_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    role_name = Column(String(100))
    role_description = Column(String(255))
    is_system = Column(Boolean)
    created_at = Column(DateTime)

class User_Role_Mapping(Base):
    __tablename__ = 'User_Role_Mapping'
    __table_args__ = {'schema': SCHEMA}
    
    user_role_mapping_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    user_id = Column(SmallInteger)
    role_id = Column(SmallInteger)


class Services_Master(Base):
    __tablename__ = 'Services_Master'
    __table_args__ = {'schema': SCHEMA}
    
    service_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(SmallInteger, nullable=True)
    service_title = Column(String(255))
    service_description = Column(Text)
    service_rate = Column(Float)
    currency_id = Column(SmallInteger)
    supplier_id = Column(SmallInteger, nullable=True)
    date_from = Column(Date)
    date_to = Column(Date)
    created_at = Column(DateTime)
    service_code = Column(String(50))


class Currency_Master(Base):
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': SCHEMA}
    
    currency_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    currency_name = Column(String(100))
    currency_code = Column(String(10))
    created_at = Column(DateTime)


class Country_Master(Base):
    __tablename__ = 'Country_Master'
    __table_args__ = {'schema': SCHEMA}
    
    country_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    country_name = Column(String(100))
    country_isd_code = Column(String(10))
    created_at = Column(DateTime)


# ==========================================
# LEGACY CUSTOMER MODEL (if needed)
# ==========================================

class Customer(Base):
    """Legacy customer model"""
    __tablename__ = 'customers'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    phone = Column(String(50))
    email = Column(String(200))
    address = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone,
            'email': self.email,
            'address': self.address,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

class Notification_Master(Base):
    __tablename__ = 'Notification_Master'
    __table_args__ = {'schema': 'StreemLyne_MT'}
    
    notification_id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, nullable=False)
    employee_id = Column(Integer, nullable=True)
    client_id = Column(Integer, nullable=True)
    contract_id = Column(Integer, nullable=True)
    
    notification_type = Column(String(50), nullable=False)
    priority = Column(String(20), nullable=False, default='medium')
    message = Column(Text, nullable=False)
    
    read = Column(Boolean, default=False, nullable=False)
    dismissed = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow, nullable=False)
    read_at = Column(DateTime(timezone=True), nullable=True)