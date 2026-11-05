"""
Sample accounts and realistic sample data for every shop type.

    python manage.py load_sample_data --accounts-only   # admin + one login per shop type
    python manage.py load_sample_data                    # accounts (if missing) + data

The data is entered the way a user would enter it: the command logs in
as each shop owner and submits the same forms the screens submit
(products, purchase bills, sales, payments, returns, quotations), so
stock, batches, the customer khata, supplier dues, GST split, invoice
numbers and supplier-product links are all built by the app itself.
Dates are spread over the last ~7 weeks.

Only adds data. A shop that already has products is skipped.
"""

from datetime import timedelta
from decimal import Decimal

from django.contrib.messages import get_messages
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from pharma_app.models import (
    CustomerLedger,
    CustomUser,
    Customer,
    Payment,
    Product,
    Purchase,
    PurchaseReturn,
    Quotation,
    Retailer,
    Sale,
    SaleReturn,
    Supplier,
    Unit,
)
from pharma_app.shop_types import get_features
from pharma_app.views import calculate_sale_totals

D = Decimal
HOST = {"HTTP_HOST": "localhost"}
AJAX = {"HTTP_X_REQUESTED_WITH": "XMLHttpRequest", **HOST}

ADMIN = {"username": "admin", "password": "Dukaan@Admin26", "email": "admin@example.com"}

UNITS = [
    ("Piece", "pc"), ("Box", "box"), ("Kilogram", "kg"), ("Packet", "pkt"), ("Ream", "ream"),
    ("Tablet", "tab"), ("Strip", "strip"), ("Bottle", "btl"), ("Tube", "tube"),
    ("Metre", "m"), ("Coil", "coil"), ("Litre", "ltr"), ("Bag", "bag"), ("Dozen", "dozen"),
]

