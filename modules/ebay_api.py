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

# Shipping service mapping (config key -> eBay ShippingService name)
SHIPPING_SERVICE_MAP = {
    'royal_mail_2nd': ('UK_RoyalMailSecondClassStandard', 2.99),
    'royal_mail_1st': ('UK_RoyalMailFirstClassStandard', 3.99),
    'royal_mail_tracked': ('UK_RoyalMailTracked', 4.49),
    'hermes': ('UK_Hermes', 3.49),
    'dpd': ('UK_DPDNextDay', 5.99),
    'yodel': ('UK_YodelDirect', 4.99),
    'collect': ('UK_CollectInPerson', 0.00),
}


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
        shipping_service, default_cost = SHIPPING_SERVICE_MAP.get(
            shipping_key, ('UK_RoyalMailSecondClassStandard', 2.99)
        )
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
