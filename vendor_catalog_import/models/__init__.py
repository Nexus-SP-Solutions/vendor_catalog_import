# -*- coding: utf-8 -*-

# --- MODELOS BASE ---
from . import vendor_catalog
from . import product_template
from . import product_supplierinfo
from . import product_image
from . import settings

# --- PATCHES ACTIVOS ---
# (sin enriquecimiento REST por SKU/Partnumber)
# from . import _infortisa_rest_patch
from . import _gallery_multi_images_patch
from . import _ecom_public_category_patch
from . import _config_helpers
from . import _kwargs_inject_patch
from . import _get_stock_api_patch
from . import _website_stock_refresh_patch
from . import _stats_field_patch

# Bloquear consultas JSON de stock si está el flag (cortacircuito)
from . import _disable_quick_stock_patch

# Stock desde CSV local (acción manual)
from . import _local_csv_stock_update
from . import _remap_categories_from_csv
