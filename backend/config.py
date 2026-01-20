# config.py - Configuration constants

# File upload configuration
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'bmp', 'tiff', 'webp'}

# Form columns configuration for data processing
FORM_COLUMNS = [
    'customer_name', 'customer_phone', 'customer_email', 'customer_address',
    'door_colour', 'door_style', 'worktop_colour', 'worktop_style',
    'handles_style', 'handles_colour', 'bedside_cabinets_style',
    'bedside_cabinets_qty', 'dresser_desk_present', 'dresser_desk_qty_size',
    'internal_mirror_present', 'internal_mirror_qty_size', 'mirror_style',
    'mirror_qty', 'soffit_lights_type', 'soffit_lights_colour',
    'soffit_lights_qty', 'gable_lights_colour', 'gable_lights_qty',
    'special_requirements', 'budget_range', 'preferred_completion_date'
]

# Kitchen design sections for form organization
FORM_SECTIONS = [
    {
        'title': 'Customer Information',
        'fields': ['customer_name', 'customer_phone', 'customer_email', 'customer_address']
    },
    {
        'title': 'Kitchen Design Preferences', 
        'fields': ['door_colour', 'door_style', 'worktop_colour', 'worktop_style', 'handles_style', 'handles_colour']
    },
    {
        'title': 'Bedside Cabinets',
        'fields': ['bedside_cabinets_style', 'bedside_cabinets_qty']
    },
    {
        'title': 'Dresser/Desk',
        'fields': ['dresser_desk_present', 'dresser_desk_qty_size']
    },
    {
        'title': 'Internal Mirror',
        'fields': ['internal_mirror_present', 'internal_mirror_qty_size']
    },
    {
        'title': 'Mirror',
        'fields': ['mirror_style', 'mirror_qty']
    },
    {
        'title': 'Soffit Lights',
        'fields': ['soffit_lights_type', 'soffit_lights_colour', 'soffit_lights_qty']
    },
    {
        'title': 'Gable Lights',
        'fields': ['gable_lights_colour', 'gable_lights_qty']
    },
    {
        'title': 'Additional Information',
        'fields': ['special_requirements', 'budget_range', 'preferred_completion_date']
    }
]

# Checkbox fields for special handling
CHECKBOX_FIELDS = [
    'dresser_desk_present',
    'internal_mirror_present'
]

# OpenAI Configuration (if using)
OPENAI_MODEL = "gpt-4-vision-preview"
OPENAI_MAX_TOKENS = 1000

# Default form values
DEFAULT_FORM_VALUES = {
    'door_colour': '',
    'door_style': '',
    'worktop_colour': '',
    'worktop_style': '',
    'handles_style': '',
    'handles_colour': '',
    'bedside_cabinets_style': '',
    'bedside_cabinets_qty': '',
    'dresser_desk_present': '',
    'dresser_desk_qty_size': '',
    'internal_mirror_present': '',
    'internal_mirror_qty_size': '',
    'mirror_style': '',
    'mirror_qty': '',
    'soffit_lights_type': '',
    'soffit_lights_colour': '',
    'soffit_lights_qty': '',
    'gable_lights_colour': '',
    'gable_lights_qty': '',
}

# Global variable for structured data (if needed for your existing code)
latest_structured_data = {}

# Helper functions
def allowed_file(filename):
    """Check if the uploaded file has an allowed extension"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def get_form_field_display_name(field_name):
    """Convert field name to display name"""
    return field_name.replace('_', ' ').title()