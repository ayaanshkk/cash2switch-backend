import uuid
import secrets
from datetime import datetime, timedelta
from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, Date, Enum, ForeignKey, Text, JSON, Numeric, Float, Time
)
from sqlalchemy.orm import relationship
from sqlalchemy.ext.hybrid import hybrid_property
from werkzeug.security import generate_password_hash, check_password_hash
import jwt

from .db import Base, SessionLocal

# ----------------------------------
# Helpers / Enums
# ----------------------------------

# Sales Pipeline Stages
SALES_STAGE_ENUM = Enum(
    'Enquiry', 'Proposal', 'Converted',
    name='sales_stage_enum'
)

# Training Pipeline Stages
TRAINING_STAGE_ENUM = Enum(
    'Training Scheduled', 'Training Conducted', 'Training Completed', 
    'PTI Created', 'Certificates Created', 'Certificates Dispatched',
    name='training_stage_enum'
)

CONTACT_MADE_ENUM = Enum('Yes', 'No', 'Unknown', name='contact_made_enum')
PREFERRED_CONTACT_ENUM = Enum('Phone', 'Email', 'WhatsApp', name='preferred_contact_enum')
AUDIT_ACTION_ENUM = Enum('create', 'update', 'delete', name='audit_action_enum')
ASSIGNMENT_TYPE_ENUM = Enum('job', 'off', 'delivery', 'note', name='assignment_type_enum')

# ----------------------------------
# Auth & Security
# ----------------------------------

class User(Base):
    __tablename__ = 'users'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    username = Column(String(100), unique=True, nullable=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    password_hash = Column(String(255), nullable=True)
    hashed_password = Column(String(255), nullable=True)
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
    
    # Relationships
    test_results = relationship("TestResult", back_populates="user", cascade="all, delete-orphan")

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

    def generate_jwt_token(self, secret_key: str) -> str:
        payload = {
            'user_id': self.id,
            'email': self.email,
            'role': self.role,
            'exp': datetime.utcnow() + timedelta(days=7),
            'iat': datetime.utcnow(),
        }
        return jwt.encode(payload, secret_key, algorithm='HS256')

    @staticmethod
    def verify_jwt_token(token: str, secret_key: str, session=None):
        try:
            payload = jwt.decode(token, secret_key, algorithms=['HS256'])
            
            if session is None:
                local_session = SessionLocal()
            else:
                local_session = session
                
            user = local_session.get(User, payload['user_id'])
            
            if session is None:
                local_session.close() 
                
            return user if user and user.is_active else None
        
        except jwt.ExpiredSignatureError:
            return None
        except jwt.InvalidTokenError:
            return None
        except Exception:
            if session is None and 'local_session' in locals():
                 local_session.close()
            return None

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
            'is_invited': self.is_invited if hasattr(self, 'is_invited') else False,
            'invitation_token': self.invitation_token if hasattr(self, 'is_invited') and self.is_invited else None,
            'invited_at': self.invited_at.isoformat() if hasattr(self, 'invited_at') and self.invited_at else None,
            'is_verified': self.is_verified,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'last_login': self.last_login.isoformat() if self.last_login else None,
        }


# DEPRECATED: legacy `User` model (application-local users). For CRM authentication and
# tenant users, use `UserMaster` (mapped to "StreemLyne_MT"."User_Master").
# Do NOT use `User` for Supabase CRM authentication — it will be removed in a follow-up.


class UserMaster(Base):
    __tablename__ = 'User_Master'
    
    user_id = Column(Integer, primary_key=True)
    employee_id = Column(Integer, nullable=True)
    user_name = Column(String(255), nullable=True)
    password = Column(String(255), nullable=True)
    created_at = Column(DateTime, nullable=False)
    updated_at = Column(Date, nullable=True)
    
    @property
    def id(self):
        return self.user_id
    
    @property
    def is_active(self):
        return True
    
    def to_dict(self):
        return {'id': self.user_id, 'employee_id': self.employee_id, 'user_name': self.user_name}

