import hashlib
import json
import os
import random
from datetime import date
from pathlib import Path

from functools import wraps

from flask import Flask, Response, redirect, render_template, request, session, url_for
from werkzeug.utils import secure_filename

try:
    from azure.cosmos import CosmosClient, PartitionKey
except ImportError:  # pragma: no cover - only used when Azure SDK is not installed.
    CosmosClient = None
    PartitionKey = None

try:
    from azure.identity import DefaultAzureCredential
    from azure.storage.blob import BlobServiceClient, ContentSettings
except ImportError:  # pragma: no cover - optional for local filesystem development.
    DefaultAzureCredential = None
    BlobServiceClient = None
    ContentSettings = None

app = Flask(__name__)
app.secret_key = "local-directory-demo"

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "change-me")

DEFAULT_COMMUNITY = "miltonkeynes"
COMMUNITY_ALIASES = {
    "mk": "miltonkeynes",
    "miltonkeys": "miltonkeynes",
    "miltonkeynes": "miltonkeynes",
    "woking": "woking",
    "buckingham": "buckingham",
}
COMMUNITY_LABELS = {
    "miltonkeynes": "Milton Keynes",
    "woking": "Woking",
    "buckingham": "Buckingham",
}
COMMUNITY_TEMPLATES = {
    "miltonkeynes": "community.html",
    "woking": "community.html",
    "buckingham": "community.html",
}
CATEGORY_OPTIONS = [
    "Services",
    "Lifestyle",
    "Food",
    "Shopping",
    "Recreation",
    "Education",
    "Other",
]
LISTINGS_PER_PAGE = 16

