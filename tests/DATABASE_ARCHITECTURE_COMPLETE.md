# StreemLyne Database Architecture - Complete Analysis

## Executive Summary

**Database**: PostgreSQL (Supabase)  
**Schema**: `StreemLyne_MT` (Multi-Tenant)  
**Total Tables**: 27  
**Architecture Type**: Multi-Tenant SaaS Platform  
**Primary Use Case**: Energy/Solar Contract Management & CRM

---

## 1. Database Architecture Overview

### **Multi-Tenant Design Pattern**
- **Shared Database, Shared Schema** approach
- Tenant isolation achieved through `tenant_id` foreign key filtering
- Core tenant table: `Tenant_Master`

### **Data Integrity**
- 39 Foreign Key Relationships
- Referential integrity enforced at database level
- Mix of CASCADE and RESTRICT delete rules

---

## 2. Complete Table Inventory (27 Tables)

### **2.1 Core Tenant & Authentication (3 tables)**

#### **Tenant_Master** (7 columns)
**Purpose**: Central tenant/organization registry  
**Key Columns**:
- `Tenant_id` (PK, smallint)
- `tenant_company_name` (varchar)
- `tenant_contact_name` (varchar)
- `onboarding_Date` (date)
- `is_active` (boolean)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 1 row (Demo Client)

---

#### **User_Master** (6 columns)
**Purpose**: User authentication credentials  
**Key Columns**:
- `user_id` (PK, smallint)
- `employee_id` (FK → Employee_Master)
- `user_name` (varchar)
- `password` (varchar) - stored credentials
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows  
**Note**: Users are linked to employees, NOT directly to tenants

---

#### **Employee_Master** (14 columns)
**Purpose**: Employee profiles within tenants  
**Key Columns**:
- `employee_id` (PK, smallint)
- `tenant_id` (FK → Tenant_Master, bigint) **✓ Multi-tenant**
- `employee_name` (varchar)
- `employee_designation_id` (FK → Designation_Master)
- `phone`, `email` (varchar)
- `date_of_birth`, `date_of_joining` (date)
- `id_type`, `id_number` (varchar) - Identity docs
- `role_ids` (varchar) - Comma-separated role IDs
- `commission_percentage` (real)
- `created_on`, `updated_on` (timestamps)

**Current Data**: 0 rows  
**Delete Rule**: CASCADE from Tenant_Master

---

### **2.2 CRM & Sales Management (3 tables)**

#### **Client_Master** (12 columns)
**Purpose**: Customer/Client records  
**Key Columns**:
- `client_id` (PK, smallint)
- `tenant_id` (FK → Tenant_Master, smallint) **✓ Multi-tenant**
- `client_company_name` (varchar, NOT NULL)
- `client_contact_name` (varchar)
- `address` (varchar)
- `country_id` (FK → Country_Master)
- `post_code` (varchar)
- `client_phone`, `client_email`, `client_website` (varchar)
- `default_currency_id` (FK → Currency_Master)
- `created_at` (timestamp)

**Current Data**: 1 row ("ABC Architects")

---

#### **Opportunity_Details** (10 columns)
**Purpose**: Sales leads/opportunities  
**Key Columns**:
- `opportunity_id` (PK, smallint)
- `client_id` (FK → Client_Master, smallint, NOT NULL)
- `opportunity_title` (varchar, NOT NULL)
- `opportunity_description` (varchar)
- `opportunity_date` (date)
- `opportunity_owner_employee_id` (FK → Employee_Master, smallint)
- `stage_id` (FK → Stage_Master, smallint, NOT NULL)
- `opportunity_value` (smallint) **⚠️ Max: 32,767**
- `currency_id` (FK → Currency_Master)
- `created_at` (timestamp)

**Current Data**: 0 rows  
**⚠️ Critical**: NO direct `tenant_id` - isolation via `client_id` → `Client_Master.tenant_id`

---