class LoginAttempt(Base):
    __tablename__ = 'login_attempts'
    __tablename__ = 'login_attempts'

    id = Column(Integer, primary_key=True)
    email = Column(String(120), nullable=False, index=True)
    ip_address = Column(String(45), nullable=False)
    success = Column(Boolean, default=False)
    attempted_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f'<LoginAttempt {self.email} - {"Success" if self.success else "Failed"}>'


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

    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


# ----------------------------------
# Core CRM Entities
# ----------------------------------

class Customer(Base):
    __tablename__ = 'customers'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String(200), nullable=False)
    address = Column(Text)  # Contains full address including PIN code for India
    phone = Column(String(50))
    email = Column(String(200))
    contact_made = Column(CONTACT_MADE_ENUM, default='Unknown')
    preferred_contact_method = Column(PREFERRED_CONTACT_ENUM)
    marketing_opt_in = Column(Boolean, default=False)
    notes = Column(Text)
    
    # Pipeline stages
    sales_stage = Column(SALES_STAGE_ENUM, default='Enquiry')
    training_stage = Column(TRAINING_STAGE_ENUM, nullable=True)  # Only set when converted
    
    # Pipeline type
    pipeline_type = Column(String(20), default='sales')  # 'sales' or 'training'

    # Project types and salesperson
    project_types = Column(JSON)
    salesperson = Column(String(200))

    # Audit
    created_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_by = Column(String(200))
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Status flag
    status = Column(String(50), default='Active')

    # Relationships
    proposals = relationship('Proposal', back_populates='customer', lazy=True, cascade='all, delete-orphan')
    assignments = relationship('Assignment', back_populates='customer', lazy=True)
    action_items = relationship('ActionItem', back_populates='customer', lazy=True)

    def save(self):
        """Save customer to database"""
        session = SessionLocal()
        try:
            session.add(self)
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def to_dict(self):
        """Convert customer to dictionary"""
        
        # Handle JSON column properly
        project_types_value = self.project_types
        if project_types_value is None:
            project_types_value = []
        elif isinstance(project_types_value, str):
            import json
            try:
                project_types_value = json.loads(project_types_value)
            except:
                project_types_value = []
        elif not isinstance(project_types_value, list):
            project_types_value = []
        
        return {
            'id': self.id,
            'name': self.name,
            'phone': self.phone or '',
            'email': self.email or '',
            'address': self.address or '',
            'salesperson': self.salesperson or '',
            'contact_made': self.contact_made or 'Unknown',
            'preferred_contact_method': self.preferred_contact_method or 'Phone',
            'marketing_opt_in': bool(self.marketing_opt_in),
            'notes': self.notes or '',
            'sales_stage': self.sales_stage or 'Enquiry',
            'training_stage': self.training_stage,
            'pipeline_type': self.pipeline_type or 'sales',
            'status': self.status or 'Active',
            'project_types': project_types_value,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
            'updated_by': self.updated_by,
        }

    def __repr__(self):
        return f'<Customer {self.name}>'


# ----------------------------------
# Jobs
# ----------------------------------

class Job(Base):
    __tablename__ = 'jobs'
    
    id = Column(Integer, primary_key=True)
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    job_number = Column(String(50), unique=True, nullable=False, index=True)
    description = Column(Text)
    status = Column(String(50), default='Pending')
    start_date = Column(Date)
    end_date = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = relationship('Customer', backref='jobs')
    
    def __repr__(self):
        return f'<Job {self.job_number}>'
    
    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'job_number': self.job_number,
            'description': self.description,
            'status': self.status,
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ----------------------------------
# Proposals (Training Proposals)
# ----------------------------------

