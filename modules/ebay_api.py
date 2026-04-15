"""
eBay Hub UK - eBay API Module
Real eBay Trading API (XML) integration using Auth'n'Auth token.
Also uses Finding API (REST) for completed item searches.
"""

import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta


# eBay Trading API endpoint (production)
TRADING_API_URL = "https://api.ebay.com/ws/api.dll"

# eBay Finding API endpoint (UK)
FINDING_API_URL = "https://svcs.ebay.co.uk/services/search/FindingService/v1"

# eBay UK site ID
SITE_ID = "3"

# Compatibility level
COMPAT_LEVEL = "1155"

# Condition ID mapping
CONDITION_MAP = {
    'new': '1000',
    'like_new': '1500',
    'used': '3000',
    'damaged': '7000',
}

# Shipping service mapping.
# Each entry: key -> dict with label, ebay_service, default_cost (GBP),
# max_weight_kg (None = unlimited), max_dims_cm (None = unlimited, else tuple
# of 3 sides in cm — product must fit in any orientation), group (see
# SHIPPING_GROUPS), notes.
SHIPPING_SERVICE_MAP = {
    # --- Royal Mail (domestic) ---
    'royal_mail_2nd': {
        'label': 'Royal Mail 2nd Class', 'ebay_service': 'UK_RoyalMailSecondClassStandard',
        'default_cost': 2.99, 'max_weight_kg': 2.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_1st': {
        'label': 'Royal Mail 1st Class', 'ebay_service': 'UK_RoyalMailFirstClassStandard',
        'default_cost': 3.99, 'max_weight_kg': 2.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_signed_2nd': {
        'label': 'Royal Mail Signed For 2nd Class', 'ebay_service': 'UK_RoyalMailSecondClassRecorded',
        'default_cost': 4.19, 'max_weight_kg': 2.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_signed_1st': {
        'label': 'Royal Mail Signed For 1st Class', 'ebay_service': 'UK_RoyalMailFirstClassRecordedRecordedDelivery',
        'default_cost': 5.19, 'max_weight_kg': 2.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_tracked_48': {
        'label': 'Royal Mail Tracked 48', 'ebay_service': 'UK_RoyalMailTracked48',
        'default_cost': 4.49, 'max_weight_kg': 20.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_tracked_24': {
        'label': 'Royal Mail Tracked 24', 'ebay_service': 'UK_RoyalMailTracked24',
        'default_cost': 5.49, 'max_weight_kg': 20.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    # Legacy key — kept for backwards compat. Remapped from intl airmail -> Tracked 48.
    'royal_mail_tracked': {
        'label': 'Royal Mail Tracked (legacy)', 'ebay_service': 'UK_RoyalMailTracked48',
        'default_cost': 4.49, 'max_weight_kg': 20.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_special': {
        'label': 'Royal Mail Special Delivery (next day 1pm)', 'ebay_service': 'UK_RoyalMailSpecialDeliveryNextDay',
        'default_cost': 8.99, 'max_weight_kg': 20.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },
    'royal_mail_special_9am': {
        'label': 'Royal Mail Special Delivery 9am', 'ebay_service': 'UK_RoyalMailSpecialDelivery9am',
        'default_cost': 15.99, 'max_weight_kg': 20.0, 'max_dims_cm': (61, 46, 46),
        'group': 'rm_domestic', 'notes': '',
    },

    # --- Royal Mail (international) ---
    'royal_mail_intl': {
        'label': 'Royal Mail International Standard', 'ebay_service': 'UK_RoyalMailAirmailInternational',
        'default_cost': 6.99, 'max_weight_kg': 2.0, 'max_dims_cm': (60, 60, 90),
        'group': 'rm_intl', 'notes': '',
    },
    'royal_mail_intl_signed': {
        'label': 'Royal Mail International Signed', 'ebay_service': 'UK_RoyalMailInternationalSignedFor',
        'default_cost': 10.99, 'max_weight_kg': 2.0, 'max_dims_cm': (60, 60, 90),
        'group': 'rm_intl', 'notes': '',
    },
    'royal_mail_intl_tracked': {
        'label': 'Royal Mail International Tracked & Signed', 'ebay_service': 'UK_RoyalMailInternationalTrackedAndSigned',
        'default_cost': 12.99, 'max_weight_kg': 2.0, 'max_dims_cm': (60, 60, 90),
        'group': 'rm_intl', 'notes': '',
    },

    # --- Parcelforce (up to 30 kg single parcel) ---
    'parcelforce_48': {
        'label': 'Parcelforce 48', 'ebay_service': 'UK_ParcelForce48',
        'default_cost': 7.99, 'max_weight_kg': 30.0, 'max_dims_cm': None,
        'group': 'parcelforce', 'notes': 'longest side 1.5 m',
    },
    'parcelforce_24': {
        'label': 'Parcelforce 24', 'ebay_service': 'UK_ParcelForce24',
        'default_cost': 10.99, 'max_weight_kg': 30.0, 'max_dims_cm': None,
        'group': 'parcelforce', 'notes': 'longest side 1.5 m',
    },
    'parcelforce_express_10': {
        'label': 'Parcelforce Express 10', 'ebay_service': 'UK_ParcelForceExpress10',
        'default_cost': 15.99, 'max_weight_kg': 30.0, 'max_dims_cm': None,
        'group': 'parcelforce', 'notes': 'longest side 1.5 m',
    },
    'parcelforce_express_9': {
        'label': 'Parcelforce Express 9', 'ebay_service': 'UK_ParcelForceExpress9',
        'default_cost': 19.99, 'max_weight_kg': 30.0, 'max_dims_cm': None,
        'group': 'parcelforce', 'notes': 'longest side 1.5 m',
    },

    # --- Couriers (eBay accepts them under UK_OtherCourier + speed tier) ---
    'hermes': {  # legacy key = Evri Standard
        'label': 'Evri (Standard)', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 3.49, 'max_weight_kg': 15.0, 'max_dims_cm': (120, 45, 45),
        'group': 'courier', 'notes': '',
    },
    'evri_next_day': {
        'label': 'Evri Next Day', 'ebay_service': 'UK_OtherCourier24',
        'default_cost': 5.49, 'max_weight_kg': 15.0, 'max_dims_cm': (120, 45, 45),
        'group': 'courier', 'notes': '',
    },
    'dpd': {
        'label': 'DPD', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 5.99, 'max_weight_kg': 30.0, 'max_dims_cm': (175, 100, 70),
        'group': 'courier', 'notes': '',
    },
    'dpd_next_day': {
        'label': 'DPD Next Day', 'ebay_service': 'UK_OtherCourier24',
        'default_cost': 7.99, 'max_weight_kg': 30.0, 'max_dims_cm': (175, 100, 70),
        'group': 'courier', 'notes': '',
    },
    'yodel': {
        'label': 'Yodel', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 4.99, 'max_weight_kg': 20.0, 'max_dims_cm': (180, 60, 60),
        'group': 'courier', 'notes': '',
    },
    'ups': {
        'label': 'UPS', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 8.99, 'max_weight_kg': 70.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '270 cm girth',
    },
    'ups_next_day': {
        'label': 'UPS Next Day', 'ebay_service': 'UK_OtherCourier24',
        'default_cost': 12.99, 'max_weight_kg': 70.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '270 cm girth',
    },
    'ups_expedited': {
        'label': 'UPS Expedited (heavy intl)', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 14.99, 'max_weight_kg': 70.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '270 cm girth',
    },
    'dhl': {
        'label': 'DHL', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 9.99, 'max_weight_kg': 70.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '',
    },
    'dhl_express': {
        'label': 'DHL Express Worldwide', 'ebay_service': 'UK_OtherCourier24',
        'default_cost': 14.99, 'max_weight_kg': 70.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '',
    },
    'fedex': {
        'label': 'FedEx', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 9.99, 'max_weight_kg': 68.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '',
    },
    'tnt_express': {
        'label': 'TNT Express (now FedEx)', 'ebay_service': 'UK_OtherCourier24',
        'default_cost': 12.99, 'max_weight_kg': 68.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '',
    },
    'inpost': {
        'label': 'InPost UK (lockers)', 'ebay_service': 'UK_OtherCourier48',
        'default_cost': 3.99, 'max_weight_kg': 25.0, 'max_dims_cm': (64, 41, 38),
        'group': 'courier', 'notes': 'locker size C',
    },
    'apc_overnight': {
        'label': 'APC Overnight', 'ebay_service': 'UK_OtherCourier24',
        'default_cost': 8.99, 'max_weight_kg': 30.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '',
    },
    'amazon_shipping': {
        'label': 'Amazon Shipping', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 4.99, 'max_weight_kg': 30.0, 'max_dims_cm': None,
        'group': 'courier', 'notes': '',
    },

    # --- Large / heavy / pallets ---
    'tuffnells': {
        'label': 'Tuffnells (heavy / oversized)', 'ebay_service': 'UK_OtherCourier',
        'default_cost': 14.99, 'max_weight_kg': 75.0, 'max_dims_cm': None,
        'group': 'large', 'notes': 'oversized OK',
    },
    'palletways': {
        'label': 'Palletways (pallet)', 'ebay_service': 'UK_Freight',
        'default_cost': 49.99, 'max_weight_kg': 1000.0, 'max_dims_cm': None,
        'group': 'large', 'notes': 'pallet 100-1000 kg',
    },
    'palletforce': {
        'label': 'Palletforce (pallet)', 'ebay_service': 'UK_Freight',
        'default_cost': 49.99, 'max_weight_kg': 1000.0, 'max_dims_cm': None,
        'group': 'large', 'notes': 'pallet 100-1000 kg',
    },
    'freight_other': {
        'label': 'Other freight / oversized', 'ebay_service': 'UK_Freight',
        'default_cost': 39.99, 'max_weight_kg': 1000.0, 'max_dims_cm': None,
        'group': 'large', 'notes': 'freight',
    },

    # --- Other ---
    'collect': {
        'label': 'Collection Only', 'ebay_service': 'UK_CollectInPerson',
        'default_cost': 0.00, 'max_weight_kg': None, 'max_dims_cm': None,
        'group': 'other', 'notes': 'no delivery — buyer picks up',
    },
    'seller_choice': {
        'label': 'Let eBay choose (seller choice)', 'ebay_service': 'UK_SellerChoice',
        'default_cost': 0.00, 'max_weight_kg': None, 'max_dims_cm': None,
        'group': 'other', 'notes': 'eBay picks based on weight',
    },
}

# Display order for dropdowns (group_key, display_label).
SHIPPING_GROUPS = [
    ('rm_domestic', 'Royal Mail — Domestic'),
    ('rm_intl',     'Royal Mail — International'),
    ('parcelforce', 'Parcelforce (up to 30 kg)'),
    ('courier',     'Couriers (Evri / DPD / Yodel / UPS / DHL / FedEx)'),
    ('large',       'Large / Heavy / Pallets'),
    ('other',       'Other'),
]


def get_shipping_method(key):
    """Get shipping method config by key. Falls back to royal_mail_2nd."""
    return SHIPPING_SERVICE_MAP.get(key) or SHIPPING_SERVICE_MAP['royal_mail_2nd']


def format_shipping_option_label(key):
    """Build dropdown label with weight/size/notes constraints appended."""
    m = SHIPPING_SERVICE_MAP.get(key)
    if not m:
        return key
    parts = []
    if m.get('max_weight_kg'):
        parts.append(f"max {m['max_weight_kg']:g} kg")
    if m.get('max_dims_cm'):
        d = m['max_dims_cm']
        parts.append(f"{d[0]}\u00d7{d[1]}\u00d7{d[2]} cm")
    if m.get('notes'):
        parts.append(m['notes'])
    if parts:
        return f"{m['label']}  \u2014  {', '.join(parts)}"
    return m['label']


def get_shipping_options_grouped():
    """Return [(group_label, [(key, display_label), ...]), ...] for rendering dropdowns."""
    out = []
    for group_key, group_label in SHIPPING_GROUPS:
        items = [(k, format_shipping_option_label(k))
                 for k, m in SHIPPING_SERVICE_MAP.items() if m.get('group') == group_key]
        if items:
            out.append((group_label, items))
    return out


def validate_shipping_fit(shipping_key, weight_kg=None, length_cm=None, width_cm=None, height_cm=None):
    """
    Check if a product fits the shipping method's weight + dimension limits.
    Returns (ok: bool, error_msg: str | None). Missing product data = pass.
    """
    m = SHIPPING_SERVICE_MAP.get(shipping_key)
    if not m:
        return True, None  # unknown key, don't block

    # Weight check
    max_w = m.get('max_weight_kg')
    try:
        w = float(weight_kg) if weight_kg else 0.0
    except (TypeError, ValueError):
        w = 0.0
    if max_w and w and w > max_w:
        return False, (f"{m['label']}: max {max_w:g} kg, product weighs {w:g} kg. "
                       f"Pick a courier for heavier parcels (e.g. Parcelforce / UPS / DHL / pallet).")

    # Dimension check — product must fit in any orientation.
    max_dims = m.get('max_dims_cm')
    try:
        dims = [float(length_cm or 0), float(width_cm or 0), float(height_cm or 0)]
    except (TypeError, ValueError):
        dims = [0.0, 0.0, 0.0]
    if max_dims and all(d > 0 for d in dims):
        prod_sorted = sorted(dims, reverse=True)
        max_sorted = sorted(max_dims, reverse=True)
        if any(p > mx for p, mx in zip(prod_sorted, max_sorted)):
            return False, (f"{m['label']}: max {max_dims[0]}\u00d7{max_dims[1]}\u00d7{max_dims[2]} cm, "
                           f"product is {int(dims[0])}\u00d7{int(dims[1])}\u00d7{int(dims[2])} cm. "
                           f"Pick a larger courier.")

    return True, None


class EbayAPI:
    """eBay Trading API client using Auth'n'Auth token."""

    def __init__(self, app_id=None, cert_id=None, dev_id=None, user_token=None):
        self.app_id = app_id
        self.cert_id = cert_id
        self.dev_id = dev_id
        self.user_token = user_token

    def is_configured(self):
        """Check if API credentials are set."""
        return bool(self.app_id and self.cert_id and self.dev_id and self.user_token)

    def _get_headers(self, call_name):
        """Build Trading API request headers."""
        return {
            'X-EBAY-API-SITEID': SITE_ID,
            'X-EBAY-API-COMPATIBILITY-LEVEL': COMPAT_LEVEL,
            'X-EBAY-API-CALL-NAME': call_name,
            'X-EBAY-API-APP-NAME': self.app_id,
            'X-EBAY-API-DEV-NAME': self.dev_id,
            'X-EBAY-API-CERT-NAME': self.cert_id,
            'Content-Type': 'text/xml; charset=utf-8',
        }

    def _make_trading_call(self, call_name, xml_body):
        """
        Execute a Trading API call.
        Returns: (success: bool, response_tree: ET.Element or None, error: str or None)
        """
        headers = self._get_headers(call_name)

        try:
            resp = requests.post(
                TRADING_API_URL,
                headers=headers,
                data=xml_body.encode('utf-8'),
                timeout=30
            )
            resp.raise_for_status()
        except requests.exceptions.Timeout:
            print(f"[eBay API] {call_name} timed out")
            return False, None, "Request timed out"
        except requests.exceptions.RequestException as e:
            print(f"[eBay API] {call_name} request error: {e}")
            return False, None, str(e)

        try:
            # eBay XML uses a namespace, strip it for easier parsing
            xml_text = resp.text
            # Remove namespace for simpler element access
            xml_text = xml_text.replace('xmlns="urn:ebay:apis:eBLBaseComponents"', '')
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"[eBay API] {call_name} XML parse error: {e}")
            print(f"[eBay API] Response body: {resp.text[:500]}")
            return False, None, f"XML parse error: {e}"

        # Check Ack status
        ack = root.findtext('Ack', '')
        if ack in ('Success', 'Warning'):
            if ack == 'Warning':
                warnings = root.findall('.//Errors')
                for w in warnings:
                    msg = w.findtext('LongMessage', '')
                    print(f"[eBay API] {call_name} warning: {msg}")
            return True, root, None
        else:
            # Extract error details
            errors = root.findall('.//Errors')
            error_messages = []
            for err in errors:
                severity = err.findtext('SeverityCode', '')
                code = err.findtext('ErrorCode', '')
                msg = err.findtext('LongMessage', '') or err.findtext('ShortMessage', '')
                error_messages.append(f"[{severity} {code}] {msg}")
                print(f"[eBay API] {call_name} error: [{severity} {code}] {msg}")

            error_str = '; '.join(error_messages) if error_messages else 'Unknown API error'
            return False, root, error_str

    def _escape_xml(self, text):
        """Escape special XML characters in text content."""
        if text is None:
            return ''
        text = str(text)
        text = text.replace('&', '&amp;')
        text = text.replace('<', '&lt;')
        text = text.replace('>', '&gt;')
        text = text.replace('"', '&quot;')
        text = text.replace("'", '&apos;')
        return text

    def _escape_cdata(self, html):
        """Wrap HTML content in CDATA for XML transport."""
        if html is None:
            return '<![CDATA[]]>'
        return f'<![CDATA[{html}]]>'

    def create_listing(self, product_data):
        """
        Create an eBay listing via AddItem Trading API call.

        Args:
            product_data: dict with keys:
                - title: str (max 80 chars)
                - description: str (HTML)
                - price: float (GBP)
                - condition: str (new, like_new, used, damaged)
                - quantity: int
                - category_id: str (eBay category ID, default '175673')
                - image_urls: list of str
                - ean: str (optional)
                - dispatch_days: int (default 3)
                - shipping_service: str (config key, default 'royal_mail_2nd')
                - shipping_cost: float (override, optional)
                - return_days: int (default 30)
                - item_specifics: dict (optional, key-value pairs for eBay ItemSpecifics)

        Returns:
            dict with success, ebay_item_id, listing_url, fees, error
        """
        title = self._escape_xml(product_data.get('title', 'Item'))[:80]
        description = product_data.get('description', '')
        price = product_data.get('price', 0.0)
        condition = product_data.get('condition', 'used')
        quantity = product_data.get('quantity', 1)
        category_id = product_data.get('category_id', '175673')  # Other > General
        image_urls = product_data.get('image_urls', [])
        ean = product_data.get('ean', '')
        dispatch_days = product_data.get('dispatch_days', 3)
        shipping_key = product_data.get('shipping_service', 'royal_mail_2nd')
        return_days = product_data.get('return_days', 30)

        condition_id = CONDITION_MAP.get(condition, '3000')

        # Shipping
        method = get_shipping_method(shipping_key)
        shipping_service = method['ebay_service']
        default_cost = method['default_cost']
        shipping_cost = product_data.get('shipping_cost', default_cost)

        # Build PictureURL elements
        picture_xml = ''
        for url in image_urls[:12]:  # eBay max 12 pictures
            if url:
                picture_xml += f'<PictureURL>{self._escape_xml(url)}</PictureURL>\n'

        # Build ProductListingDetails if EAN provided
        product_listing_details = ''
        if ean and ean.strip():
            product_listing_details = f"""
            <ProductListingDetails>
                <EAN>{self._escape_xml(ean)}</EAN>
            </ProductListingDetails>"""

        # Build ItemSpecifics XML from dict
        item_specifics = product_data.get('item_specifics', {})
        if not isinstance(item_specifics, dict):
            item_specifics = {}
        # Add required defaults if missing
        if 'Type' not in item_specifics and 'type' not in item_specifics:
            item_specifics['Type'] = 'Charger'
        if 'Brand' not in item_specifics and 'brand' not in item_specifics:
            # Try to extract brand from title
            _title_words = title.split()
            if _title_words:
                item_specifics['Brand'] = _title_words[0]

        item_specifics_xml = ''
        if item_specifics:
            nvl_parts = []
            for spec_name, spec_value in item_specifics.items():
                if spec_name and spec_value:
                    nvl_parts.append(
                        f'<NameValueList>'
                        f'<Name>{self._escape_xml(str(spec_name)[:65])}</Name>'
                        f'<Value>{self._escape_xml(str(spec_value)[:65])}</Value>'
                        f'</NameValueList>'
                    )
            if nvl_parts:
                item_specifics_xml = '<ItemSpecifics>\n' + '\n'.join(nvl_parts) + '\n</ItemSpecifics>'

        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<AddItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{self._escape_xml(self.user_token)}</eBayAuthToken>
    </RequesterCredentials>
    <ErrorLanguage>en_GB</ErrorLanguage>
    <WarningLevel>High</WarningLevel>
    <Item>
        <Title>{title}</Title>
        <Description>{self._escape_cdata(description)}</Description>
        <PrimaryCategory>
            <CategoryID>{self._escape_xml(category_id)}</CategoryID>
        </PrimaryCategory>
        <StartPrice currencyID="GBP">{price:.2f}</StartPrice>
        <ConditionID>{condition_id}</ConditionID>
        <CategoryMappingAllowed>true</CategoryMappingAllowed>
        <Country>GB</Country>
        <Location>United Kingdom</Location>
        <Currency>GBP</Currency>
        <DispatchTimeMax>{dispatch_days}</DispatchTimeMax>
        <ListingDuration>GTC</ListingDuration>
        <ListingType>FixedPriceItem</ListingType>
        <Quantity>{quantity}</Quantity>
        <PictureDetails>
            {picture_xml}
        </PictureDetails>
        {product_listing_details}
        {item_specifics_xml}
        <ReturnPolicy>
            <ReturnsAcceptedOption>ReturnsAccepted</ReturnsAcceptedOption>
            <ReturnsWithinOption>Days_30</ReturnsWithinOption>
        </ReturnPolicy>
        <ShippingDetails>
            <ShippingType>Flat</ShippingType>
            <ShippingServiceOptions>
                <ShippingServicePriority>1</ShippingServicePriority>
                <ShippingService>{shipping_service}</ShippingService>
                <ShippingServiceCost currencyID="GBP">{shipping_cost:.2f}</ShippingServiceCost>
                <ShippingServiceAdditionalCost currencyID="GBP">{shipping_cost:.2f}</ShippingServiceAdditionalCost>
                {'<FreeShipping>true</FreeShipping>' if shipping_cost == 0 else ''}
            </ShippingServiceOptions>
        </ShippingDetails>
        <Site>UK</Site>
    </Item>
