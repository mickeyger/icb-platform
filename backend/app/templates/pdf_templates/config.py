# PDF Template Configuration
# Maps trailer types to their respective templates

PDF_TEMPLATES = {
    # Exact matches (case-insensitive)
    'explosive': {
        'template': 'explosive.html',
        'background_pdf': r'C:\Users\micge\Documents\Burt Costing Model\EXPLOSIVE Body Template 2026.pdf',
        'use_overlay': True,  # If True, overlay on background PDF; if False, use HTML only
        'overlay_positions': {
            'trailer_type': {'page': 0, 'x': 50, 'y': 650},  # x,y in points from bottom-left
            'length': {'page': 0, 'x': 80, 'y': 600},
            'width': {'page': 0, 'x': 80, 'y': 580},
            'height': {'page': 0, 'x': 80, 'y': 560},
            'price': {'page': 0, 'x': 50, 'y': 500},
        }
    },

    # Pattern matches (searched in trailer name)
    'bakery': {
        'template': 'bakery.html',
        'background_pdf': r'C:\Users\micge\Documents\Burt Costing Model\Bakery Body Template 2026.pdf',
        'use_overlay': False,
    },

    'dry freight': {
        'template': 'dry_freight.html',
        'background_pdf': r'C:\Users\micge\Documents\Burt Costing Model\Dry Freight Template 2026.pdf',
        'use_overlay': False,
    },

    'freezer': {
        'template': 'freezer.html',
        'background_pdf': r'C:\Users\micge\Documents\Burt Costing Model\Freezer Body Template 2026.pdf',
        'use_overlay': False,
    },

    'meat': {
        'template': 'meat.html',
        'background_pdf': r'C:\Users\micge\Documents\Burt Costing Model\Meathanger Body Template 2026.pdf',
        'use_overlay': False,
    },

    'rhinorange': {
        'template': 'rhinorange.html',
        'background_pdf': r'C:\Users\micge\Documents\Burt Costing Model\Rhinorange Freezer Body Template 2026.pdf',
        'use_overlay': False,
    },
}

def get_template_config(trailer_name):
    """
    Get template configuration for a trailer type.
    Returns (template_name, config_dict) or (None, None) if not found.
    """
    trailer_lower = trailer_name.lower()

    # Check exact matches first
    if trailer_lower in PDF_TEMPLATES:
        config = PDF_TEMPLATES[trailer_lower]
        return config['template'], config

    # Check pattern matches
    for pattern, config in PDF_TEMPLATES.items():
        if pattern in trailer_lower:
            return config['template'], config

    # Default fallback
    return 'default.html', {
        'template': 'default.html',
        'background_pdf': None,
        'use_overlay': False,
    }