#### **Client_Interactions** (8 columns)
**Purpose**: Track customer communications  
**Key Columns**:
- `interaction_id` (PK, smallint)
- `client_id` (FK → Client_Master, smallint, NOT NULL)
- `contact_date` (date, NOT NULL)
- `contact_method` (smallint, NOT NULL)
- `notes` (varchar)
- `next_steps` (varchar)
- `reminder_date` (date)
- `created_at` (timestamp)

**Current Data**: 0 rows

---

### **2.3 Project & Contract Management (4 tables)**

#### **Project_Details** (13 columns)
**Purpose**: Active project/job records  
**Key Columns**:
- `project_id` (PK, smallint)
- `project_name` (varchar, NOT NULL)
- `project_description` (varchar)
- `project_location` (varchar)
- `opportunity_id` (FK → Opportunity_Details)
- `project_start_date`, `project_end_date` (date)
- `project_status` (varchar) - e.g., "In Progress", "Complete"
- `employee_id` (FK → Employee_Master) - Project manager
- `project_value` (numeric)
- `actual_cost` (numeric)
- `project_margin` (numeric)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows  
**⚠️ Critical**: NO direct `tenant_id` - isolation via relationships

---

#### **Energy_Contract_Master** (13 columns)
**Purpose**: Energy/solar contracts  
**Key Columns**:
- `contract_id` (PK, smallint)
- `Tenant_id` (FK → Tenant_Master, bigint, NOT NULL) **✓ Multi-tenant**
- `contract_reference_number` (varchar, NOT NULL)
- `project_id` (FK → Project_Details)
- `service_id` (FK → Services_Master)
- `employee_id` (FK → Employee_Master) - Contract owner
- `contract_start_date`, `contract_end_date` (date)
- `contract_value` (numeric)
- `currency_id` (FK → Currency_Master)
- `contract_status` (varchar) - "Active", "Pending", "Expired"
- `contract_terms` (varchar)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows

---

#### **Proposal_Master** (11 columns)
**Purpose**: Sales proposals/quotes  
**Key Columns**:
- `proposal_id` (PK, smallint)
- `proposal_reference` (varchar, NOT NULL)
- `client_id` (FK → Client_Master, smallint, NOT NULL)
- `proposal_date` (date, NOT NULL)
- `proposal_valid_till` (date)
- `total_amount` (numeric)
- `currency_id` (FK → Currency_Master)
- `proposal_status` (varchar) - "Draft", "Sent", "Accepted", "Rejected"
- `notes` (varchar)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows

---

#### **Proposal_Details** (7 columns)
**Purpose**: Line items for proposals  
**Key Columns**:
- `proposal_details_id` (PK, smallint)
- `proposal_id` (FK → Proposal_Master, smallint, NOT NULL)
- `service_id` (FK → Services_Master)
- `quantity` (real)
- `uom_id` (FK → UOM_Master) - Unit of measure
- `unit_price` (numeric)
- `line_total` (numeric)

**Current Data**: 0 rows

---

### **2.4 Financial Management (3 tables)**

#### **Invoice_Master** (14 columns)
**Purpose**: Customer invoices  
**Key Columns**:
- `invoice_id` (PK, smallint)
- `invoice_number` (varchar, NOT NULL)
- `client_id` (FK → Client_Master, smallint, NOT NULL)
- `project_id` (FK → Project_Details)
- `proposal_id` (FK → Proposal_Master)
- `invoice_date` (date, NOT NULL)
- `due_date` (date)
- `total_amount` (numeric)
- `currency_id` (FK → Currency_Master)
- `invoice_status` (varchar) - "Pending", "Paid", "Overdue"
- `payment_terms` (varchar)
- `notes` (varchar)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows

---

#### **Invoice_Details** (7 columns)
**Purpose**: Invoice line items  
**Key Columns**:
- `invoice_details_id` (PK, smallint)
- `invoice_id` (FK → Invoice_Master, smallint, NOT NULL)
- `service_id` (FK → Services_Master)
- `quantity` (real)
- `uom_id` (FK → UOM_Master)
- `unit_price` (numeric)
- `line_total` (numeric)

**Current Data**: 0 rows

---

