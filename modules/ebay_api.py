"""
eBay Hub UK - eBay API Module (Placeholder)

TODO: Implement real eBay API integration using:
- eBay Browse API (for searching items)
- eBay Inventory API (for creating/managing listings)
- eBay Fulfillment API (for order management)
- eBay Account API (for settings)

eBay Developer Portal: https://developer.ebay.com/
OAuth2 flow required for production.
"""


class EbayAPI:
    """Placeholder eBay API client."""

    def __init__(self, app_id=None, cert_id=None, dev_id=None, user_token=None):
        self.app_id = app_id
        self.cert_id = cert_id
        self.dev_id = dev_id
        self.user_token = user_token
        self.sandbox = True  # Always sandbox until ready for production

    def is_configured(self):
        """Check if API credentials are set."""
        return bool(self.app_id and self.cert_id and self.dev_id)

    def get_auth_url(self):
        """
        TODO: Generate eBay OAuth2 consent URL.
        The user needs to authorize the app to manage their eBay account.
        Returns: authorization URL string
        """
        # TODO: Implement OAuth2 flow
        # https://developer.ebay.com/api-docs/static/oauth-authorization-code-grant.html
        return None

    def exchange_code(self, auth_code):
        """
        TODO: Exchange authorization code for access/refresh tokens.
        Args: auth_code - the code from eBay redirect
        Returns: dict with access_token, refresh_token, expires_in
        """
        # TODO: POST to https://api.ebay.com/identity/v1/oauth2/token
        return None

    def refresh_token(self):
        """
        TODO: Refresh the access token using stored refresh token.
        Returns: new access_token
        """
        # TODO: Implement token refresh
        return None

    def create_listing(self, product_data):
        """
        TODO: Create an eBay listing via Inventory API.

        Args:
            product_data: dict with keys:
                - title: str
                - description: str (HTML)
                - price: float (GBP)
                - condition: str (NEW, LIKE_NEW, USED_EXCELLENT, etc.)
                - quantity: int
                - category_id: str (eBay category)
                - image_urls: list of str
                - ean: str (optional)

        Returns:
            dict with ebay_item_id, listing_url or None on failure

        Steps:
            1. Create/update inventory item (PUT /sell/inventory/v1/inventory_item/{sku})
            2. Create offer (POST /sell/inventory/v1/offer)
            3. Publish offer (POST /sell/inventory/v1/offer/{offerId}/publish)
        """
        # TODO: Implement real eBay listing creation
        return {
            'success': False,
            'error': 'eBay API not yet configured. Set up credentials in Settings.',
            'ebay_item_id': None
        }

    def end_listing(self, ebay_item_id):
        """
        TODO: End an active eBay listing.
        Args: ebay_item_id - the eBay item number
        Returns: bool success
        """
        # TODO: Implement via Trading API or Inventory API
        return False

    def get_listing_status(self, ebay_item_id):
        """
        TODO: Get current status of an eBay listing.
        Args: ebay_item_id
        Returns: dict with status, views, watchers, current_price
        """
        # TODO: Implement via Browse API or Trading API
        return None

    def get_orders(self, days=30):
        """
        TODO: Fetch recent orders from eBay.
        Args: days - how many days back to fetch
        Returns: list of order dicts

        Use: GET /sell/fulfillment/v1/order
        """
        # TODO: Implement order fetching
        return []

    def mark_shipped(self, order_id, tracking_number, carrier='Royal Mail'):
        """
        TODO: Mark an order as shipped on eBay.
        Args:
            order_id: eBay order ID
            tracking_number: tracking code
            carrier: shipping carrier name
        Returns: bool success

        Use: POST /sell/fulfillment/v1/order/{orderId}/shipping_fulfillment
        """
        # TODO: Implement shipping fulfillment
        return False

    def search_completed(self, keywords, days=90):
        """
        TODO: Search completed listings to estimate selling price.
        Useful for pricing products from pallets.
        Args:
            keywords: search string
            days: lookback period
        Returns: list of dicts with title, price, sold_date
        """
        # TODO: Implement via Finding API
        return []


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
