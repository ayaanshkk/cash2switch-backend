"""
StreemLyne CRM Models
SQLAlchemy models for the multi-tenant CRM database tables in StreemLyne_MT schema
"""

from sqlalchemy import Column, Integer, SmallInteger, String, Boolean, DateTime, Date, ForeignKey, Text, Numeric, Float
from sqlalchemy.orm import relationship
from datetime import datetime

from .db import Base

# Schema for all CRM tables
SCHEMA = 'StreemLyne_MT'


class Tenant_Master(Base):
    """Tenant/Company Master"""
    __tablename__ = 'Tenant_Master'
    __table_args__ = {'schema': SCHEMA}
    
    tenant_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_company_name = Column(String(255))
    tenant_contact_name = Column(String(255))
    onboarding_date = Column(Date)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class Employee_Master(Base):
    """Employee Master"""
    __tablename__ = 'Employee_Master'
    __table_args__ = {'schema': SCHEMA}
    
    employee_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(Integer, ForeignKey(f'{SCHEMA}.Tenant_Master.tenant_id'))
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
    """Client Master"""
    __tablename__ = 'Client_Master'
    __table_args__ = {'schema': SCHEMA}
    
    client_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Tenant_Master.tenant_id'))
    client_company_name = Column(String(255))
    client_contact_name = Column(String(255))
    address = Column(String(500))
    country_id = Column(SmallInteger)
    post_code = Column(String(20))
    client_phone = Column(String(50))
    client_email = Column(String(255))
    client_website = Column(String(255))
    default_currency_id = Column(SmallInteger)
    created_at = Column(DateTime)


class Project_Details(Base):
    """Project Details"""
    __tablename__ = 'Project_Details'
    __table_args__ = {'schema': SCHEMA}
    
    project_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    client_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Client_Master.client_id'))
    opportunity_id = Column(SmallInteger)
    project_title = Column(String(255))
    project_description = Column(Text)
    start_date = Column(Date)
    end_date = Column(Date)
    employee_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Employee_Master.employee_id'))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    address = Column(String(500))
    Misc_Col1 = Column(String(255))  # Extra field
    Misc_Col2 = Column(Integer)  # Annual Usage for energy


class Energy_Contract_Master(Base):
    """Energy Contract Master"""
    __tablename__ = 'Energy_Contract_Master'
    __table_args__ = {'schema': SCHEMA}
    
    energy_contract_master_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    project_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Project_Details.project_id'))
    employee_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Employee_Master.employee_id'))
    supplier_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Supplier_Master.supplier_id'))
    contract_start_date = Column(Date)
    contract_end_date = Column(Date)
    terms_of_sale = Column(String(500))
    service_id = Column(SmallInteger)
    unit_rate = Column(Float)
    currency_id = Column(SmallInteger)
    document_details = Column(String(500))
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
    mpan_number = Column(String(100))  # MPAN/MPR number


class Opportunity_Details(Base):
    """Opportunity/Pipeline Details"""
    __tablename__ = 'Opportunity_Details'
    __table_args__ = {'schema': SCHEMA}
    
    opportunity_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    client_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Client_Master.client_id'))
    opportunity_title = Column(String(255))
    opportunity_description = Column(Text)
    opportunity_date = Column(Date)
    opportunity_owner_employee_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Employee_Master.employee_id'))
    stage_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Stage_Master.stage_id'))
    opportunity_value = Column(SmallInteger)
    currency_id = Column(SmallInteger)
    created_at = Column(DateTime)
    Misc_Col1 = Column(String(255))


class Client_Interactions(Base):
    """Client Interactions/Callbacks"""
    __tablename__ = 'Client_Interactions'
    __table_args__ = {'schema': SCHEMA}
    
    interaction_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    client_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Client_Master.client_id'))
    contact_date = Column(Date)
    contact_method = Column(SmallInteger)  # 1=Phone, 2=Email, etc.
    notes = Column(String(1000))
    next_steps = Column(String(500))
    reminder_date = Column(Date)
    created_at = Column(DateTime)


class Supplier_Master(Base):
    """Supplier Master"""
    __tablename__ = 'Supplier_Master'
    __table_args__ = {'schema': SCHEMA}
    
    supplier_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    supplier_company_name = Column(String(255))
    supplier_contact_name = Column(String(255))
    supplier_provisions = Column(SmallInteger)  # 0=Generic, 1=Electricity, 2=Gas, 3=Both
    created_at = Column(DateTime)


class Stage_Master(Base):
    """Stage Master (Pipeline Stages)"""
    __tablename__ = 'Stage_Master'
    __table_args__ = {'schema': SCHEMA}
    
    stage_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    stage_name = Column(String(100))
    stage_description = Column(String(255))
    preceding_stage_id = Column(SmallInteger)
    stage_type = Column(SmallInteger)


class Services_Master(Base):
    """Services Master"""
    __tablename__ = 'Services_Master'
    __table_args__ = {'schema': SCHEMA}
    
    service_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Tenant_Master.tenant_id'))
    service_title = Column(String(255))
    service_description = Column(Text)
    service_rate = Column(Float)
    currency_id = Column(SmallInteger)
    supplier_id = Column(SmallInteger, ForeignKey(f'{SCHEMA}.Supplier_Master.supplier_id'))
    date_from = Column(Date)
    date_to = Column(Date)
    created_at = Column(DateTime)
    service_code = Column(String(50))


class Currency_Master(Base):
    """Currency Master"""
    __tablename__ = 'Currency_Master'
    __table_args__ = {'schema': SCHEMA}
    
    currency_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    currency_name = Column(String(100))
    currency_code = Column(String(10))
    created_at = Column(DateTime)


class Country_Master(Base):
    """Country Master"""
    __tablename__ = 'Country_Master'
    __table_args__ = {'schema': SCHEMA}
    
    country_id = Column(SmallInteger, primary_key=True, autoincrement=True)
    country_name = Column(String(100))
    country_isd_code = Column(String(10))
    created_at = Column(DateTime)