class Proposal(Base):
    """Model for training proposals in Forklift Academy format"""
    __tablename__ = 'proposals'
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Customer Information
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    customer_name = Column(String(255), nullable=False)
    customer_designation = Column(String(255))
    customer_company = Column(String(255))
    customer_address = Column(Text)
    customer_mobile = Column(String(50))
    customer_email = Column(String(255))
    
    # Proposal Details
    quotation_number = Column(String(100), unique=True, nullable=False, index=True)
    date = Column(Date, default=datetime.utcnow)
    ifo_number = Column(String(100))
    mode_of_enquiry = Column(String(50), default='Email')
    payment_terms = Column(Text)
    
    # Items (stored as JSON array)
    items = Column(JSON, nullable=False)
    
    # Financial Details
    sub_total = Column(Float, default=0.0)
    discount_percentage = Column(Float, default=0.0)
    discount_amount = Column(Float, default=0.0)
    igst_percentage = Column(Float, default=18.0)
    igst_amount = Column(Float, default=0.0)
    grand_total = Column(Float, default=0.0)
    
    # Bank Details
    bank_name = Column(String(255))
    branch_name = Column(String(255))
    account_number = Column(String(100))
    ifsc_code = Column(String(50))
    gst_number = Column(String(50))
    
    # Terms & Conditions
    valid_for_days = Column(Integer, default=30)
    terms_conditions = Column(JSON)  # Array of strings
    notes = Column(Text)
    
    # Status
    status = Column(String(50), default='Draft')
    
    # Audit Fields
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'))
    updated_by = Column(Integer, ForeignKey('users.id'))
    created_by_name = Column(String(255))
    updated_by_name = Column(String(255))
    
    # Relationships
    customer = relationship("Customer", back_populates="proposals")
    created_by_user = relationship("User", foreign_keys=[created_by], backref="created_proposals")
    updated_by_user = relationship("User", foreign_keys=[updated_by], backref="updated_proposals")
    
    def __repr__(self):
        return f'<Proposal {self.quotation_number} - {self.customer_name}>'
    
    def to_dict(self):
        """Convert proposal to dictionary"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'customer_name': self.customer_name,
            'customer_designation': self.customer_designation,
            'customer_company': self.customer_company,
            'customer_address': self.customer_address,
            'customer_mobile': self.customer_mobile,
            'customer_email': self.customer_email,
            'quotation_number': self.quotation_number,
            'date': self.date.isoformat() if self.date else None,
            'ifo_number': self.ifo_number,
            'mode_of_enquiry': self.mode_of_enquiry,
            'payment_terms': self.payment_terms,
            'items': self.items if self.items else [],
            'sub_total': float(self.sub_total) if self.sub_total else 0.0,
            'discount_percentage': float(self.discount_percentage) if self.discount_percentage else 0.0,
            'discount_amount': float(self.discount_amount) if self.discount_amount else 0.0,
            'igst_percentage': float(self.igst_percentage) if self.igst_percentage else 0.0,
            'igst_amount': float(self.igst_amount) if self.igst_amount else 0.0,
            'grand_total': float(self.grand_total) if self.grand_total else 0.0,
            'bank_name': self.bank_name,
            'branch_name': self.branch_name,
            'account_number': self.account_number,
            'ifsc_code': self.ifsc_code,
            'gst_number': self.gst_number,
            'valid_for_days': self.valid_for_days,
            'terms_conditions': self.terms_conditions if self.terms_conditions else [],
            'notes': self.notes,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'created_by': self.created_by,
            'updated_by': self.updated_by,
            'created_by_name': self.created_by_name,
            'updated_by_name': self.updated_by_name,
        }


# ----------------------------------
# Assignments
# ----------------------------------

class Assignment(Base):
    __tablename__ = 'assignments'

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    
    type = Column(ASSIGNMENT_TYPE_ENUM, nullable=False, default='job')
    title = Column(String(255), nullable=False)
    date = Column(Date, nullable=False)
    start_date = Column(Date, nullable=True)
    end_date = Column(Date, nullable=True)
    customer_name = Column(String(200), nullable=True)
    
    user_id = Column(Integer, ForeignKey('users.id'))
    team_member = Column(String(200))
    
    created_by = Column(Integer, ForeignKey('users.id'))
    updated_by = Column(Integer, ForeignKey('users.id'))
    
    customer_id = Column(String(36), ForeignKey('customers.id'))
    job_id = Column(Integer, ForeignKey('jobs.id'), nullable=True)
    
    start_time = Column(Time)
    end_time = Column(Time)
    estimated_hours = Column(Float)
    
    notes = Column(Text)
    priority = Column(String(20), default='Medium')
    status = Column(String(20), default='Scheduled')
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    customer = relationship('Customer', back_populates='assignments')
    job = relationship('Job', backref='assignments')
    
    user = relationship(
        'User', 
        foreign_keys=[user_id], 
        backref='assigned_assignments',
        overlaps="created_by_user,updated_by_user"
    )
    
    created_by_user = relationship(
        'User', 
        foreign_keys=[created_by], 
        backref='created_assignments',
        overlaps="user,updated_by_user"
    )
    
    updated_by_user = relationship(
        'User', 
        foreign_keys=[updated_by], 
        backref='updated_assignments',
        overlaps="user,created_by_user"
    )
    
    def to_dict(self):
        """Convert assignment to dictionary with safe attribute access"""
        try:
            created_by_name = None
            try:
                if self.created_by_user:
                    created_by_name = self.created_by_user.full_name
            except Exception:
                pass
            
            updated_by_name = None
            try:
                if self.updated_by_user:
                    updated_by_name = self.updated_by_user.full_name
            except Exception:
                pass
            
            customer_name = None
            try:
                if self.customer:
                    customer_name = self.customer.name
            except Exception:
                pass
            
            return {
                'id': self.id,
                'type': self.type,
                'title': self.title,
                'date': self.date.isoformat() if self.date else None,
                'start_date': self.start_date.isoformat() if self.start_date else None,
                'end_date': self.end_date.isoformat() if self.end_date else None,
                'customer_name': self.customer_name or customer_name,
                'user_id': self.user_id,
                'team_member': self.team_member,
                'customer_id': self.customer_id,
                'start_time': self.start_time.strftime('%H:%M') if self.start_time else None,
                'end_time': self.end_time.strftime('%H:%M') if self.end_time else None,
                'estimated_hours': self.estimated_hours,
                'notes': self.notes,
                'priority': self.priority,
                'status': self.status,
                'created_at': self.created_at.isoformat() if self.created_at else None,
                'updated_at': self.updated_at.isoformat() if self.updated_at else None,
                'created_by': self.created_by,
                'created_by_name': created_by_name,
                'updated_by': self.updated_by,
                'updated_by_name': updated_by_name,
            }
        except Exception as e:
            return {
                'id': self.id,
                'type': self.type,
                'title': self.title,
                'date': self.date.isoformat() if self.date else None,
                'error': 'Error loading full assignment data'
            }


# ----------------------------------
# Audit & Action Items
# ----------------------------------

class AuditLog(Base):
    __tablename__ = 'audit_logs'

    id = Column(Integer, primary_key=True)
    entity_type = Column(String(120), nullable=False)
    entity_id = Column(String(120), nullable=False)
    action = Column(AUDIT_ACTION_ENUM, nullable=False)
    changed_by = Column(String(200))
    changed_at = Column(DateTime, default=datetime.utcnow)
    change_summary = Column(JSON)
    previous_snapshot = Column(JSON)
    new_snapshot = Column(JSON)

    def to_dict(self):
        return {
            'id': self.id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'action': self.action,
            'changed_by': self.changed_by,
            'changed_at': self.changed_at.isoformat() if self.changed_at else None,
            'change_summary': self.change_summary,
        }


class ActionItem(Base):
    __tablename__ = 'action_items'
    
    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    customer_id = Column(String(36), ForeignKey('customers.id'), nullable=False)
    stage = Column(String(50), nullable=False)
    priority = Column(String(20), default='High')
    completed = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    # Relationships
    customer = relationship("Customer", back_populates="action_items")

    def to_dict(self):
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'stage': self.stage,
            'priority': self.priority,
            'completed': self.completed,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ----------------------------------
# Test Grading System
# ----------------------------------

class TestResult(Base):
    """Model for storing test grading results"""
    __tablename__ = "test_results"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    # Participant information
    participant_name = Column(String(255), nullable=False)
    company = Column(String(255))
    date = Column(String(100))
    place = Column(String(255))
    test_type = Column(String(100))  # Pre-test, Post-test, etc.
    
    # Test details
    mhe_type = Column(String(50), nullable=False)  # BOPT, FORKLIFT, REACH_TRUCK, STACKER
    total_marks_obtained = Column(Integer, nullable=False)
    total_marks = Column(Integer, nullable=False)
    percentage = Column(Float, nullable=False)
    grade = Column(String(20), nullable=False)  # Pass/Fail
    
    # JSON data
    answers_json = Column(Text)  # Student's answers as JSON
    details_json = Column(Text)  # Detailed question-by-question breakdown as JSON
    image_base64 = Column(Text)  # Base64 encoded image of the test paper
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="test_results")
    
    def __repr__(self):
        return f"<TestResult {self.id} - {self.participant_name} - {self.mhe_type} - {self.grade}>"
    
    def to_dict(self):
        """Convert test result to dictionary"""
        import json as json_module
        
        return {
            'id': self.id,
            'user_id': self.user_id,
            'participant_name': self.participant_name,
            'company': self.company,
            'date': self.date,
            'place': self.place,
            'test_type': self.test_type,
            'mhe_type': self.mhe_type,
            'total_marks_obtained': self.total_marks_obtained,
            'total_marks': self.total_marks,
            'percentage': self.percentage,
            'grade': self.grade,
            'answers': json_module.loads(self.answers_json) if self.answers_json else {},
            'details': json_module.loads(self.details_json) if self.details_json else [],
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
        }


# ----------------------------------
# Data Imports
# ----------------------------------

class DataImport(Base):
    __tablename__ = 'data_imports'

    id = Column(Integer, primary_key=True)
    filename = Column(String(255), nullable=False)
    import_type = Column(String(50), nullable=False)
    status = Column(String(20), default='processing')
    records_processed = Column(Integer, default=0)
    records_failed = Column(Integer, default=0)
    error_log = Column(Text)
    imported_by = Column(String(200))
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    def __repr__(self):
        return f'<DataImport {self.filename} ({self.status})>'

    def to_dict(self):
        return {
            'id': self.id,
            'filename': self.filename,
            'import_type': self.import_type,
            'status': self.status,
            'records_processed': self.records_processed,
            'records_failed': self.records_failed,
            'error_log': self.error_log,
            'imported_by': self.imported_by,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'completed_at': self.completed_at.isoformat() if self.completed_at else None,
        }


# ----------------------------------
# Customer Documents
# ----------------------------------

class CustomerDocument(Base):
    """Model for storing customer documents (contracts, forms, certificates, etc.)"""
    __tablename__ = 'customer_documents'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    
    # Foreign Keys (nullable with SET NULL on delete)
    customer_id = Column(String(36), ForeignKey('customers.id', ondelete='SET NULL'), nullable=True, index=True)
    proposal_id = Column(Integer, ForeignKey('proposals.id', ondelete='SET NULL'), nullable=True, index=True)
    
    # File Information
    file_name = Column(String(255), nullable=False)
    file_path = Column(Text, nullable=False)
    file_type = Column(String(100), nullable=True)  # e.g., 'pdf', 'docx', 'image/png'
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    
    # Relationships
    customer = relationship('Customer', backref='documents', foreign_keys=[customer_id])
    proposal = relationship('Proposal', backref='documents', foreign_keys=[proposal_id])
    
    def __repr__(self):
        return f'<CustomerDocument {self.id} - {self.file_name}>'
    
    def to_dict(self):
        """Convert document to dictionary"""
        return {
            'id': self.id,
            'customer_id': self.customer_id,
            'proposal_id': self.proposal_id,
            'file_name': self.file_name,
            'file_path': self.file_path,
            'file_type': self.file_type,
            'created_at': self.created_at.isoformat() if self.created_at else None,
        }