#### **Services_Master** (11 columns)
**Purpose**: Service/product catalog  
**Key Columns**:
- `service_id` (PK, smallint)
- `tenant_id` (FK → Tenant_Master, bigint, NOT NULL) **✓ Multi-tenant**
- `service_name` (varchar, NOT NULL)
- `service_description` (varchar)
- `service_category` (varchar)
- `unit_price` (numeric)
- `currency_id` (FK → Currency_Master)
- `is_active` (boolean)
- `service_sku` (varchar)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows

---

### **2.5 Master Data / Reference Tables (9 tables)**

#### **Country_Master** (4 columns)
- `country_id` (PK), `country_name`, `country_isd_code`, `created_at`
- **Current Data**: 248 rows (complete country list)

#### **Currency_Master** (4 columns)
- `currency_id` (PK), `currency_name`, `currency_code`, `created_at`
- **Current Data**: 165 rows (global currencies)

#### **Designation_Master** (3 columns)
- `designation_id` (PK), `designation_description`, `created_at`
- **Current Data**: 0 rows

#### **Stage_Master** (5 columns)
**Purpose**: CRM pipeline stages  
**Key Columns**:
- `stage_id` (PK, smallint)
- `stage_name` (varchar, NOT NULL) - e.g., "Lead", "Proposal", "Won"
- `stage_order` (smallint)
- `stage_type` (varchar) - "Opportunity", "Project", etc.
- `created_at` (timestamp)

**Current Data**: 5 rows ("Lead", "Proposal", "Won", "Site Survey", "Procurement")

#### **Supplier_Master** (5 columns)
- `supplier_id` (PK), `supplier_company_name`, `supplier_contact_name`, `supplier_provisions`, `created_at`
- **Current Data**: 0 rows

#### **UOM_Master** (3 columns)
**Purpose**: Units of Measure  
- `uom_id` (PK), `uom_description` (e.g., "Each", "Meter", "KWh"), `created_at`
- **Current Data**: 0 rows

#### **Role_Master** (5 columns)
**Purpose**: User role definitions  
**Key Columns**:
- `role_id` (PK, smallint)
- `role_name` (varchar, NOT NULL)
- `role_description` (varchar)
- `is_system_role` (boolean)
- `created_at` (timestamp)

**Current Data**: 0 rows

#### **Permission_Catalog** (4 columns)
**Purpose**: Available system permissions  
- `permission_id` (PK), `permission_name`, `permission_description`, `created_at`
- **Current Data**: 0 rows

#### **Role_Permission_Mapping** (5 columns)
**Purpose**: Assign permissions to roles  
- `role_permission_mapping_id` (PK)
- `role_id` (FK → Role_Master)
- `permission_id` (FK → Permission_Catalog)
- `can_create`, `can_read`, `can_update`, `can_delete` (booleans)

**Current Data**: 0 rows

---

### **2.6 SaaS Configuration (4 tables)**

#### **Module_Master** (8 columns)
**Purpose**: Available platform modules  
**Key Columns**:
- `module_id` (PK, smallint)
- `module_name` (varchar, NOT NULL) - e.g., "CRM", "Projects", "Invoicing"
- `module_code` (varchar)
- `module_description` (varchar)
- `is_active` (boolean)
- `module_icon` (varchar)
- `display_order` (smallint)
- `created_at` (timestamp)

**Current Data**: 0 rows

#### **Subscription_Plans** (11 columns)
**Purpose**: SaaS subscription tiers  
**Key Columns**:
- `subscription_id` (PK, bigint)
- `subscription_name` (varchar, NOT NULL) - e.g., "Basic", "Pro", "Enterprise"
- `subscription_description` (varchar)
- `is_base_plan` (boolean)
- `is_active` (boolean)
- `billing_cycle` (smallint) - Monthly/Yearly
- `price` (numeric)
- `currency_id` (FK → Currency_Master)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows

#### **Subscription_Module_Mapping** (4 columns)
**Purpose**: Which modules are in which subscription plans  
- `subscription_module_mapping_id` (PK)
- `subscription_id` (FK → Subscription_Plans)
- `module_id` (FK → Module_Master)
- `created_at` (timestamp)