# ---------------------------------------------------------------- shops
SHOPS = {
    "general": {
        "login": ("sharma_kirana", "Grocery#2026"),
        "shop": {
            "shop_name": "Sharma Kirana Store", "owner_name": "Rakesh Sharma",
            "mobile": "9822011451", "email": "rakesh.sharma@example.com",
            "address": "Shop 4, Gulmohar Complex, Aundh Road", "city": "Pune", "pincode": "411007",
            "gst_number": "27AKXPS4821L1ZQ", "pan_number": "AKXPS4821L",
        },
        "suppliers": [
            ("Pune Wholesale Grains", "Vijay Bhosale", "9850112233", "27AAKFP2231N1ZT", "Market Yard, Gultekdi", "Pune", "Maharashtra", "411037", 15),
            ("Shree Ganesh FMCG Distributors", "Manoj Jain", "9823456710", "27ABJFS7731K1Z2", "Bhavani Peth", "Pune", "Maharashtra", "411042", 30),
            ("Gujarat Edible Oils", "Hitesh Patel", "9898123450", "24AAGFG5521M1ZP", "GIDC Naroda", "Ahmedabad", "Gujarat", "382330", 30),
        ],
        "customers": [
            ("Sunita Deshpande", "9763210045", {}),
            ("Prakash Jadhav", "9890456712", {"credit_limit": "5000"}),
            ("Meena Kulkarni", "9420567831", {}),
            ("Hotel Sai Krupa", "9325671209", {"credit_limit": "20000", "address": "Baner Road, Pune"}),
            ("Anil Pawar", "9561230987", {"opening_balance": "450"}),
            ("Patel Caterers (Surat)", "9824011876", {"state": "gujarat", "address": "Adajan, Surat"}),
        ],
        "products": {
            "rice":  {"name": "India Gate Basmati Rice", "unit": "kg", "cat": "Grains & Rice", "brand": "India Gate", "hsn": "1006", "gst": "5", "pp": "96", "sp": "115", "mrp": "125", "min": "20"},
            "atta":  {"name": "Aashirvaad Whole Wheat Atta 10kg", "unit": "bag", "cat": "Flour", "brand": "Aashirvaad", "hsn": "1101", "gst": "5", "pp": "410", "sp": "455", "mrp": "485", "min": "5"},
            "dal":   {"name": "Tur Dal (Loose)", "unit": "kg", "cat": "Pulses", "brand": "Loose", "hsn": "0713", "gst": "5", "pp": "128", "sp": "150", "mrp": "160", "min": "15"},
            "sugar": {"name": "Sugar (Loose)", "unit": "kg", "cat": "Grains & Rice", "brand": "Loose", "hsn": "1701", "gst": "5", "pp": "40", "sp": "46", "mrp": "48", "min": "25"},
            "oil":   {"name": "Fortune Sunflower Oil 1L", "unit": "pc", "buy_in": ("box", "12"), "cat": "Edible Oil", "brand": "Fortune", "hsn": "1512", "gst": "5", "pp": "138", "sp": "155", "mrp": "165", "min": "12"},
            "tea":   {"name": "Tata Tea Premium 500g", "unit": "pkt", "cat": "Tea & Coffee", "brand": "Tata", "hsn": "0902", "gst": "5", "pp": "245", "sp": "275", "mrp": "290", "min": "10"},
            "soap":  {"name": "Lifebuoy Soap 125g", "unit": "pc", "buy_in": ("box", "24"), "cat": "Personal Care", "brand": "Lifebuoy", "hsn": "3401", "gst": "18", "pp": "28", "sp": "33", "mrp": "36", "min": "24"},
            "maggi": {"name": "Maggi Masala Noodles 70g", "unit": "pc", "buy_in": ("box", "48"), "cat": "Packaged Food", "brand": "Nestle", "hsn": "1902", "gst": "18", "pp": "12", "sp": "14", "mrp": "15", "min": "48"},
            "salt":  {"name": "Tata Salt 1kg", "unit": "pkt", "cat": "Spices & Salt", "brand": "Tata", "hsn": "2501", "gst": "0", "pp": "24", "sp": "27", "mrp": "28", "min": "20"},
            "biscuit": {"name": "Parle-G Biscuits 800g", "unit": "pkt", "cat": "Packaged Food", "brand": "Parle", "hsn": "1905", "gst": "18", "pp": "78", "sp": "88", "mrp": "90", "min": "10"},
        },
        "purchases": [
            (48, 0, "PWG/2026/1184", "net15", [("rice", "kg", "60", "96", "125"), ("dal", "kg", "40", "128", "160"), ("sugar", "kg", "80", "40", "48")], "full"),
            (46, 1, "SGF-7731", "net30", [("atta", "bag", "20", "410", "485"), ("oil", "box", "4", "1656", "1980"), ("tea", "pkt", "24", "245", "290"), ("soap", "box", "3", "672", "864"), ("maggi", "box", "4", "576", "720"), ("salt", "pkt", "40", "24", "28"), ("biscuit", "pkt", "30", "78", "90")], "10000"),
            (20, 2, "GEO/1045", "net30", [("oil", "box", "3", "1620", "1980")], None),
            (12, 0, "PWG/2026/1302", "net15", [("rice", "kg", "40", "98", "125"), ("sugar", "kg", "50", "41", "48")], None),
        ],
        "sales": [
            (35, 0, [("rice", "5", "0"), ("dal", "2", "0"), ("sugar", "3", "0")], "full"),
            (33, 3, [("rice", "15", "50"), ("oil", "12", "60"), ("atta", "4", "0")], "due"),
            (31, 1, [("tea", "2", "0"), ("biscuit", "3", "0"), ("maggi", "12", "0")], "500"),
            (28, 2, [("atta", "1", "0"), ("salt", "2", "0"), ("soap", "4", "0")], "full"),
            (26, 5, [("rice", "20", "100"), ("dal", "10", "0"), ("tea", "4", "0")], "full"),
            (22, 4, [("sugar", "5", "0"), ("dal", "2.5", "0")], "due"),
            (19, 0, [("oil", "2", "0"), ("maggi", "6", "0"), ("biscuit", "2", "0")], "full"),
            (15, 3, [("rice", "10", "0"), ("sugar", "10", "0"), ("salt", "5", "0")], "due"),
            (11, 1, [("atta", "2", "0"), ("dal", "3", "0")], "full"),
            (8, 2, [("tea", "1", "0"), ("soap", "6", "10")], "full"),
            (5, 0, [("rice", "2.5", "0"), ("sugar", "1.5", "0"), ("maggi", "10", "0")], "full"),
            (3, 3, [("oil", "6", "30"), ("atta", "3", "0")], "1500"),
            (1, 4, [("biscuit", "2", "0"), ("salt", "1", "0")], "full"),
            (0, 2, [("rice", "3", "0"), ("tea", "1", "0"), ("soap", "2", "0")], "full"),
            (0, 0, [("maggi", "8", "0"), ("biscuit", "1", "0")], "full"),
        ],
        "receipts": [(10, 3, "6000"), (4, 4, "300")],
        "supplier_payments": [(25, 1, "8000"), (6, 2, "2500")],
        "sale_return": (8, [("soap", "2")], "Two soaps were damaged in the pack", "account"),
        "purchase_return": (18, 2, [("oil", "1")], "One box with leaking pouches"),
        "low_stock": {"tea": "25", "salt": "40"},
    },

    "stationery": {
        "login": ("vidya_stationery", "Notebook#2026"),
        "shop": {
            "shop_name": "Vidya Stationery & Xerox", "owner_name": "Sunil Patil",
            "mobile": "9881034562", "email": "sunil.patil@example.com",
            "address": "Opp. Fergusson College Gate, FC Road", "city": "Pune", "pincode": "411004",
            "gst_number": "27BCSPP7712Q1Z8", "pan_number": "BCSPP7712Q",
        },
        "suppliers": [
            ("Navneet Education Distributors", "Rahul Shah", "9822345671", "27AAACN1234B1Z9", "Sadashiv Peth", "Pune", "Maharashtra", "411030", 30),
            ("Kokuyo Camlin Agency", "Deepak Joshi", "9970123456", "27AACCK5562H1Z1", "Shukrawar Peth", "Pune", "Maharashtra", "411002", 15),
            ("JK Paper Traders", "Sanjay Reddy", "9845098765", "29AAGFJ4471C1ZR", "Chickpet", "Bengaluru", "Karnataka", "560053", 30),
        ],
        "customers": [
            ("Aarav Joshi", "9767123409", {}),
            ("Sanskriti Public School", "9021456783", {"credit_limit": "50000", "address": "Kothrud, Pune"}),
            ("Pooja Shinde", "9604512378", {}),
            ("Deccan Coaching Classes", "9850789123", {"credit_limit": "15000"}),
            ("Rohit Kale", "8888123450", {}),
            ("Belgaum Book Depot", "9448012345", {"state": "karnataka", "address": "Khade Bazar, Belagavi"}),
        ],
        "products": {
            "pen":    {"name": "Reynolds 045 Blue Ball Pen", "unit": "pc", "buy_in": ("box", "10"), "cat": "Pens", "brand": "Reynolds", "hsn": "9608", "gst": "18", "pp": "7", "sp": "10", "mrp": "10", "min": "50"},
            "gel":    {"name": "Cello Gripper Gel Pen", "unit": "pc", "buy_in": ("box", "10"), "cat": "Pens", "brand": "Cello", "hsn": "9608", "gst": "18", "pp": "14", "sp": "20", "mrp": "20", "min": "30"},
            "nb":     {"name": "Classmate Long Notebook 200 Pages", "unit": "pc", "buy_in": ("dozen", "12"), "cat": "Notebooks", "brand": "Classmate", "hsn": "4820", "gst": "5", "pp": "52", "sp": "65", "mrp": "70", "min": "24"},
            "a4":     {"name": "JK Copier A4 Paper 75 GSM", "unit": "ream", "cat": "Paper", "brand": "JK Paper", "hsn": "4802", "gst": "5", "pp": "235", "sp": "280", "mrp": "310", "min": "10"},
            "pencil": {"name": "Apsara Platinum Pencil", "unit": "pc", "buy_in": ("box", "10"), "cat": "Pencils", "brand": "Apsara", "hsn": "9609", "gst": "5", "pp": "4", "sp": "6", "mrp": "6", "min": "50"},
            "geo":    {"name": "Camlin Geometry Box", "unit": "pc", "cat": "School Kits", "brand": "Camlin", "hsn": "9017", "gst": "18", "pp": "118", "sp": "150", "mrp": "165", "min": "10"},
            "fevi":   {"name": "Fevicol MR 100g", "unit": "pc", "cat": "Glue & Tape", "brand": "Pidilite", "hsn": "3506", "gst": "18", "pp": "34", "sp": "42", "mrp": "45", "min": "12"},
            "marker": {"name": "Camlin Whiteboard Marker (Black)", "unit": "pc", "buy_in": ("box", "10"), "cat": "Markers", "brand": "Camlin", "hsn": "9608", "gst": "18", "pp": "22", "sp": "30", "mrp": "32", "min": "20"},
            "file":   {"name": "Solo Plastic File Folder", "unit": "pc", "cat": "Files", "brand": "Solo", "hsn": "3926", "gst": "18", "pp": "18", "sp": "25", "mrp": "28", "min": "20"},
        },
        "purchases": [
            (47, 0, "NED/26/3321", "net30", [("nb", "dozen", "15", "624", "840"), ("pen", "box", "40", "70", "100"), ("gel", "box", "10", "140", "200"), ("pencil", "box", "30", "40", "60")], "6000"),
            (45, 1, "KCA-1127", "net15", [("geo", "pc", "30", "118", "165"), ("marker", "box", "6", "220", "320"), ("fevi", "pc", "36", "34", "45"), ("file", "pc", "60", "18", "28")], "full"),
            (40, 2, "JKP/KA/889", "net30", [("a4", "ream", "40", "235", "310")], None),
            (14, 0, "NED/26/3510", "net30", [("nb", "dozen", "8", "636", "840"), ("pen", "box", "20", "70", "100")], None),
        ],
        "sales": [
            (36, 1, [("nb", "120", "300"), ("pen", "200", "100"), ("pencil", "150", "0"), ("geo", "20", "200")], "due"),
            (34, 0, [("nb", "4", "0"), ("gel", "2", "0"), ("geo", "1", "0")], "full"),
            (30, 3, [("marker", "20", "0"), ("a4", "10", "0"), ("file", "15", "0")], "2000"),
            (27, 2, [("pen", "5", "0"), ("pencil", "6", "0"), ("fevi", "1", "0")], "full"),
            (24, 5, [("a4", "15", "150"), ("file", "20", "0")], "full"),
            (20, 4, [("nb", "6", "0"), ("gel", "4", "0")], "full"),
            (16, 1, [("a4", "5", "0"), ("marker", "10", "0")], "due"),
            (12, 0, [("geo", "1", "0"), ("pencil", "10", "0")], "full"),
            (9, 3, [("nb", "30", "100"), ("pen", "50", "0")], "due"),
            (6, 2, [("fevi", "2", "0"), ("file", "3", "0")], "full"),
            (3, 4, [("gel", "5", "0"), ("marker", "2", "0")], "full"),
            (1, 0, [("nb", "2", "0"), ("pen", "3", "0")], "full"),
            (0, 2, [("a4", "1", "0"), ("pencil", "4", "0")], "full"),
        ],
        "receipts": [(18, 1, "10000"), (5, 3, "4000")],
        "supplier_payments": [(20, 0, "7000"), (8, 2, "5000")],
        "sale_return": (6, [("file", "1")], "Customer bought an extra file by mistake", "cash"),
        "purchase_return": (30, 2, [("a4", "2")], "Two reams arrived torn"),
        "low_stock": {"geo": "15", "fevi": "40"},
    },

    "cosmetics": {
        "login": ("glamour_gifts", "Lipstick#2026"),
        "shop": {
            "shop_name": "Glamour Cosmetics & Gifts", "owner_name": "Neha Kulkarni",
            "mobile": "9922870134", "email": "neha.kulkarni@example.com",
            "address": "G-12, Phoenix Market City, Viman Nagar", "city": "Pune", "pincode": "411014",
            "gst_number": "27DKNPK3390R1Z4", "pan_number": "DKNPK3390R",
        },
        "suppliers": [
            ("Lakme Lever Distributors", "Arjun Mehta", "9819345612", "27AAACL9981F1Z6", "Andheri East", "Mumbai", "Maharashtra", "400069", 30),
            ("Mumbai Gift House", "Farhan Shaikh", "9867012345", "27ABCFM4410D1Z3", "Crawford Market", "Mumbai", "Maharashtra", "400001", 15),
            ("Delhi Mobile Accessories Hub", "Gurpreet Singh", "9810234567", "07AAMFD3321P1ZK", "Gaffar Market, Karol Bagh", "New Delhi", "Delhi", "110005", 30),
        ],
        "customers": [
            ("Priya Nair", "9819023457", {}),
            ("Sneha Gokhale", "9765098123", {}),
            ("Kavya Bhat", "9850011223", {}),
            ("Salon Glow & Go", "9028765432", {"credit_limit": "10000", "address": "Kalyani Nagar, Pune"}),
            ("Riya Chavan", "7020123987", {}),
            ("Goa Beauty Studio", "9822198765", {"state": "goa", "address": "Panaji, Goa"}),
        ],
        "products": {
            "lipstick": {"name": "Lakme 9to5 Matte Lipstick", "unit": "pc", "cat": "Lip Care", "brand": "Lakme", "hsn": "3304", "gst": "18", "pp": "390", "sp": "475", "mrp": "500", "min": "5"},
            "kajal":    {"name": "Maybelline Colossal Kajal", "unit": "pc", "cat": "Eye Makeup", "brand": "Maybelline", "hsn": "3304", "gst": "18", "pp": "165", "sp": "199", "mrp": "210", "min": "10"},
            "cream":    {"name": "Pond's Bright Beauty Cream 50g", "unit": "pc", "cat": "Skin Care", "brand": "Pond's", "hsn": "3304", "gst": "18", "pp": "175", "sp": "215", "mrp": "230", "min": "6"},
            "facewash": {"name": "Himalaya Neem Face Wash 150ml", "unit": "tube", "cat": "Skin Care", "brand": "Himalaya", "hsn": "3401", "gst": "18", "pp": "150", "sp": "185", "mrp": "199", "min": "8"},
            "perfume":  {"name": "Fogg Body Spray 150ml", "unit": "pc", "cat": "Fragrance", "brand": "Fogg", "hsn": "3303", "gst": "18", "pp": "245", "sp": "299", "mrp": "330", "min": "6"},
            "frame":    {"name": "Wooden Photo Frame 8x10", "unit": "pc", "cat": "Gifts", "brand": "Archies", "hsn": "4414", "gst": "5", "pp": "210", "sp": "349", "mrp": "399", "min": "4"},
            "mug":      {"name": "Printed Coffee Mug (Gift Box)", "unit": "pc", "cat": "Gifts", "brand": "Archies", "hsn": "6912", "gst": "5", "pp": "140", "sp": "249", "mrp": "299", "min": "6"},
            "cover":    {"name": "Silicone Back Cover (Redmi Note 13)", "unit": "pc", "cat": "Mobile Accessories", "brand": "Spigen", "hsn": "3926", "gst": "18", "pp": "85", "sp": "199", "mrp": "249", "min": "10"},
            "charger":  {"name": "boAt 20W Type-C Fast Charger", "unit": "pc", "cat": "Mobile Accessories", "brand": "boAt", "hsn": "8504", "gst": "18", "pp": "420", "sp": "599", "mrp": "699", "min": "5"},
        },
        "purchases": [
            (46, 0, "LLD/MUM/2290", "net30", [("lipstick", "pc", "20", "390", "500"), ("kajal", "pc", "30", "165", "210"), ("cream", "pc", "24", "175", "230"), ("facewash", "tube", "24", "150", "199"), ("perfume", "pc", "18", "245", "330")], "8000"),
            (44, 1, "MGH-0567", "net15", [("frame", "pc", "15", "210", "399"), ("mug", "pc", "24", "140", "299")], "full"),
            (42, 2, "DMAH/2026/771", "net30", [("cover", "pc", "40", "85", "249"), ("charger", "pc", "15", "420", "699")], None),
        ],
        "sales": [
            (33, 0, [("lipstick", "2", "0"), ("kajal", "1", "0")], "full"),
            (31, 3, [("cream", "6", "100"), ("facewash", "6", "0"), ("kajal", "4", "0")], "due"),
            (29, 1, [("perfume", "1", "0"), ("mug", "1", "0")], "full"),
            (25, 5, [("lipstick", "5", "150"), ("cream", "4", "0")], "full"),
            (21, 2, [("cover", "1", "0"), ("charger", "1", "50")], "full"),
            (18, 4, [("frame", "2", "0"), ("mug", "2", "0")], "full"),
            (14, 3, [("facewash", "5", "0"), ("perfume", "3", "0")], "1000"),
            (10, 0, [("kajal", "2", "0"), ("cover", "2", "0")], "full"),
            (7, 1, [("charger", "1", "0")], "full"),
            (4, 2, [("lipstick", "1", "0"), ("perfume", "1", "0")], "full"),
            (2, 4, [("mug", "3", "0"), ("frame", "1", "0")], "full"),
            (0, 0, [("cream", "1", "0"), ("kajal", "1", "0")], "full"),
        ],
        "receipts": [(12, 3, "3500")],
        "supplier_payments": [(15, 0, "4000"), (9, 2, "6000")],
        "sale_return": (20, [("charger", "1")], "Charger not working, customer returned", "cash"),
        "purchase_return": (19, 2, [("charger", "1")], "Faulty charger returned to supplier"),
        "low_stock": {"lipstick": "15", "charger": "16"},
    },

    "pharmacy": {
        "login": ("sai_medical", "Medicine#2026"),
        "shop": {
            "shop_name": "Sai Medical & General Stores", "owner_name": "Amit Deshmukh",
            "mobile": "9890567234", "email": "amit.deshmukh@example.com",
            "address": "Near Ruby Hall Clinic, Sassoon Road", "city": "Pune", "pincode": "411001",
            "gst_number": "27AFQPD6672M1ZB", "pan_number": "AFQPD6672M",
            "drug_licence_number": "MH-PZ3-112045", "drug_licence_number_2": "MH-PZ3-112046",
        },
        "suppliers": [
            ("Mahalaxmi Pharma Distributors", "Santosh Gaikwad", "9822567890", "27AAEFM7781G1ZD", "Rasta Peth", "Pune", "Maharashtra", "411011", 30),
            ("Apollo Medical Agencies", "Ramesh Iyer", "9890123678", "27AAKFA2234J1ZS", "Camp", "Pune", "Maharashtra", "411001", 15),
            ("Ahmedabad Pharma Hub", "Kalpesh Shah", "9825067812", "24AAQFA8891R1ZW", "Ashram Road", "Ahmedabad", "Gujarat", "380009", 30),
        ],
        "customers": [
            ("Ramesh Gupta", "9822334455", {}),
            ("Sangeeta More", "9764112233", {}),
            ("Vinod Kamble", "9545667788", {"credit_limit": "3000"}),
            ("Shanti Nursing Home", "9011223344", {"credit_limit": "25000", "address": "Hadapsar, Pune"}),
            ("Lata Shirke", "9403556677", {"opening_balance": "320"}),
            ("Belagavi Care Clinic", "9448778899", {"state": "karnataka", "address": "Tilakwadi, Belagavi"}),
        ],
        "products": {
            "pcm":   {"name": "Dolo 650 Tablet", "unit": "tab", "buy_in": ("strip", "15"), "cat": "Fever & Pain", "brand": "Micro Labs", "hsn": "3004", "gst": "5", "pp": "2.00", "sp": "2.80", "mrp": "3.07", "min": "60", "salt": "Paracetamol 650mg", "mfr": "Micro Labs Ltd", "schedule": "none"},
            "azi":   {"name": "Azithral 500 Tablet", "unit": "tab", "buy_in": ("strip", "5"), "cat": "Antibiotics", "brand": "Alembic", "hsn": "3004", "gst": "5", "pp": "17.00", "sp": "22.50", "mrp": "24.90", "min": "15", "salt": "Azithromycin 500mg", "mfr": "Alembic Pharmaceuticals", "schedule": "H1"},
            "augm":  {"name": "Augmentin 625 Duo Tablet", "unit": "tab", "buy_in": ("strip", "10"), "cat": "Antibiotics", "brand": "GSK", "hsn": "3004", "gst": "5", "pp": "17.50", "sp": "21.50", "mrp": "22.36", "min": "20", "salt": "Amoxicillin 500mg + Clavulanic Acid 125mg", "mfr": "GlaxoSmithKline", "schedule": "H1"},
            "pan":   {"name": "Pan 40 Tablet", "unit": "tab", "buy_in": ("strip", "15"), "cat": "Gastro", "brand": "Alkem", "hsn": "3004", "gst": "5", "pp": "8.00", "sp": "10.50", "mrp": "11.27", "min": "30", "salt": "Pantoprazole 40mg", "mfr": "Alkem Laboratories", "schedule": "H"},
            "cetz":  {"name": "Cetzine 10mg Tablet", "unit": "tab", "buy_in": ("strip", "10"), "cat": "Allergy", "brand": "Dr. Reddy's", "hsn": "3004", "gst": "5", "pp": "1.60", "sp": "2.10", "mrp": "2.25", "min": "30", "salt": "Cetirizine 10mg", "mfr": "Dr. Reddy's Laboratories", "schedule": "none"},
            "benad": {"name": "Benadryl Cough Syrup 100ml", "unit": "btl", "cat": "Cough & Cold", "brand": "Johnson & Johnson", "hsn": "3004", "gst": "5", "pp": "105", "sp": "128", "mrp": "135", "min": "6", "salt": "Diphenhydramine + Ammonium Chloride", "mfr": "Johnson & Johnson", "schedule": "none"},
            "ors":   {"name": "Electral ORS Powder 21.8g", "unit": "pkt", "cat": "Rehydration", "brand": "FDC", "hsn": "3004", "gst": "5", "pp": "18", "sp": "22", "mrp": "23.50", "min": "20", "salt": "Oral Rehydration Salts", "mfr": "FDC Ltd", "schedule": "none"},
            "volini": {"name": "Volini Pain Relief Gel 30g", "unit": "tube", "cat": "Fever & Pain", "brand": "Sun Pharma", "hsn": "3004", "gst": "5", "pp": "120", "sp": "145", "mrp": "155", "min": "5", "salt": "Diclofenac + Methyl Salicylate", "mfr": "Sun Pharmaceutical", "schedule": "none",
                       "opening": ("4", "2026-09")},
        },
        "purchases": [
            (45, 0, "MPD/2026/5521", "net30", [("pcm", "strip", "40", "30", "46.05", "DL6501", "2028-03"), ("pan", "strip", "20", "120", "169.05", "PN4412", "2027-11"), ("cetz", "strip", "30", "16", "22.50", "CZ1098", "2027-08")], "3000"),
            (43, 1, "AMA-8834", "net15", [("azi", "strip", "20", "85", "124.50", "AZ5531", "2027-06"), ("augm", "strip", "10", "175", "223.60", "AG7720", "2027-02"), ("benad", "btl", "24", "105", "135", "BN2209", "2027-09")], "full"),
            (41, 2, "APH/GJ/3310", "net30", [("ors", "pkt", "60", "18", "23.50", "OR8812", "2028-01"), ("volini", "tube", "12", "120", "155", "VG3301", "2027-12")], None),
            # A batch that is close to expiry (shows on Near Expiry):
            (25, 0, "MPD/2026/5690", "net30", [("pcm", "strip", "10", "29", "46.05", "DL6377", None), ("benad", "btl", "6", "100", "135", "BN1987", None)], None),
        ],
        "near_expiry_days": 24,
        "sales": [
            (38, 0, [("pcm", "15", "0"), ("cetz", "10", "0")], "full"),
            (35, 3, [("pcm", "60", "10"), ("ors", "20", "0"), ("pan", "30", "0")], "due", {"patient_name": "Ward patients (Bed 4, 7)", "doctor_name": "Dr. R. S. Kale", "prescription_note": "Shanti Nursing Home indent 1182"}),
            (32, 1, [("azi", "5", "0")], "full", {"patient_name": "Sangeeta More", "doctor_name": "Dr. S. K. Joshi", "prescription_note": "Rx dated 28 Sep"}),
            (29, 2, [("benad", "1", "0"), ("cetz", "10", "0")], "full"),
            (26, 5, [("augm", "10", "0"), ("pan", "15", "0")], "full", {"patient_name": "Kiran Wagh", "doctor_name": "Dr. Meera Patil", "prescription_note": "Belagavi Care Clinic, OPD 2231"}),
            (22, 4, [("volini", "1", "0"), ("pcm", "10", "0")], "due"),
            (18, 0, [("azi", "3", "0"), ("pcm", "6", "0")], "full", {"patient_name": "Ramesh Gupta", "doctor_name": "Dr. A. R. Kulkarni"}),
            (14, 3, [("ors", "20", "0"), ("benad", "6", "50"), ("pan", "30", "0")], "1500", {"patient_name": "Ward patients (Bed 2)", "doctor_name": "Dr. R. S. Kale"}),
            (10, 1, [("cetz", "5", "0"), ("ors", "4", "0")], "full"),
            (6, 2, [("augm", "6", "0")], "full", {"patient_name": "Vinod Kamble", "doctor_name": "Dr. N. V. Rao", "prescription_note": "Follow-up after 5 days"}),
            (3, 0, [("pcm", "10", "0"), ("benad", "1", "0")], "full"),
            (1, 4, [("pan", "15", "0")], "full", {"patient_name": "Lata Shirke", "doctor_name": "Dr. S. K. Joshi"}),
            (0, 2, [("ors", "2", "0"), ("cetz", "10", "0")], "full"),
        ],
        "receipts": [(16, 3, "800"), (5, 4, "320")],
        "supplier_payments": [(22, 0, "4000"), (12, 2, "1500")],
        "sale_return": (10, [("cetz", "5")], "Doctor changed the medicine", "account"),
        "purchase_return": (20, 2, [("ors", "10")], "Short expiry stock sent back"),
        "low_stock": {"volini": "20", "augm": "25"},
    },

    "hardware": {
        "login": ("balaji_hardware", "Toolbox#2026"),
        "shop": {
            "shop_name": "Shree Balaji Hardware & Electricals", "owner_name": "Mahesh Agarwal",
            "mobile": "9823098761", "email": "mahesh.agarwal@example.com",
            "address": "Plot 18, Pimpri Industrial Area, Old Mumbai-Pune Highway", "city": "Pimpri-Chinchwad", "pincode": "411018",
            "gst_number": "27AGRPA5512K1ZM", "pan_number": "AGRPA5512K",
        },
        "suppliers": [
            ("Finolex Cables Stockist", "Nitin Kadam", "9881234567", "27AAACF3344L1Z0", "Chinchwad MIDC", "Pune", "Maharashtra", "411019", 30),
            ("Asian Paints Depot", "Rajesh Nair", "9822123987", "27AAACA6612E1ZP", "Bhosari", "Pune", "Maharashtra", "411026", 30),
            ("Supreme Pipes Gujarat", "Bhavesh Modi", "9879012345", "24AABCS4421Q1ZL", "Sachin GIDC", "Surat", "Gujarat", "394230", 45),
        ],
        "customers": [
            ("Sharma Contractors", "9822776655", {"price_level": "wholesale", "credit_limit": "100000", "address": "Akurdi, Pune"}),
            ("Patil Electricals (Contractor)", "9767554433", {"price_level": "wholesale", "credit_limit": "60000"}),
            ("Ganesh Shinde", "9890112244", {}),
            ("Om Sai Builders", "9011998877", {"price_level": "wholesale", "credit_limit": "150000", "address": "Wakad, Pune"}),
            ("Suresh Yadav", "8806554433", {}),
            ("Vapi Industrial Works", "9898776655", {"state": "gujarat", "price_level": "wholesale", "address": "GIDC Vapi"}),
        ],
        "products": {
            "wire15": {"name": "Finolex FR Wire 1.5 sq mm", "unit": "m", "buy_in": ("coil", "90"), "cat": "Wires & Cables", "brand": "Finolex", "hsn": "8544", "gst": "18", "pp": "15.50", "sp": "22", "mrp": "", "wholesale": "19", "min": "180", "spec": "1.5 sq mm, FR PVC, 90 m coil, red"},
            "wire25": {"name": "Finolex FR Wire 2.5 sq mm", "unit": "m", "buy_in": ("coil", "90"), "cat": "Wires & Cables", "brand": "Finolex", "hsn": "8544", "gst": "18", "pp": "24", "sp": "34", "mrp": "", "wholesale": "29", "min": "180", "spec": "2.5 sq mm, FR PVC, 90 m coil, black"},
            "pipe":   {"name": "Supreme PVC Pipe 1 inch", "unit": "m", "cat": "Pipes & Fittings", "brand": "Supreme", "hsn": "3917", "gst": "18", "pp": "38", "sp": "52", "mrp": "", "wholesale": "46", "min": "60", "spec": "25 mm, 6 kg/cm², ISI"},
            "elbow":  {"name": "Supreme PVC Elbow 1 inch", "unit": "pc", "buy_in": ("box", "50"), "cat": "Pipes & Fittings", "brand": "Supreme", "hsn": "3917", "gst": "18", "pp": "9", "sp": "15", "mrp": "18", "wholesale": "12", "min": "50", "spec": "25 mm, 90 degree"},
            "paint":  {"name": "Asian Paints Apex Exterior Emulsion", "unit": "ltr", "cat": "Paints", "brand": "Asian Paints", "hsn": "3209", "gst": "18", "pp": "265", "sp": "340", "mrp": "370", "wholesale": "310", "min": "20", "spec": "White, weatherproof, 20 L bucket also available"},
            "switch": {"name": "Anchor Roma 6A Switch", "unit": "pc", "buy_in": ("box", "20"), "cat": "Electrical Fittings", "brand": "Anchor", "hsn": "8536", "gst": "18", "pp": "42", "sp": "58", "mrp": "65", "wholesale": "50", "min": "40", "spec": "6A, 1 way, white"},
            "mcb":    {"name": "Havells 32A Double Pole MCB", "unit": "pc", "cat": "Electrical Fittings", "brand": "Havells", "hsn": "8536", "gst": "18", "pp": "480", "sp": "620", "mrp": "720", "wholesale": "560", "min": "5", "spec": "32A, DP, C-curve"},
            "drill":  {"name": "Bosch GSB 500W Impact Drill", "unit": "pc", "cat": "Power Tools", "brand": "Bosch", "hsn": "8467", "gst": "18", "pp": "2650", "sp": "3290", "mrp": "3999", "wholesale": "3050", "min": "2", "spec": "500 W, 13 mm chuck, with kit"},
            "screw":  {"name": "Wood Screw 1.5 inch", "unit": "kg", "cat": "Fasteners", "brand": "Loose", "hsn": "7318", "gst": "18", "pp": "160", "sp": "220", "mrp": "", "wholesale": "190", "min": "5", "spec": "1.5 inch, CSK head, zinc plated"},
        },
        "purchases": [
            (48, 0, "FCS/26/4410", "net30", [("wire15", "coil", "10", "1395", ""), ("wire25", "coil", "6", "2160", ""), ("switch", "box", "10", "840", "1300"), ("mcb", "pc", "20", "480", "720")], "50000"),
            (46, 1, "APD-90021", "net30", [("paint", "ltr", "120", "265", "370")], "full"),
            (44, 2, "SPG/2026/1187", "net45", [("pipe", "m", "300", "38", ""), ("elbow", "box", "8", "450", "900")], None),
            (40, 0, "FCS/26/4502", "net30", [("drill", "pc", "6", "2650", "3999"), ("screw", "kg", "25.5", "160", "")], None),
        ],
        "quotations": [
            # (customer, items [(product, qty, price or "")], valid days, what happens)
            (0, [("wire15", "360", ""), ("wire25", "180", ""), ("switch", "40", "")], 15, "convert"),
            (3, [("paint", "60", "300"), ("pipe", "120", "")], 20, "open"),
            (2, [("drill", "1", "3150")], 7, "cancel"),
            (5, [("pipe", "90", ""), ("elbow", "100", "")], 30, "open"),
        ],
        "sales": [
            (34, 0, [("wire15", "180", "0"), ("switch", "20", "0"), ("mcb", "2", "0")], "due"),
            (31, 2, [("paint", "4", "0"), ("screw", "1.5", "0")], "full"),
            (28, 3, [("pipe", "60", "200"), ("elbow", "40", "0"), ("paint", "20", "0")], "8000"),
            (24, 4, [("switch", "4", "0"), ("wire15", "12.5", "0")], "full"),
            (21, 1, [("wire25", "90", "0"), ("mcb", "4", "100")], "due"),
            (17, 5, [("pipe", "45", "0"), ("elbow", "30", "0")], "full"),
            (13, 2, [("drill", "1", "100"), ("screw", "2", "0")], "full"),
            (9, 0, [("paint", "10", "0"), ("wire25", "45", "0")], "4000"),
            (5, 4, [("elbow", "6", "0"), ("pipe", "6", "0")], "full"),
            (2, 3, [("mcb", "3", "0"), ("switch", "20", "0")], "due"),
            (0, 2, [("screw", "0.5", "0"), ("switch", "2", "0")], "full"),
        ],
        "receipts": [(15, 0, "4000"), (7, 1, "5000")],
        "supplier_payments": [(25, 2, "8000"), (10, 0, "12000")],
        "sale_return": (13, [("screw", "0.5")], "Extra screws returned", "cash"),
        "purchase_return": (38, 3, [("drill", "1")], "Drill not working, returned under warranty"),
        "low_stock": {"drill": "6", "mcb": "15"},
    },
}