# Simple per-page overrides for listing cards. Update these booleans to decide
# which listing features appear on the homepage vs the community pages.
LISTING_FEATURES = {
    "home": {
        "category": True,
        "description": True,
        "address": True,
        "phone": False,
        "website": False,
        "usage_counter": True,
        "contact_button": True,
    },
    "community": {
        "category": True,
        "description": True,
        "address": True,
        "phone": True,
        "website": True,
        "usage_counter": True,
        "contact_button": True,
    },
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DATA_FILE = os.path.join(DATA_DIR, "listings.json")
LOCAL_LOGO_DIR = Path(os.path.dirname(__file__)) / "static" / "uploads" / "logos"
ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


def normalize_community(value):
    community = str(value or DEFAULT_COMMUNITY).strip().lower()
    community = community.replace(" ", "-")
    return COMMUNITY_ALIASES.get(community, community or DEFAULT_COMMUNITY)


def get_community_label(community):
    if community in (None, '', 'all'):
        return 'Featured listings'
    return COMMUNITY_LABELS.get(normalize_community(community), normalize_community(community).replace("-", " ").title())


def get_community_slug(community):
    normalized = normalize_community(community)
    return "mk" if normalized == DEFAULT_COMMUNITY else normalized


def get_community_template(community):
    normalized = normalize_community(community)
    return COMMUNITY_TEMPLATES.get(normalized, "community.html")


def get_listing_feature_config(page_name):
    page = str(page_name or "home").lower()
    return LISTING_FEATURES.get(page, LISTING_FEATURES["home"]).copy()


def paginate_listings(listings, requested_page):
    try:
        page = max(1, int(requested_page or 1))
    except (TypeError, ValueError):
        page = 1

    total_pages = max(1, (len(listings) + LISTINGS_PER_PAGE - 1) // LISTINGS_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * LISTINGS_PER_PAGE
    return listings[start:start + LISTINGS_PER_PAGE], page, total_pages


def get_community_options(listings):
    communities = {
        normalize_community(item.get("community"))
        for item in listings
        if item.get("community")
    }
    if not communities:
        communities = {DEFAULT_COMMUNITY}

    return [
        {"slug": community, "label": get_community_label(community)}
        for community in sorted(communities, key=lambda item: (item != DEFAULT_COMMUNITY, item))
    ]


def requires_auth(view_func):
    @wraps(view_func)
    def wrapped(*args, **kwargs):
        auth = request.authorization
        if not auth or auth.username != ADMIN_USERNAME or auth.password != ADMIN_PASSWORD:
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Admin Area"'},
            )
        return view_func(*args, **kwargs)

    return wrapped


def normalize_listing(item):
    normalized = dict(item)
    normalized["id"] = str(normalized.get("id", ""))
    normalized["approved"] = bool(normalized.get("approved", True))
    normalized["community"] = normalize_community(normalized.get("community"))
    normalized["homepagefeatured"] = bool(normalized.get("homepagefeatured", True))
    normalized["communitypagefeatured"] = bool(normalized.get("communitypagefeatured", True))
    try:
        normalized["usage_count"] = int(normalized.get("usage_count", 0) or 0)
    except (TypeError, ValueError):
        normalized["usage_count"] = 0
    return normalized


def get_seed_data():
    return [
        normalize_listing({
            "id": 1,
            "name": "Maple Cafe",
            "category": "Food",
            "image": "https://images.unsplash.com/photo-1501339847302-ac426a4a7cbb?auto=format&fit=crop&w=160&q=80",
            "description": "Cozy neighborhood coffee shop with fresh pastries and free Wi-Fi.",
            "address": "15 Maple Street",
            "phone": "555-0142",
            "website": "https://example.com/maplecafe",
            "email": "hello@maplecafe.example",
            "instagram": "@maplecafe",
            "facebook": "Maple Cafe",
            "whatsapp_group": "https://chat.whatsapp.com/maple-cafe",
            "community": "miltonkeynes",
            "sub_community": "Central Milton Keynes",
            "opening_hours": "Mon-Sat 8am-5pm",
            "additional_information": "Local coffee roaster and community events.",
            "deals": "Free refill on selected drinks this week.",
            "homepagefeatured": True,
            "communitypagefeatured": True,
            "usage_count": 0,
        }),
        normalize_listing({
            "id": 2,
            "name": "Oak Pharmacy",
            "category": "Services",
            "description": "Local pharmacy offering prescriptions, wellness products, and advice.",
            "address": "8 Oak Lane",
            "phone": "555-0189",
            "website": "https://example.com/oakpharmacy",
            "email": "care@oakpharmacy.example",
            "community": "miltonkeynes",
            "homepagefeatured": True,
            "communitypagefeatured": True,
            "usage_count": 0,
        }),
        normalize_listing({
            "id": 3,
            "name": "River Fitness",
            "category": "Recreation",
            "description": "Gym and fitness studio with classes, lockers, and personal training.",
            "address": "44 River Road",
            "phone": "555-0112",
            "website": "https://example.com/riverfitness",
            "community": "miltonkeynes",
            "homepagefeatured": True,
            "communitypagefeatured": True,
            "usage_count": 0,
        }),
        normalize_listing({
            "id": 4,
            "name": "Woking Market Hall",
            "category": "Shopping",
            "description": "A busy local food and crafts market with weekly seasonal stalls.",
            "address": "27 High Street, Woking",
            "phone": "555-0201",
            "website": "https://example.com/wokingmarket",
            "community": "woking",
            "homepagefeatured": True,
            "communitypagefeatured": True,
            "usage_count": 0,
        }),
        normalize_listing({
            "id": 5,
            "name": "Buckingham Library Hub",
            "category": "Lifestyle",
            "description": "Community library, reading café, and free Wi-Fi for local residents.",
            "address": "10 Castle Street, Buckingham",
            "phone": "555-0202",
            "website": "https://example.com/buckinghamlibrary",
            "community": "buckingham",
            "homepagefeatured": True,
            "communitypagefeatured": True,
            "usage_count": 0,
        }),
        normalize_listing({
            "id": 6,
            "name": "The Grove Community Market",
            "category": "Shopping",
            "description": "A neighbourhood market with independent traders, snacks, and local produce.",
            "address": "21 The Grove, Milton Keynes",
            "phone": "555-0303",
            "website": "https://example.com/thegrovecommunitymarket",
            "email": "hello@thegrovecommunitymarket.example",
            "instagram": "@thegrovecommunitymarket",
            "facebook": "The Grove Community Market",
            "whatsapp_group": "https://chat.whatsapp.com/thegrovecommunitymarket",
            "community": "miltonkeynes",
            "sub_community": "Stony Stratford",
            "opening_hours": "Thu-Sun 9am-4pm",
            "additional_information": "Family-friendly market with rotating local vendors.",
            "deals": "10% off selected stalls on market day.",
            "homepagefeatured": True,
            "communitypagefeatured": True,
            "usage_count": 0,
        })
    ]


def is_cosmos_configured():
    return all(
        os.getenv(value) for value in (
            "COSMOS_ENDPOINT",
            "COSMOS_KEY",
            "COSMOS_DATABASE",
            "COSMOS_CONTAINER",
        )
    )


def get_cosmos_container():
    if not is_cosmos_configured():
        return None

    if CosmosClient is None or PartitionKey is None:
        raise RuntimeError("azure-cosmos is required when Cosmos DB is configured.")

    endpoint = os.getenv("COSMOS_ENDPOINT")
    key = os.getenv("COSMOS_KEY")
    database_name = os.getenv("COSMOS_DATABASE")
    container_name = os.getenv("COSMOS_CONTAINER")

    client = CosmosClient(endpoint, credential=key)
    database = client.get_database_client(database_name)
    container = database.get_container_client(container_name)

    database.create_container_if_not_exists(
        id=container_name,
        partition_key=PartitionKey(path="/category"),
    )
    return container


def ensure_data_file():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(DATA_FILE):
        save_listings(get_seed_data())


def filter_listings(
    listings,
    query=None,
    category=None,
    community=None,
    featured_field=None,
):
    filtered = [item for item in listings if item.get('approved', True)]

    if community:
        selected_community = normalize_community(community)
        filtered = [
            item for item in filtered
            if normalize_community(item.get('community')) == selected_community
        ]

    if query:
        needle = query.strip().lower()
        if needle:
            filtered = [
                item for item in filtered
                if any(
                    needle in str(item.get(field, '')).lower()
                    for field in ('name', 'category', 'description', 'address', 'phone', 'website')
                )
            ]

    if category:
        filtered = [
            item for item in filtered
            if str(item.get('category', '')).lower() == category.lower()
        ]

    if featured_field:
        featured = [item for item in filtered if bool(item.get(featured_field, False))]
        non_featured = [item for item in filtered if not bool(item.get(featured_field, False))]
        seed_parts = (
            date.today().isoformat(),
            featured_field,
            normalize_community(community or 'all'),
            query or '',
            category or '',
        )
        seed = int.from_bytes(
            hashlib.sha256('|'.join(seed_parts).encode('utf-8')).digest()[:8],
            'big',
        )
        random.Random(seed).shuffle(non_featured)
        filtered = featured + non_featured

    return filtered


def get_categories(listings):
    return ['All'] + CATEGORY_OPTIONS.copy()


def load_listings(community=None):
    if is_cosmos_configured():
        container = get_cosmos_container()
        if container is None:
            return []

        items = [
            normalize_listing(item)
            for item in container.query_items(
                query="SELECT * FROM c ORDER BY c.id DESC",
                enable_cross_partition_query=True,
            )
        ]
        if not items:
            seed = get_seed_data()
            for item in seed:
                container.upsert_item(item)
            return seed
        if community:
            selected_community = normalize_community(community)
            return [
                item for item in items
                if normalize_community(item.get('community')) == selected_community
            ]
        return items

    ensure_data_file()
    with open(DATA_FILE, "r", encoding="utf-8") as file:
        listings = [normalize_listing(item) for item in json.load(file)]

    if community:
        selected_community = normalize_community(community)
        return [
            item for item in listings
            if normalize_community(item.get('community')) == selected_community
        ]
    return listings


def save_listings(listings):
    normalized_items = [normalize_listing(item) for item in listings]

    if is_cosmos_configured():
        container = get_cosmos_container()
        if container is not None:
            for item in normalized_items:
                container.upsert_item(item)
            return

    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(normalized_items, file, indent=2)


def store_logo(upload, listing_id):
    if not upload or not upload.filename:
        return ""

    filename = secure_filename(upload.filename)
    extension = Path(filename).suffix.lower().lstrip(".")
    if not filename or extension not in ALLOWED_LOGO_EXTENSIONS:
        raise ValueError("Logo must be a PNG, JPEG, or WebP image.")
    if upload.content_type not in ALLOWED_LOGO_TYPES:
        raise ValueError("Logo must be a PNG, JPEG, or WebP image.")

    upload.stream.seek(0, os.SEEK_END)
    if upload.stream.tell() > MAX_LOGO_BYTES:
        raise ValueError("Logo must be 2 MB or smaller.")
    upload.stream.seek(0)

    blob_name = f"{listing_id}/logo.{extension}"
    account_url = os.getenv("AZURE_STORAGE_ACCOUNT_URL")
    container_name = os.getenv("AZURE_STORAGE_CONTAINER", "listing-logos")
    if account_url:
        if not BlobServiceClient or not DefaultAzureCredential:
            raise RuntimeError("Azure Blob Storage dependencies are not installed.")
        client = BlobServiceClient(account_url=account_url, credential=DefaultAzureCredential())
        blob_client = client.get_blob_client(container=container_name, blob=blob_name)
        blob_client.upload_blob(
            upload.stream,
            overwrite=True,
            content_settings=ContentSettings(content_type=upload.content_type),
        )
        return blob_client.url

    LOCAL_LOGO_DIR.mkdir(parents=True, exist_ok=True)
    local_path = LOCAL_LOGO_DIR / blob_name
    local_path.parent.mkdir(parents=True, exist_ok=True)
    upload.save(local_path)
    return url_for("static", filename=f"uploads/logos/{blob_name}")


@app.route('/')
def index():
    query = request.args.get('q', '').strip()
    category = request.args.get('category', 'All').strip()
    requested_page = request.args.get('page', 1)
    all_listings = load_listings()
    listings = all_listings
    filtered = filter_listings(
        listings,
        query=query,
        category=category if category != 'All' else None,
        featured_field='homepagefeatured',
    )
    paginated, page, total_pages = paginate_listings(filtered, requested_page)
    communities = get_community_options(all_listings)
    return render_template(
        'index.html',
        listings=paginated,
        query=query,
        category=category,
        categories=get_categories(all_listings),
        communities=communities,
        community_slug='all',
        community_label='Featured listings',
        selected_community='all',
        listing_features=get_listing_feature_config('home'),
        page=page,
        total_pages=total_pages,
        pagination_endpoint='index',
    )


@app.route('/mk', endpoint='milton_keynes_page')
@app.route('/miltonkeynes', endpoint='milton_keynes_page')
@app.route('/woking', endpoint='woking_page')
@app.route('/buckingham', endpoint='buckingham_page')
def community_page(community_slug=None):
    requested = (community_slug or request.path.lstrip('/')).strip().lower()
    requested = 'miltonkeynes' if requested in ('mk', 'miltonkeynes') else requested
    normalized = normalize_community(requested)
    allowed = set(COMMUNITY_LABELS)

    if normalized not in allowed:
        return render_template('404.html', communities=get_community_options(load_listings())), 404

    query = request.args.get('q', '').strip()
    category = request.args.get('category', 'All').strip()
    requested_page = request.args.get('page', 1)
    all_listings = load_listings()
    listings = load_listings(normalized)
    filtered = filter_listings(
        listings,
        query=query,
        category=category if category != 'All' else None,
        community=normalized,
        featured_field='communitypagefeatured',
    )
    paginated, page, total_pages = paginate_listings(filtered, requested_page)
    communities = get_community_options(all_listings)
    template_name = get_community_template(normalized)
    return render_template(
        template_name,
        listings=paginated,
        query=query,
        category=category,
        categories=get_categories(listings),
        communities=communities,
        community_slug=get_community_slug(normalized),
        community_label=get_community_label(normalized),
        selected_community=get_community_slug(normalized),
        listing_features=get_listing_feature_config('community'),
        page=page,
        total_pages=total_pages,
        pagination_endpoint=request.endpoint,
    )


@app.route('/add', methods=['GET', 'POST'])
def add_listing():
    selected_community = normalize_community(request.args.get('community') or DEFAULT_COMMUNITY)
    communities = get_community_options(load_listings())

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        address = request.form.get('address', '').strip()
        phone = (request.form.get('phone_number') or request.form.get('phone') or '').strip()
        website = request.form.get('website', '').strip()
        email = request.form.get('email', '').strip()
        instagram = request.form.get('instagram', '').strip()
        facebook = request.form.get('facebook', '').strip()
        whatsapp_group = request.form.get('whatsapp_group') or request.form.get('whatsappgroup') or ''
        whatsapp_group = whatsapp_group.strip()
        community = normalize_community(request.form.get('community') or selected_community)
        sub_community = request.form.get('sub_community', '').strip()
        opening_hours = request.form.get('opening_hours', '').strip()
        additional_information = request.form.get('additional_information', '').strip()
        deals = request.form.get('deals', '').strip()
        logo = request.files.get('logo')

        if not name or category not in CATEGORY_OPTIONS or not address:
            return render_template(
                'add_listing.html',
            error='Please provide a business name, valid category, and address.',
                form=request.form,
                communities=communities,
                selected_community=community,
            )

        listings = load_listings()
        numeric_ids = []
        for item in listings:
            try:
                numeric_ids.append(int(str(item.get('id', '0'))))
            except (TypeError, ValueError):
                continue

        next_id = max(numeric_ids, default=0) + 1
        try:
            logo_url = store_logo(logo, next_id)
        except (OSError, RuntimeError, ValueError) as error:
            return render_template(
                'add_listing.html',
                error=str(error),
                form=request.form,
                communities=communities,
                selected_community=community,
            )

        new_listing = normalize_listing({
            'id': next_id,
            'name': name,
            'category': category,
            'description': description or 'A local spot to discover and support.',
            'address': address,
            'phone': phone,
            'website': website,
            'email': email,
            'instagram': instagram,
            'facebook': facebook,
            'whatsapp_group': whatsapp_group,
            'community': community,
            'sub_community': sub_community,
            'opening_hours': opening_hours,
            'additional_information': additional_information,
            'deals': deals,
            'logo_url': logo_url,
            'approved': False,
            'pending_action': 'add',
            'homepagefeatured': False,
            'communitypagefeatured': False,
        })

        if is_cosmos_configured():
            container = get_cosmos_container()
            if container is not None:
                container.upsert_item(new_listing)
                return redirect(url_for('index', community_slug=get_community_slug(community)))

        listings.insert(0, new_listing)
        save_listings(listings)
        return redirect(url_for('index', community_slug=get_community_slug(community)))

    return render_template(
        'add_listing.html',
        communities=communities,
        selected_community=selected_community,
    )


@app.route('/listing/<listing_id>/edit', methods=['GET', 'POST'])
def edit_listing(listing_id):
    listings = load_listings()
    listing = next((item for item in listings if str(item.get('id')) == str(listing_id)), None)
    if listing is None:
        return render_template('404.html', communities=get_community_options(listings)), 404

    communities = get_community_options(listings)
    selected_community = normalize_community(listing.get('community'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        address = request.form.get('address', '').strip()
        community = normalize_community(request.form.get('community') or selected_community)

        if not name or category not in CATEGORY_OPTIONS or not address:
            return render_template(
                'add_listing.html',
                error='Please provide a business name, valid category, and address.',
                form=request.form,
                listing=listing,
                editing=True,
                communities=communities,
                selected_community=community,
            )

        updated_values = {
            'name': name,
            'category': category,
            'description': request.form.get('description', '').strip() or 'A local spot to discover and support.',
            'address': address,
            'phone': (request.form.get('phone_number') or request.form.get('phone') or '').strip(),
            'website': request.form.get('website', '').strip(),
            'email': request.form.get('email', '').strip(),
            'instagram': request.form.get('instagram', '').strip(),
            'facebook': request.form.get('facebook', '').strip(),
            'whatsapp_group': (request.form.get('whatsapp_group') or request.form.get('whatsappgroup') or '').strip(),
            'community': community,
            'sub_community': request.form.get('sub_community', '').strip(),
            'opening_hours': request.form.get('opening_hours', '').strip(),
            'additional_information': request.form.get('additional_information', '').strip(),
            'deals': request.form.get('deals', '').strip(),
        }

        logo = request.files.get('logo')
        try:
            if logo and logo.filename:
                updated_values['logo_url'] = store_logo(logo, listing_id)
        except (OSError, RuntimeError, ValueError) as error:
            return render_template(
                'add_listing.html',
                error=str(error),
                form=request.form,
                listing=listing,
                editing=True,
                communities=communities,
                selected_community=community,
            )

        listing['pending_changes'] = updated_values
        listing['pending_action'] = 'edit'
        save_listings(listings)
        return redirect(url_for('index'))

    return render_template(
        'add_listing.html',
        form=listing,
        listing=listing,
        editing=True,
        communities=communities,
        selected_community=selected_community,
    )


@app.route('/listing/<listing_id>/delete', methods=['POST'])
def request_listing_deletion(listing_id):
    listings = load_listings()
    for item in listings:
        if str(item.get('id')) == str(listing_id):
            item['pending_action'] = 'delete'
            save_listings(listings)
            break
    return redirect(url_for('index'))

@app.route('/listing/<listing_id>')
def listing_detail(listing_id):
    listing_id = str(listing_id)
    listings = load_listings()
    listing = None
    viewed_listings = {str(item) for item in session.get('viewed_listings', [])}
    for item in listings:
        if str(item.get('id')) == listing_id:
            listing = item
            if listing_id not in viewed_listings:
                item['usage_count'] = int(item.get('usage_count', 0) or 0) + 1
                save_listings(listings)
                viewed_listings.add(listing_id)
                session['viewed_listings'] = list(viewed_listings)
                session.modified = True
            break

    if listing is None:
        return render_template('404.html', communities=get_community_options(load_listings())), 404

    return render_template(
        'listing_detail.html',
        listing=listing,
        communities=get_community_options(load_listings()),
        community_label=get_community_label(listing.get('community')),
    )


@app.route('/admin')
@requires_auth
def admin():
    field_labels = {
        'name': 'Name',
        'category': 'Category',
        'description': 'Description',
        'address': 'Address',
        'phone': 'Phone',
        'website': 'Website',
        'email': 'Email',
        'instagram': 'Instagram',
        'facebook': 'Facebook',
        'whatsapp_group': 'WhatsApp group',
        'community': 'Community',
        'sub_community': 'Sub community',
        'opening_hours': 'Opening hours',
        'additional_information': 'Additional information',
        'deals': 'Deals / special promotions',
        'logo_url': 'Logo',
    }
    pending = []
    for item in load_listings():
        if item.get('approved', True) and not item.get('pending_action'):
            continue
        review_item = dict(item)
        if item.get('pending_action') == 'edit':
            pending_changes = item.get('pending_changes') or {}
            review_item['pending_diff'] = [
                {
                    'label': field_labels.get(field, field.replace('_', ' ').title()),
                    'before': item.get(field) or 'Not set',
                    'after': value or 'Not set',
                }
                for field, value in pending_changes.items()
                if value != item.get(field)
            ]
            review_item.update(pending_changes)
        pending.append(review_item)
    return render_template('admin.html', listings=pending)


@app.route('/admin/approve/<listing_id>', methods=['POST'])
@requires_auth
def approve_listing(listing_id):
    listings = load_listings()
    for item in listings:
        if str(item.get('id')) == str(listing_id):
            if item.get('pending_action', 'add') == 'delete':
                listings.remove(item)
                save_listings(listings)
                return redirect(url_for('admin'))
            if item.get('pending_action') == 'edit':
                item.update(item.pop('pending_changes', {}))
            item['approved'] = True
            item['pending_action'] = ''
            save_listings(listings)
            break
    return redirect(url_for('admin'))


@app.route('/admin/reject/<listing_id>', methods=['POST'])
@requires_auth
def reject_listing(listing_id):
    listings = load_listings()
    for item in listings:
        if str(item.get('id')) == str(listing_id):
            if item.get('pending_action', 'add') == 'add':
                listings.remove(item)
            else:
                item.pop('pending_changes', None)
                item['approved'] = True
                item['pending_action'] = ''
            break
    save_listings(listings)
    return redirect(url_for('admin'))


@app.route('/listing/<listing_id>/contact', methods=['POST'])
def record_contact(listing_id):
    listing_id = str(listing_id)
    used_listings = [str(item) for item in session.get('contacted_listings', [])]

    if listing_id in used_listings:
        return redirect(url_for('index'))

    listings = load_listings()
    for item in listings:
        if str(item.get('id')) == listing_id:
            item['usage_count'] = int(item.get('usage_count', 0) or 0) + 1
            save_listings(listings)
            break

    used_listings.append(listing_id)
    session['contacted_listings'] = used_listings
    session.modified = True
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8000, debug=True)