**Current Data**: 0 rows

#### **Tenant_Module_Mapping** (4 columns)
**Purpose**: Which modules a tenant has access to  
- `tenant_module_mapping_id` (PK)
- `tenant_id` (FK → Tenant_Master)
- `module_id` (FK → Module_Master)
- `created_at` (timestamp)

**Current Data**: 0 rows

#### **Tenant_Subscription** (9 columns)
**Purpose**: Tenant subscription history  
- `tenant_subscription_mapping_id` (PK)
- `tenant_id` (FK → Tenant_Master, bigint)
- `subscription_id` (FK → Subscription_Plans, bigint)
- `subscription_start_date`, `subscription_end_date` (date)
- `is_active` (boolean)
- `auto_renew` (boolean)
- `created_at`, `updated_at` (timestamps)

**Current Data**: 0 rows

---

## 3. Multi-Tenant Architecture Analysis

### **Tables WITH Direct Tenant Isolation** (5 tables)
✓ **Tenant_Master** - Core tenant table  
✓ **Employee_Master** - `tenant_id` (bigint)  
✓ **Client_Master** - `tenant_id` (smallint)  
✓ **Services_Master** - `tenant_id` (bigint)  
✓ **Energy_Contract_Master** - `Tenant_id` (bigint)  

### **Tables WITHOUT Direct tenant_id** (22 tables)
These rely on **indirect tenant isolation** through foreign keys:

**Via Client_Master:**
- Opportunity_Details (via `client_id`)
- Client_Interactions (via `client_id`)
- Proposal_Master (via `client_id`)
- Invoice_Master (via `client_id`)

**Via Project_Details:**
- Project_Details (via `opportunity_id` → `client_id`)

**Via Employee_Master:**
- User_Master (via `employee_id`)

**Master/Reference Tables (No Tenant):**
- Country_Master, Currency_Master, UOM_Master, Stage_Master, Designation_Master, Supplier_Master
- Role_Master, Permission_Catalog, Role_Permission_Mapping
- Module_Master, Subscription_Plans, Subscription_Module_Mapping

**Tenant-Specific Config:**
- Tenant_Module_Mapping, Tenant_Subscription

---

## 4. Database Relationships (39 Foreign Keys)

### **Key Relationship Chains:**

#### **CRM Flow:**
```
Tenant_Master
  └─> Client_Master (tenant_id)
       ├─> Opportunity_Details (client_id)
       │    └─> Project_Details (opportunity_id)
       │         ├─> Energy_Contract_Master (project_id)
       │         └─> Invoice_Master (project_id)
       ├─> Proposal_Master (client_id)
       │    └─> Proposal_Details (proposal_id)
       └─> Client_Interactions (client_id)
```

#### **Employee/User Flow:**
```
Tenant_Master
  └─> Employee_Master (tenant_id)
       ├─> User_Master (employee_id)
       ├─> Opportunity_Details (opportunity_owner_employee_id)
       ├─> Project_Details (employee_id)
       └─> Energy_Contract_Master (employee_id)
```

#### **Financial Flow:**
```
Client_Master
  └─> Invoice_Master (client_id)
       └─> Invoice_Details (invoice_id)
            └─> Services_Master (service_id)
```

---

## 5. Critical Design Observations

### **✅ Strengths:**
1. **Robust Referential Integrity** - 39 FK relationships enforce data consistency
2. **Complete Master Data** - 248 countries, 165 currencies pre-loaded
3. **Flexible Role-Based Access Control** - Separate Role/Permission tables
4. **Multi-Currency Support** - Currency FKs throughout financial tables
5. **Audit Trail** - `created_at`, `updated_at` timestamps on most tables

### **⚠️ Design Issues:**

1. **Inconsistent Tenant ID Data Types:**
   - `Tenant_Master.Tenant_id` = `smallint`
   - `Employee_Master.tenant_id` = `bigint`
   - `Energy_Contract_Master.Tenant_id` = `bigint`
   - `Client_Master.tenant_id` = `smallint`
   - **Risk**: Type mismatch can cause FK failures