class Command(BaseCommand):
    help = "Create sample logins for every shop type and fill each shop with realistic sample data."

    def add_arguments(self, parser):
        parser.add_argument("--accounts-only", action="store_true", help="Only create the admin and shop logins.")

    # ------------------------------------------------------------ helpers
    def fail(self, response, what):
        detail = ""
        try:
            detail = response.json().get("message", "")
        except Exception:
            context = getattr(response, "context", None)
            if context is not None and "messages" in context:
                detail = " | ".join(str(m) for m in context["messages"])
            if not detail:
                detail = " | ".join(str(m) for m in get_messages(response.wsgi_request))
        raise CommandError(f"{what} failed: {detail or response.status_code}")

    def client_for(self, user):
        client = Client(**HOST)
        client.force_login(user)
        return client

    # ------------------------------------------------------------ accounts
    def create_accounts(self):
        for name, short in UNITS:
            if not Unit.objects.filter(short_name__iexact=short).exists():
                Unit.objects.create(name=name, short_name=short)

        admin = CustomUser.objects.filter(username=ADMIN["username"]).first()
        if admin is None:
            admin = CustomUser.objects.create_superuser(
                username=ADMIN["username"], email=ADMIN["email"], password=ADMIN["password"], user_type="admin",
            )
            self.stdout.write(self.style.SUCCESS(f"Admin created: {ADMIN['username']}"))

        admin_client = self.client_for(admin)
        for shop_type, spec in SHOPS.items():
            username, password = spec["login"]
            if CustomUser.objects.filter(username=username).exists():
                continue
            data = {
                "username": username, "password": password, "shop_type": shop_type,
                "state": "maharashtra", **spec["shop"],
            }
            response = admin_client.post(reverse("retailer_register"), data, **HOST)
            if not Retailer.objects.filter(user__username=username).exists():
                self.fail(response, f"Registering {spec['shop']['shop_name']}")
            self.stdout.write(self.style.SUCCESS(f"Shop created: {spec['shop']['shop_name']} ({username})"))

    # ------------------------------------------------------------ data
    def load_shop(self, shop_type, spec):
        username, _ = spec["login"]
        shop = Retailer.objects.get(user__username=username)
        if shop.products.exists():
            self.stdout.write(f"Skipped {shop.shop_name}: it already has products.")
            return

        features = get_features(shop)
        client = self.client_for(shop.user)
        today = timezone.localdate()
        units = {u.short_name.lower(): u for u in Unit.objects.all()}

        # Suppliers
        suppliers = []
        for name, person, mobile, gstin, address, city, state, pincode, days in spec["suppliers"]:
            suppliers.append(Supplier.objects.create(
                retailer=shop, supplier_name=name, contact_person=person, mobile=mobile,
                email=f"{name.split()[0].lower()}.orders@example.com", gst_number=gstin, pan_number=gstin[2:12],
                address=address, city=city, state=state, pincode=pincode, credit_days=days,
            ))

        # Customers (through the sale screen's "Add customer" form)
        customers = []
        for name, mobile, extra in spec["customers"]:
            data = {"customer_name": name, "mobile": mobile, "email": "", "address": extra.get("address", ""),
                    "opening_balance": extra.get("opening_balance", "0"), "credit_limit": extra.get("credit_limit", "0"),
                    "price_level": extra.get("price_level", "retail"), "state": extra.get("state", "")}
            response = client.post(reverse("create_customer_ajax"), data, **AJAX)
            if response.status_code != 201:
                self.fail(response, f"Customer {name}")
            customers.append(Customer.objects.get(retailer=shop, mobile=mobile))

        # Products (Add Product form)
        products = {}
        for key, p in spec["products"].items():
            data = {
                "category": f"other:{p['cat']}", "brand": f"other:{p['brand']}", "unit": units[p["unit"]].id,
                "product_name": p["name"], "hsn_code": p["hsn"], "barcode": "",
                "purchase_price": p["pp"], "selling_price": p["sp"], "mrp": p.get("mrp", ""),
                "gst": p["gst"], "minimum_stock": p["min"], "current_stock": "0",
                "salt_composition": p.get("salt", ""), "manufacturer": p.get("mfr", ""),
                "schedule": p.get("schedule", "none"),
                "wholesale_price": p.get("wholesale", ""), "specification": p.get("spec", ""),
            }
            if p.get("buy_in"):
                data["purchase_unit"] = units[p["buy_in"][0]].id
                data["conversion_factor"] = p["buy_in"][1]
            if p.get("opening"):
                data["current_stock"], data["opening_expiry"] = p["opening"]
            response = client.post(reverse("add_product"), data, **AJAX)
            if response.status_code != 201:
                self.fail(response, f"Product {p['name']}")
            products[key] = Product.objects.get(pk=response.json()["id"])

        # Purchase bills (New Purchase Order form), oldest first
        purchases = []
        near_expiry = (today + timedelta(days=spec.get("near_expiry_days", 30))).strftime("%Y-%m-%d")
        for days_ago, supplier_index, bill_no, terms, lines, payment in spec["purchases"]:
            bill_date = today - timedelta(days=days_ago)
            data = {"supplier": suppliers[supplier_index].id, "bill_number": bill_no, "bill_date": bill_date.isoformat(),
                    "payment_terms": terms, "discount": "0", "transport_charge": "0", "other_charge": "0",
                    "paid_amount": "0", "remarks": ""}
            total = D("0")
            for n, line in enumerate(lines, start=1):
                key, unit, qty, price, mrp = line[:5]
                data.update({
                    f"item_name_{n}": products[key].product_name, f"item_unit_{n}": units[unit].id,
                    f"item_qty_{n}": qty, f"item_free_qty_{n}": "0", f"item_price_{n}": price,
                    f"item_tax_{n}": format(products[key].gst.normalize(), "f"),
                    f"item_mrp_{n}": mrp or "0",
                })
                if features.batch_tracking:
                    batch, expiry = line[5], line[6] or near_expiry
                    data[f"item_batch_{n}"], data[f"item_expiry_{n}"] = batch, expiry
                taxable = (D(qty) * D(price)).quantize(D("0.01"))
                total += taxable + (taxable * products[key].gst / 100).quantize(D("0.01"))
            if payment:
                # Cash paid at purchase time: "full" or an amount.
                data["paid_amount"] = str(total.quantize(D("0.01"))) if payment == "full" else payment
            response = client.post(reverse("add_new_order"), data, follow=True, **HOST)
            purchase = Purchase.objects.filter(retailer=shop, bill_number=bill_no).first()
            if purchase is None:
                self.fail(response, f"Purchase {bill_no}")
            Purchase.objects.filter(pk=purchase.pk).update(created_at=timezone.now() - timedelta(days=days_ago))
            purchases.append(purchase)

        # Stock levels that need reordering (Reorder list / dashboard)
        for key, minimum in spec.get("low_stock", {}).items():
            Product.objects.filter(pk=products[key].pk).update(minimum_stock=D(minimum))

        # Quotations (hardware)
        quotations = []
        if features.quotations:
            for customer_index, lines, valid_days, outcome in spec.get("quotations", []):
                data = {"customer": customers[customer_index].id,
                        "valid_until": (today + timedelta(days=valid_days)).isoformat(),
                        "remarks": "Rates valid for the quoted quantity. Delivery within 3 working days.",
                        "action": "save"}
                for n, (key, qty, price) in enumerate(lines, start=1):
                    data.update({f"items[{n}][product]": products[key].id, f"items[{n}][quantity]": qty,
                                 f"items[{n}][selling_price]": price, f"items[{n}][discount]": "0"})
                before = set(Quotation.objects.filter(retailer=shop).values_list("id", flat=True))
                response = client.post(reverse("quotation_create"), data, follow=True, **HOST)
                created = Quotation.objects.filter(retailer=shop).exclude(id__in=before).first()
                if created is None:
                    self.fail(response, "Quotation")
                quotations.append((created, outcome))

        # Sales, oldest first; dates are moved to the sale day afterwards
        sales = []
        for row in spec["sales"]:
            days_ago, customer_index, lines, payment = row[:4]
            extra = row[4] if len(row) > 4 else {}
            customer = customers[customer_index]
            sales.append(self.make_sale(client, shop, features, customer, products, lines, payment, extra, today - timedelta(days=days_ago)))

        # Quotations: convert / cancel
        for quotation, outcome in quotations:
            if outcome == "convert":
                lines = [(item.product, item.quantity, item.discount) for item in quotation.items.all()]
                data = {"customer": quotation.customer_id, "quotation": quotation.id,
                        "paid_amount": "0", "action": "save"}
                for n, (product, qty, disc) in enumerate(lines, start=1):
                    data.update({f"items[{n}][product]": product.id, f"items[{n}][unit]": product.unit_id,
                                 f"items[{n}][quantity]": str(qty), f"items[{n}][discount]": str(disc)})
                response = client.post(reverse("sale_create"), data, follow=True, **HOST)
                quotation.refresh_from_db()
                if quotation.status != Quotation.STATUS_CONVERTED:
                    self.fail(response, f"Converting {quotation.quotation_number}")
                self.move_sale(quotation.converted_sale, today - timedelta(days=4))
            elif outcome == "cancel":
                client.post(reverse("quotation_cancel", args=[quotation.id]), **HOST)

        # Customers paying old dues in cash (khata)
        for days_ago, customer_index, amount in spec.get("receipts", []):
            customer = customers[customer_index]
            response = client.post(reverse("customer_receive_payment", args=[customer.id]), {
                "amount": amount,
                "payment_date": (today - timedelta(days=days_ago)).isoformat(), "remarks": "Old due received",
            }, follow=True, **HOST)
            if not Payment.objects.filter(customer=customer, receipt_number__isnull=False, amount__gt=0).exists():
                self.fail(response, f"Receipt from {customer.customer_name}")

        # Paying suppliers in cash (part payments on open bills)
        for days_ago, purchase_index, amount in spec.get("supplier_payments", []):
            purchase = purchases[purchase_index]
            purchase.refresh_from_db()
            pay = min(D(amount), purchase.due_amount)
            if pay <= 0:
                continue
            pay_date = max(today - timedelta(days=days_ago), purchase.bill_date)
            response = client.post(reverse("purchase_add_payment", args=[purchase.id]), {
                "amount": str(pay),
                "payment_date": pay_date.isoformat(), "remarks": "Part payment",
            }, follow=True, **HOST)

        # A sales return (credit note) and a purchase return (debit note)
        if spec.get("sale_return"):
            sale_index_hint, lines, reason, refund_mode = spec["sale_return"]
            target = next((s for s in sales if all(s.items.filter(product=products[k]).exists() for k, _ in lines)), None)
            if target is not None:
                data = {"reason": reason, "refund_mode": refund_mode}
                for key, qty in lines:
                    item = target.items.filter(product=products[key]).first()
                    data[f"return_qty_{item.id}"] = qty
                response = client.post(reverse("sale_return_create", args=[target.id]), data, follow=True, **HOST)
                if not SaleReturn.objects.filter(sale=target).exists():
                    self.fail(response, "Sales return")

        if spec.get("purchase_return"):
            _, purchase_index, lines, reason = spec["purchase_return"]
            purchase = purchases[purchase_index]
            data = {"reason": reason}
            for key, qty in lines:
                item = purchase.items.filter(product=products[key]).first()
                data[f"return_qty_{item.id}"] = qty
            response = client.post(reverse("purchase_return_create", args=[purchase.id]), data, follow=True, **HOST)
            if not PurchaseReturn.objects.filter(purchase=purchase).exists():
                self.fail(response, "Purchase return")

        self.stdout.write(self.style.SUCCESS(
            f"{shop.shop_name}: {len(products)} products, {len(suppliers)} suppliers, {len(customers)} customers, "
            f"{len(purchases)} purchase bills, {Sale.objects.filter(retailer=shop).count()} sales"
            + (f", {len(quotations)} quotations" if quotations else "")
        ))

    def make_sale(self, client, shop, features, customer, products, lines, payment, extra, sale_date):
        data = {"customer": customer.id, "action": "save", **extra}
        totals_input = []
        for n, (key, qty, discount) in enumerate(lines, start=1):
            product = products[key]
            data.update({f"items[{n}][product]": product.id, f"items[{n}][unit]": product.unit_id,
                         f"items[{n}][quantity]": qty, f"items[{n}][discount]": discount})
            totals_input.append({
                "product": product, "quantity": D(qty),
                "selling_price": D(str(product.price_for(customer, features))).quantize(D("0.01")),
                "discount": D(discount).quantize(D("0.01")), "gst": D(str(product.gst)).quantize(D("0.01")),
            })
        grand_total = calculate_sale_totals(totals_input)["grand_total"]

        # Sales are cash only: "full" = paid in full, "due" = nothing
        # paid yet (udhari), any other value = the cash paid now.
        if payment == "due":
            data["paid_amount"] = "0"
        elif payment == "full":
            data["paid_amount"] = str(grand_total)
        else:
            data["paid_amount"] = payment

        before = Sale.objects.filter(retailer=shop).count()
        response = client.post(reverse("sale_create"), data, follow=True, **HOST)
        if Sale.objects.filter(retailer=shop).count() == before:
            self.fail(response, f"Sale to {customer.customer_name}")
        sale = Sale.objects.filter(retailer=shop).latest("id")
        self.move_sale(sale, sale_date)
        return sale

    def move_sale(self, sale, sale_date):
        """Put a sale (and its khata entries and payments) on its real day."""
        stamp = timezone.now() - timedelta(days=(timezone.localdate() - sale_date).days)
        Sale.objects.filter(pk=sale.pk).update(invoice_date=sale_date, created_at=stamp)
        CustomerLedger.objects.filter(sale=sale, sale_return__isnull=True).update(date=sale_date)
        Payment.objects.filter(sale=sale, receipt_number__isnull=True).update(payment_date=sale_date)

    # ------------------------------------------------------------ main
    def handle(self, *args, **options):
        # The test runner only allows "testserver"; normal (DEBUG) runs allow localhost.
        from django.conf import settings
        host = "testserver" if "testserver" in settings.ALLOWED_HOSTS else "localhost"
        HOST["HTTP_HOST"] = AJAX["HTTP_HOST"] = host

        with transaction.atomic():
            self.create_accounts()
        if options["accounts_only"]:
            return
        for shop_type, spec in SHOPS.items():
            with transaction.atomic():
                self.load_shop(shop_type, spec)
        self.stdout.write(self.style.SUCCESS("Sample data loaded."))
