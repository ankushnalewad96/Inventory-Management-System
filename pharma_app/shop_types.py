"""
Shop types and the features each one uses.

This is the ONE place that says which feature is on for which kind of
shop. Code must ask for a feature, never for a shop type:

    features = get_features(retailer)
    if features.expiry_tracking:
        ...

    {% if features.expiry_tracking %} ... {% endif %}    (templates)

To change what a shop type can do, edit SHOP_TYPE_FEATURES below.
This module must not import models (models.py imports it).
"""

# ------------------------------------------------------------------ shop types

GENERAL = "general"
STATIONERY = "stationery"
COSMETICS = "cosmetics"
PHARMACY = "pharmacy"
HARDWARE = "hardware"

SHOP_TYPE_CHOICES = [
    (GENERAL, "General / Kirana store"),
    (STATIONERY, "Stationery"),
    (COSMETICS, "Cosmetics / Gifts / Mobile accessories"),
    (PHARMACY, "Pharmacy"),
    (HARDWARE, "Hardware"),
]

DEFAULT_SHOP_TYPE = GENERAL

SHOP_TYPE_LABELS = dict(SHOP_TYPE_CHOICES)


# ------------------------------------------------------------------ features

# Short description of every feature (shown to the admin).
FEATURE_LABELS = {
    "decimal_quantity": "Sell loose quantities (e.g. 2.5 kg, 1.5 m)",
    "unit_conversion": "Buy in one unit, sell in another (box -> piece)",
    "mrp_required": "MRP is required on products",
    "hsn_required": "HSN code is required on products",
    "allow_below_cost_sale": "Selling below purchase price is allowed (warning only)",
    "batch_tracking": "Batch numbers on stock",
    "expiry_tracking": "Expiry dates on stock",
    "prescription_details": "Patient / doctor details on sales",
    "drug_licence": "Drug licence on the shop and invoices",
    "price_levels": "Retail and wholesale prices",
    "quotations": "Quotations / estimates",
    "b2b_tax_split": "CGST + SGST / IGST split on invoices",
    "product_specification": "Specification on products (size, gauge, grade)",
}

FEATURE_NAMES = tuple(FEATURE_LABELS)

_YES, _NO = True, False

#                         general stationery cosmetics pharmacy hardware
_FEATURE_TABLE = {
    "decimal_quantity":      (_YES,   _NO,       _NO,      _NO,     _YES),
    "unit_conversion":       (_YES,   _YES,      _NO,      _YES,    _YES),
    "mrp_required":          (_YES,   _YES,      _YES,     _YES,    _NO),
    "hsn_required":          (_YES,   _YES,      _YES,     _YES,    _YES),
    "allow_below_cost_sale": (_NO,    _NO,       _NO,      _NO,     _YES),
    "batch_tracking":        (_NO,    _NO,       _NO,      _YES,    _NO),
    "expiry_tracking":       (_NO,    _NO,       _NO,      _YES,    _NO),
    "prescription_details":  (_NO,    _NO,       _NO,      _YES,    _NO),
    "drug_licence":          (_NO,    _NO,       _NO,      _YES,    _NO),
    "price_levels":          (_NO,    _NO,       _NO,      _NO,     _YES),
    "quotations":            (_NO,    _NO,       _NO,      _NO,     _YES),
    "b2b_tax_split":         (_YES,   _YES,      _YES,     _YES,    _YES),
    "product_specification": (_NO,    _NO,       _NO,      _NO,     _YES),
}

_COLUMN_ORDER = (GENERAL, STATIONERY, COSMETICS, PHARMACY, HARDWARE)

# shop type -> {feature name: True/False}
SHOP_TYPE_FEATURES = {
    shop_type: {
        feature: _FEATURE_TABLE[feature][column]
        for feature in FEATURE_NAMES
    }
    for column, shop_type in enumerate(_COLUMN_ORDER)
}

