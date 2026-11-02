# DukaanPro

Billing and stock software for small Indian shops, built with Django.

One app serves five kinds of shop. Each shop type gets only the features it needs:

| Shop type | Extra features |
|---|---|
| General / Kirana store | Loose quantities (2.5 kg), buy in boxes and sell in pieces |
| Stationery | Buy in boxes and sell in pieces |
| Cosmetics / Gifts / Mobile accessories | Standard billing |
| Pharmacy | Batches, expiry dates, FEFO selling, Schedule H1 register, drug licence |
| Hardware | Loose quantities, retail and wholesale prices, quotations, specifications |

Every shop gets:
- GST invoices with the CGST + SGST / IGST split
- Purchases, suppliers and supplier dues
- Customer dues (udhari), sale returns (credit notes) and purchase returns (debit notes)
- Low stock alerts and a dashboard
- English, Hindi and Marathi

The admin sees every shop and can switch a whole shop type on or off from the **Shop types** page.

## Run it on your computer

```bash
python -m venv venv
venv\Scripts\activate            # Windows  (Linux/macOS: source venv/bin/activate)
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000 and sign in.

To add demo logins for every shop type, with realistic sample data (shops that already have products are skipped):

```bash
python manage.py load_sample_data
```

## Tests

```bash
python manage.py test pharma_app
```

## Translations

Texts are in `pharma_app/locale/<language>/LC_MESSAGES/*.po`. After editing them run:

```bash
python manage.py build_translations            # rebuild the .mo files
python manage.py build_translations --update   # also pick up new texts from the code
```

## Settings for a real server

Set these environment variables:

- `DJANGO_SECRET_KEY`: a long random value
- `DJANGO_DEBUG=0`

Also add your domain to `ALLOWED_HOSTS` in `pharmacy/settings.py`, then run `python manage.py collectstatic`.

## Project layout

```
pharmacy/            Django project settings and URLs
pharma_app/
    shop_types.py    which features each shop type has (the one place to change this)
    shop_services.py switching shop types on / off
    models.py        shops, products, batches, purchases, sales, returns, accounts
    *_views.py       pages
    templates/       HTML pages
    static/          CSS and JavaScript
    locale/          Hindi and Marathi translations
    management/      commands: build_translations, load_sample_data, seed_demo_shops
    tests.py         automated tests
```
