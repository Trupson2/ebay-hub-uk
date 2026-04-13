# eBay Hub UK — User Guide

## How to access the app

1. Open your browser (Chrome, Safari, Firefox)
2. Enter the link you received (ngrok URL)
3. Enter your PIN and click **Unlock**

## Adding a new pallet (joblot)

1. Click **Pallets** in the top menu
2. Click **+ Add Pallet** (blue button)
3. Fill in:
   - **Pallet Name** — e.g. "Amazon Returns #5"
   - **Supplier** — e.g. "Jobalots"
   - **Purchase Price** — how much you paid in GBP
   - **Purchase Date** — when you bought it
   - **Import Specification** — select your CSV or XLSX file from the supplier
4. Click **+ Add Pallet**
5. Wait — the app imports products and fetches images from Amazon UK

## Setting prices

1. Open the pallet (click on it)
2. Find the **Set Prices** section — list of products with price fields
3. Two ways to set prices:
   - **Manual** — type the price next to each product
   - **Multiplier** — enter e.g. 2.5 in the "Multiplier" field → click **Apply Multiplier** → the app calculates: pallet cost / number of products × 2.5 = suggested price
4. Click **Save All Prices**

## Listing on eBay

**IMPORTANT: Set prices BEFORE listing! eBay has no drafts — listings go live immediately.**

### List entire pallet at once:
1. Open the pallet
2. Click **List All on eBay** (green button)
3. Wait — the app lists each product one by one
4. You'll see a message showing how many were listed

### List a single product:
1. Click on the product
2. Set title, description, price
3. Click **List on eBay**

## Orders

1. Click **Orders** in the top menu
2. New orders show status **TO SHIP**
3. Pack the item and post it
4. Click **Mark as Shipped** next to the order
5. Enter the tracking number

## Dashboard

The home page shows:
- Today / this week / this month sales in GBP
- Active listings
- Orders to ship
- Frozen capital (money tied up in unsold stock)
- Revenue chart

## Settings

Go to **Settings** to:
- Change your access PIN
- Change default shipping method (Royal Mail, Evri, DPD)
- Change return policy days (default 30)
- View and restore backups

## Backups

- The app backs up automatically every hour
- In **Settings** scroll down to see the backup list
- **Create Backup Now** — make a manual backup
- **Restore** — go back to a previous backup
- **Download** — save a backup file to your computer

## Install on your phone (PWA)

1. Open the app in your phone's browser
2. **Android**: tap the 3 dots menu → "Add to Home Screen"
3. **iPhone**: tap the share icon → "Add to Home Screen"
4. The app will appear on your phone like a normal app

## Troubleshooting

**I can't access the website:**
- Check your internet connection
- The link may have changed (ngrok URL changes when Pi restarts)
- Contact Adrian

**I forgot my PIN:**
- Contact Adrian — he can reset it

**Products have no images:**
- Open the pallet → click **Scrape Images**
- Wait about 30 seconds per product

**Listing on eBay doesn't work:**
- Check that eBay API keys are set in Settings
- Make sure the product has a price above £0
- Make sure the product has a title

## Quick reference

| What you want to do | Where to go |
|---------------------|-------------|
| See today's sales | Dashboard |
| Add new joblot | Pallets → + Add Pallet |
| Import supplier file | Pallets → open pallet → Import CSV |
| Set prices | Pallets → open pallet → Set Prices |
| List on eBay | Pallets → open pallet → List All on eBay |
| Check what to ship | Orders |
| Change settings | Settings |
| Make a backup | Settings → Create Backup Now |