# Fail fast if the table and the lists ever drift apart.
assert set(_FEATURE_TABLE) == set(FEATURE_NAMES), "Feature table and FEATURE_LABELS differ"
assert set(SHOP_TYPE_FEATURES) == set(SHOP_TYPE_LABELS), "Every shop type needs a feature column"


class Features:
    """
    Read-only set of feature switches.

        features.expiry_tracking   -> True / False
        features.enabled           -> list of feature names that are on
        features.shop_type         -> "pharmacy", ... (None for the admin view)

    Asking for a feature that does not exist raises AttributeError, so a
    typo in Python code fails loudly instead of silently being "off".
    """

    __slots__ = ("_flags", "shop_type")

    def __init__(self, flags, shop_type=None):
        unknown = set(flags) - set(FEATURE_NAMES)
        if unknown:
            raise ValueError(f"Unknown feature(s): {', '.join(sorted(unknown))}")

        object.__setattr__(self, "_flags", {name: bool(flags.get(name, False)) for name in FEATURE_NAMES})
        object.__setattr__(self, "shop_type", shop_type)

    def __getattr__(self, name):
        flags = object.__getattribute__(self, "_flags")
        if name in flags:
            return flags[name]
        raise AttributeError(f"Unknown feature: {name!r}")

    def __setattr__(self, name, value):
        raise AttributeError("Features are read-only")

    def __getitem__(self, name):
        return getattr(self, name)

    def __contains__(self, name):
        return bool(self._flags.get(name, False))

    @property
    def enabled(self):
        return [name for name in FEATURE_NAMES if self._flags[name]]

    def as_dict(self):
        return dict(self._flags)

    def __repr__(self):
        return f"<Features {self.shop_type or 'all'}: {', '.join(self.enabled) or 'none'}>"


def normalize_shop_type(value):
    """A valid shop type, or the default for empty/unknown values."""

    return value if value in SHOP_TYPE_LABELS else DEFAULT_SHOP_TYPE


def features_for_type(shop_type):
    shop_type = normalize_shop_type(shop_type)
    return Features(SHOP_TYPE_FEATURES[shop_type], shop_type=shop_type)


def get_features(retailer):
    """
    Features of a shop (a Retailer). Use this for every on/off decision
    about a specific shop, including when the admin acts for that shop.
    With no shop, every optional feature is off.
    """

    if retailer is None:
        return Features({}, shop_type=None)

    return features_for_type(getattr(retailer, "shop_type", None))


def shop_type_feature_labels():
    """{shop type: [labels of its features]} for forms and the admin."""

    return {
        shop_type: [FEATURE_LABELS[name] for name in features_for_type(shop_type).enabled]
        for shop_type in SHOP_TYPE_LABELS
    }


def features_for_types(shop_types):
    """
    Union of the features of these shop types (e.g. the types of the
    shops that exist). Used for what the admin sees in the menu.
    """

    types = {normalize_shop_type(shop_type) for shop_type in shop_types}
    flags = {
        name: any(SHOP_TYPE_FEATURES[shop_type][name] for shop_type in types)
        for name in FEATURE_NAMES
    }
    return Features(flags, shop_type=None)


def shop_type_labels_with(feature):
    """Labels of the shop types that have a feature, e.g. ["Pharmacy"]."""

    return [
        SHOP_TYPE_LABELS[shop_type]
        for shop_type in SHOP_TYPE_LABELS
        if SHOP_TYPE_FEATURES[shop_type][feature]
    ]


def all_features():
    """
    Union of every shop type's features. Used only for what the admin
    *sees* (menus) across all shops; server-side checks for a given shop
    must still use get_features(that_shop).
    """

    flags = {
        name: any(SHOP_TYPE_FEATURES[shop_type][name] for shop_type in SHOP_TYPE_FEATURES)
        for name in FEATURE_NAMES
    }
    return Features(flags, shop_type=None)