2. **Opportunity_Details - No Direct Tenant ID:**
   - Must JOIN through `Client_Master` for tenant filtering
   - **Impact**: More complex queries, potential performance issues

3. **Smallint Limitations:**
   - `opportunity_value` = smallint (max 32,767)
   - **Risk**: Cannot store values > £32,767
   - **Recommendation**: Change to `numeric` or `integer`

4. **No Soft Deletes:**
   - Some FKs use `CASCADE`, others `RESTRICT`
   - No `deleted_at` or `is_deleted` columns
   - **Risk**: Hard deletes lose historical data

5. **User_Master Security:**
   - Password storage unclear (hash algorithm not visible)
   - No `is_active`, `last_login`, `failed_attempts` columns
   - **Risk**: Limited authentication security

6. **Missing Indexes (Not Visible):**
   - Cannot verify if tenant_id columns are indexed
   - **Recommendation**: Ensure indexes on all FK columns

---

## 6. Table Categorization by Business Function

### **Core Platform (7 tables)**
- Tenant_Master, User_Master, Employee_Master
- Role_Master, Permission_Catalog, Role_Permission_Mapping, Designation_Master

### **CRM & Sales (3 tables)**
- Client_Master, Opportunity_Details, Client_Interactions

### **Project Management (2 tables)**
- Project_Details, Energy_Contract_Master

### **Financial (5 tables)**
- Proposal_Master, Proposal_Details, Invoice_Master, Invoice_Details, Services_Master

### **Master Data (6 tables)**
- Country_Master, Currency_Master, Stage_Master, Supplier_Master, UOM_Master, Module_Master

### **SaaS Configuration (4 tables)**
- Subscription_Plans, Subscription_Module_Mapping, Tenant_Module_Mapping, Tenant_Subscription

---

## 7. Current Data State

**Active Data:**
- ✅ 1 Tenant ("Demo Client")
- ✅ 1 Client ("ABC Architects")
- ✅ 5 Stages (Lead, Proposal, Won, Site Survey, Procurement)
- ✅ 248 Countries
- ✅ 165 Currencies

**Empty Tables (22):**
All other tables are empty - system is in initial setup state.

---

## 8. Recommendations for CRM Implementation

### **Immediate Actions:**
1. **Fix Data Type Inconsistencies** - Standardize tenant_id to bigint
2. **Add opportunity_value Validation** - Or change to numeric type
3. **Implement Soft Deletes** - Add is_deleted, deleted_at columns
4. **Create Database Indexes** - On all FK columns, especially tenant_id
5. **Add User Security Fields** - is_active, last_login, failed_login_attempts

### **For Frontend Integration:**
1. **Use Client_Master JOIN** for Opportunity_Details tenant filtering
2. **Handle smallint limits** in UI (max 32,767 for opportunity values)
3. **Implement proper error handling** for FK constraint violations
4. **Cache master data** (countries, currencies, stages) on frontend

---

## 9. API Alignment

**Current Backend CRM API (`/api/crm/leads`):**
- Returns: `opportunity_id`, `opportunity_title`, `client_id`, `opportunity_value`, `stage_id`
- Filters by: `tenant_id` (via Client_Master JOIN)

**Current Frontend Expectations:**
- Expects: `id`, `name`, `email`, `company`, `status: "Lead"`, `value`
- Calls: `fetchWithAuth("customers")` ❌ Wrong endpoint

**Required Changes:**
- Update frontend to call `/api/crm/leads`
- Map backend structure to frontend display
- Add `X-Tenant-ID` header to all CRM requests

---

## Summary

StreemLyne is a **well-structured multi-tenant SaaS platform** for energy/solar contract management with:
- **27 tables** across 6 functional areas
- **Strong referential integrity** with 39 FK relationships
- **Hybrid tenant isolation** (direct + indirect through FK chains)
- **Production-ready master data** (countries, currencies)
- **Flexible subscription/module system** for SaaS monetization

**Current State**: Initial deployment with minimal seed data (1 tenant, 1 client, 5 stages).

**Next Steps**: Implement comprehensive CRM CRUD operations, enhance security, optimize for scale.