</AddItemRequest>"""

        print(f"[eBay API] AddItem: '{title}' at GBP {price:.2f}")
        success, root, error = self._make_trading_call('AddItem', xml_body)

        if success and root is not None:
            item_id = root.findtext('.//ItemID', '')
            # Calculate total fees
            total_fees = 0.0
            fees = root.findall('.//Fee')
            for fee in fees:
                fee_name = fee.findtext('Name', '')
                fee_amount = fee.findtext('Fee', '0')
                try:
                    fee_val = float(fee_amount)
                    if fee_val > 0:
                        total_fees += fee_val
                        print(f"[eBay API]   Fee: {fee_name} = GBP {fee_val:.2f}")
                except (ValueError, TypeError):
                    pass

            listing_url = f"https://www.ebay.co.uk/itm/{item_id}" if item_id else ''
            print(f"[eBay API] AddItem success: ItemID={item_id}, Fees=GBP {total_fees:.2f}")

            return {
                'success': True,
                'ebay_item_id': item_id,
                'listing_url': listing_url,
                'fees': total_fees,
                'error': None,
            }
        else:
            return {
                'success': False,
                'ebay_item_id': None,
                'listing_url': None,
                'fees': 0.0,
                'error': error or 'Unknown error',
            }

    def end_listing(self, ebay_item_id):
        """
        End an active eBay listing via EndItem Trading API call.

        Args:
            ebay_item_id: str - the eBay item number

        Returns:
            dict with success, error
        """
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<EndItemRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{self._escape_xml(self.user_token)}</eBayAuthToken>
    </RequesterCredentials>
    <ErrorLanguage>en_GB</ErrorLanguage>
    <ItemID>{self._escape_xml(ebay_item_id)}</ItemID>
    <EndingReason>NotAvailable</EndingReason>
</EndItemRequest>"""

        print(f"[eBay API] EndItem: {ebay_item_id}")
        success, root, error = self._make_trading_call('EndItem', xml_body)

        if success:
            print(f"[eBay API] EndItem success: {ebay_item_id}")
            return {'success': True, 'error': None}
        else:
            return {'success': False, 'error': error or 'Failed to end listing'}

    def get_orders(self, days=30):
        """
        Fetch recent completed orders via GetOrders Trading API call.

        Args:
            days: int - how many days back to fetch

        Returns:
            list of order dicts with: order_id, buyer, total, status,
            created_time, items (list of dicts with item_id, title, quantity, price)
        """
        date_from = (datetime.utcnow() - timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%S.000Z')
        date_to = datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetOrdersRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{self._escape_xml(self.user_token)}</eBayAuthToken>
    </RequesterCredentials>
    <ErrorLanguage>en_GB</ErrorLanguage>
    <CreateTimeFrom>{date_from}</CreateTimeFrom>
    <CreateTimeTo>{date_to}</CreateTimeTo>
    <OrderRole>Seller</OrderRole>
    <OrderStatus>Completed</OrderStatus>
    <Pagination>
        <EntriesPerPage>100</EntriesPerPage>
        <PageNumber>1</PageNumber>
    </Pagination>
</GetOrdersRequest>"""

        print(f"[eBay API] GetOrders: last {days} days")
        success, root, error = self._make_trading_call('GetOrders', xml_body)

        orders = []
        if success and root is not None:
            order_elems = root.findall('.//Order')
            for order_el in order_elems:
                order_id = order_el.findtext('OrderID', '')
                buyer_id = order_el.findtext('.//BuyerUserID', '')
                total = order_el.findtext('.//Total', '0')
                status = order_el.findtext('OrderStatus', '')
                created = order_el.findtext('CreatedTime', '')

                # Shipping address
                addr = order_el.find('.//ShippingAddress')
                shipping_address = ''
                if addr is not None:
                    parts = [
                        addr.findtext('Name', ''),
                        addr.findtext('Street1', ''),
                        addr.findtext('Street2', ''),
                        addr.findtext('CityName', ''),
                        addr.findtext('StateOrProvince', ''),
                        addr.findtext('PostalCode', ''),
                        addr.findtext('CountryName', ''),
                    ]
                    shipping_address = ', '.join(p for p in parts if p)

                # Items in order
                items = []
                for txn in order_el.findall('.//Transaction'):
                    item = txn.find('Item')
                    item_id = item.findtext('ItemID', '') if item is not None else ''
                    item_title = item.findtext('Title', '') if item is not None else ''
                    qty = txn.findtext('QuantityPurchased', '1')
                    txn_price = txn.findtext('.//TransactionPrice', '0')
                    items.append({
                        'item_id': item_id,
                        'title': item_title,
                        'quantity': int(qty) if qty.isdigit() else 1,
                        'price': float(txn_price) if txn_price else 0.0,
                    })

                try:
                    total_float = float(total)
                except (ValueError, TypeError):
                    total_float = 0.0

                orders.append({
                    'order_id': order_id,
                    'buyer': buyer_id,
                    'total': total_float,
                    'status': status,
                    'created_time': created,
                    'shipping_address': shipping_address,
                    'items': items,
                })

            print(f"[eBay API] GetOrders: {len(orders)} orders found")
        else:
            print(f"[eBay API] GetOrders failed: {error}")

        return orders

    def mark_shipped(self, order_id, tracking_number, carrier='Royal Mail'):
        """
        Mark an order as shipped via CompleteSale Trading API call.

        Args:
            order_id: str - eBay order ID (or ItemID-TransactionID)
            tracking_number: str - tracking code
            carrier: str - carrier name (default Royal Mail)

        Returns:
            dict with success, error
        """
        # CompleteSale uses OrderID for combined orders,
        # or ItemID + TransactionID for single transactions
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<CompleteSaleRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{self._escape_xml(self.user_token)}</eBayAuthToken>
    </RequesterCredentials>
    <ErrorLanguage>en_GB</ErrorLanguage>
    <OrderID>{self._escape_xml(order_id)}</OrderID>
    <Shipped>true</Shipped>
    <Shipment>
        <ShipmentTrackingDetails>
            <ShipmentTrackingNumber>{self._escape_xml(tracking_number)}</ShipmentTrackingNumber>
            <ShippingCarrierUsed>{self._escape_xml(carrier)}</ShippingCarrierUsed>
        </ShipmentTrackingDetails>
    </Shipment>
</CompleteSaleRequest>"""

        print(f"[eBay API] CompleteSale: order={order_id}, tracking={tracking_number}, carrier={carrier}")
        success, root, error = self._make_trading_call('CompleteSale', xml_body)

        if success:
            print(f"[eBay API] CompleteSale success: {order_id}")
            return {'success': True, 'error': None}
        else:
            return {'success': False, 'error': error or 'Failed to mark as shipped'}

    def search_sold_prices(self, keywords, days=90):
        """
        Search completed/sold items via eBay Finding API (REST).
        Useful for price research.

        Args:
            keywords: str - search terms
            days: int - lookback period (max 90 for Finding API)

        Returns:
            list of dicts with: title, price, currency, sold_date, item_url, condition
        """
        params = {
            'OPERATION-NAME': 'findCompletedItems',
            'SERVICE-VERSION': '1.13.0',
            'SECURITY-APPNAME': self.app_id,
            'RESPONSE-DATA-FORMAT': 'XML',
            'REST-PAYLOAD': '',
            'keywords': keywords,
            'itemFilter(0).name': 'SoldItemsOnly',
            'itemFilter(0).value': 'true',
            'itemFilter(1).name': 'ListedIn',
            'itemFilter(1).value': 'EBAY-GB',
            'sortOrder': 'EndTimeSoonest',
            'paginationInput.entriesPerPage': '50',
        }

        print(f"[eBay API] findCompletedItems: '{keywords}'")

        try:
            resp = requests.get(FINDING_API_URL, params=params, timeout=15)
            resp.raise_for_status()
        except requests.exceptions.RequestException as e:
            print(f"[eBay API] findCompletedItems request error: {e}")
            return []

        try:
            # Strip namespace for easier parsing
            xml_text = resp.text
            xml_text = xml_text.replace(
                'xmlns="http://www.ebay.com/marketplace/search/v1/services"', ''
            )
            root = ET.fromstring(xml_text)
        except ET.ParseError as e:
            print(f"[eBay API] findCompletedItems XML parse error: {e}")
            return []

        ack = root.findtext('ack', '')
        if ack != 'Success':
            error_msg = root.findtext('.//errorMessage/error/message', 'Unknown error')
            print(f"[eBay API] findCompletedItems failed: {error_msg}")
            return []

        results = []
        items = root.findall('.//item')
        for item in items:
            title = item.findtext('title', '')
            price_elem = item.find('.//sellingStatus/currentPrice')
            price = 0.0
            currency = 'GBP'
            if price_elem is not None:
                try:
                    price = float(price_elem.text)
                except (ValueError, TypeError):
                    pass
                currency = price_elem.get('currencyId', 'GBP')

            end_time = item.findtext('.//listingInfo/endTime', '')
            item_url = item.findtext('viewItemURL', '')
            condition_name = item.findtext('.//condition/conditionDisplayName', '')

            results.append({
                'title': title,
                'price': price,
                'currency': currency,
                'sold_date': end_time,
                'item_url': item_url,
                'condition': condition_name,
            })

        print(f"[eBay API] findCompletedItems: {len(results)} sold items found")
        return results


    def get_suggested_categories(self, query):
        """
        Get suggested eBay categories for a product name.
        Uses GetSuggestedCategories Trading API.

        Args:
            query: str - product name/keywords

        Returns:
            list of dicts: [{category_id, category_name}]
        """
        xml_body = f"""<?xml version="1.0" encoding="utf-8"?>
<GetSuggestedCategoriesRequest xmlns="urn:ebay:apis:eBLBaseComponents">
    <RequesterCredentials>
        <eBayAuthToken>{self._escape_xml(self.user_token)}</eBayAuthToken>
    </RequesterCredentials>
    <ErrorLanguage>en_GB</ErrorLanguage>
    <Query>{self._escape_xml(query[:350])}</Query>
</GetSuggestedCategoriesRequest>"""

        success, root, error = self._make_trading_call('GetSuggestedCategories', xml_body)

        categories = []
        if success and root is not None:
            for cat in root.findall('.//SuggestedCategory'):
                cat_elem = cat.find('Category')
                if cat_elem is not None:
                    cat_id = cat_elem.findtext('CategoryID', '')
                    cat_name = cat_elem.findtext('CategoryName', '')
                    # Build full path from parent categories
                    parent = cat_elem.findtext('CategoryParentID', '')
                    pct = int(cat.findtext('PercentItemFound', '0') or '0')
                    categories.append({
                        'category_id': cat_id,
                        'category_name': cat_name,
                        'percent': pct,
                    })
            categories.sort(key=lambda x: -x['percent'])
            print(f"[eBay API] GetSuggestedCategories: {len(categories)} found for '{query[:40]}'")
        else:
            print(f"[eBay API] GetSuggestedCategories failed: {error}")

        return categories[:5]  # Top 5


def get_ebay_client(config_getter):
    """
    Create an EbayAPI instance using stored config values.
    Args: config_getter - function(key, default) to read config
    Returns: EbayAPI instance
    """
    return EbayAPI(
        app_id=config_getter('ebay_app_id', ''),
        cert_id=config_getter('ebay_cert_id', ''),
        dev_id=config_getter('ebay_dev_id', ''),
        user_token=config_getter('ebay_user_token', '')
    )
