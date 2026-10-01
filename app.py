import hashlib
import json
import os
import random
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

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
EVENT_COMMUNITY_LABELS = {**COMMUNITY_LABELS, "other": "Other"}
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
MAX_LISTING_NAME_LENGTH = 40
DAYS_OF_WEEK = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Simple per-page overrides for listing cards. Update these booleans to decide
# which listing features appear on the homepage vs the community pages.
LISTING_FEATURES = {
    "home": {
        "category": True,
        "description": True,
        "community": True,
        "sub_community": True,
        "phone": False,
        "website": False,
        "usage_counter": True,
        "contact_button": True,
    },
    "community": {
        "category": True,
        "description": True,
        "community": True,
        "sub_community": True,
        "phone": False,
        "website": False,
        "usage_counter": True,
        "contact_button": True,
    },
}

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
DATA_FILE = os.path.join(DATA_DIR, "listings.json")
EVENT_DATA_FILE = os.path.join(DATA_DIR, "events.json")
LOCAL_LOGO_DIR = Path(os.path.dirname(__file__)) / "static" / "uploads" / "logos"
ALLOWED_LOGO_EXTENSIONS = {"png", "jpg", "jpeg", "webp"}
ALLOWED_LOGO_TYPES = {"image/png", "image/jpeg", "image/webp"}
MAX_LOGO_BYTES = 2 * 1024 * 1024


def normalize_community(value):
    community = str(value or DEFAULT_COMMUNITY).strip().lower()
    community = community.replace(" ", "-")
    return COMMUNITY_ALIASES.get(community, community or DEFAULT_COMMUNITY)


def is_valid_listing_name(value):
    return (
        len(value) <= MAX_LISTING_NAME_LENGTH
        and all(character.isalpha() or character == ' ' for character in value)
    )


@app.template_filter('external_url')
def external_url(value):
    url = str(value or '').strip()
    if url and not url.startswith(('http://', 'https://')):
        return f'https://{url}'
    return url


@app.template_filter('listing_initials')
def listing_initials(value):
    words = [
        ''.join(character for character in word if character.isalnum())
        for word in str(value or '').split()
    ]
    return ''.join(word[0].upper() for word in words if word)[:2] or '?'


@app.template_filter('listing_fallback_color')
def listing_fallback_color(value):
    colors = ('#9b3c36', '#286650', '#355b85', '#874b65', '#7a4b15', '#684b8a')
    digest = hashlib.sha256(str(value or '').encode('utf-8')).digest()
    return colors[int.from_bytes(digest[:4], 'big') % len(colors)]


@app.template_filter('uk_date')
def uk_date(value):
    try:
        return date.fromisoformat(str(value)).strftime('%d/%m/%Y')
    except ValueError:
        return str(value)


def format_phone_number(value):
    phone = str(value or '').strip()
    digits = ''.join(character for character in phone if character.isdigit())
    if len(digits) == 11:
        return f'{digits[:5]} {digits[5:]}'
    return phone


app.add_template_filter(format_phone_number, 'phone_format')


def phone_link(value):
    return ''.join(character for character in str(value or '') if character.isdigit() or character == '+')


app.add_template_filter(phone_link, 'phone_link')


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


def parse_opening_hours(form, existing=None):
    periods = {}
    has_daily_hours = False
    for day in DAYS_OF_WEEK:
        day_periods = []
        for period_number in (1, 2):
            opening = (form.get(f'opening_{day}_{period_number}_open') or '').strip()
            closing = (form.get(f'opening_{day}_{period_number}_close') or '').strip()
            if opening or closing:
                has_daily_hours = True
            if opening and closing:
                day_periods.append({'open': opening, 'close': closing})
        periods[day] = day_periods

    return periods if has_daily_hours else (existing or '')


def paginate_listings(listings, requested_page):
    try:
        page = max(1, int(requested_page or 1))
    except (TypeError, ValueError):
        page = 1

    total_pages = max(1, (len(listings) + LISTINGS_PER_PAGE - 1) // LISTINGS_PER_PAGE)
    page = min(page, total_pages)
    start = (page - 1) * LISTINGS_PER_PAGE
    return listings[start:start + LISTINGS_PER_PAGE], page, total_pages


def normalize_listing_slug(value):
    return ''.join(str(value or '').lower().split())


def get_listing_slugs(listings):
    base_slugs = {}
    slug_counts = {}
    for listing in listings:
        listing_id = str(listing.get('id', ''))
        base_slug = normalize_listing_slug(listing.get('name')) or f'listing{listing_id}'
        base_slugs[listing_id] = base_slug
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1

    return {
        listing_id: f'{base_slug}-{listing_id}' if slug_counts[base_slug] > 1 else base_slug
        for listing_id, base_slug in base_slugs.items()
    }


def get_community_options(listings):
    communities = set(COMMUNITY_LABELS)
    communities.update(
        normalize_community(item.get("community"))
        for item in listings
        if item.get("community")
    )

    return [
        {"slug": community, "label": get_community_label(community)}
        for community in sorted(communities, key=lambda item: (item != DEFAULT_COMMUNITY, item))
    ]


def get_event_community_options():
    return get_community_options([]) + [{"slug": "other", "label": EVENT_COMMUNITY_LABELS["other"]}]


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


def get_events_container():
    if not is_cosmos_configured():
        return None

    if CosmosClient is None or PartitionKey is None:
        raise RuntimeError("azure-cosmos is required when Cosmos DB is configured.")

    client = CosmosClient(os.getenv("COSMOS_ENDPOINT"), credential=os.getenv("COSMOS_KEY"))
    database = client.get_database_client(os.getenv("COSMOS_DATABASE"))
    return database.create_container_if_not_exists(
        id=os.getenv("COSMOS_EVENTS_CONTAINER", "events"),
        partition_key=PartitionKey(path="/community"),
    )


def load_events(community=None):
    if is_cosmos_configured():
        if community:
            return list(get_events_container().query_items(
                query="SELECT * FROM c WHERE c.community = @community",
                parameters=[{'name': '@community', 'value': community}],
                partition_key=community,
            ))
        return list(get_events_container().query_items(
            query="SELECT * FROM c", enable_cross_partition_query=True,
        ))
    if not os.path.exists(EVENT_DATA_FILE):
        return []
    with open(EVENT_DATA_FILE, "r", encoding="utf-8") as file:
        events = json.load(file)
    return [event for event in events if event.get('community') == community] if community else events


def save_event(event):
    if is_cosmos_configured():
        get_events_container().upsert_item(event)
        return
    events = load_events()
    events.append(event)
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(EVENT_DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(events, file, indent=2)


def update_event(event):
    if is_cosmos_configured():
        get_events_container().upsert_item(event)
        return
    events = load_events()
    events = [event if str(item['id']) == str(event['id']) else item for item in events]
    with open(EVENT_DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(events, file, indent=2)


def delete_event(event):
    if is_cosmos_configured():
        get_events_container().delete_item(item=event['id'], partition_key=event['community'])
        return
    remaining_events = [item for item in load_events() if str(item['id']) != str(event['id'])]
    with open(EVENT_DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(remaining_events, file, indent=2)


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


def delete_listing_record(listings, listing):
    if is_cosmos_configured():
        container = get_cosmos_container()
        if container is not None:
            container.delete_item(
                item=str(listing.get('id')),
                partition_key=listing.get('category'),
            )
            return

    listings.remove(listing)
    save_listings(listings)


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
        if not BlobServiceClient:
            raise RuntimeError("Azure Blob Storage dependencies are not installed.")
        storage_key = os.getenv("AZURE_STORAGE_ACCOUNT_KEY")
        if storage_key:
            credential = storage_key
        else:
            if not DefaultAzureCredential:
                raise RuntimeError("Azure identity dependencies are not installed.")
            credential = DefaultAzureCredential()
        client = BlobServiceClient(account_url=account_url, credential=credential)
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
    listing_slugs = get_listing_slugs(all_listings)
    return render_template(
        'index.html',
        listings=paginated,
        query=query,
        category=category,
        categories=get_categories(all_listings),
        communities=communities,
        listing_slugs=listing_slugs,
        community_slug='all',
        community_label='Featured listings',
        selected_community='all',
        listing_features=get_listing_feature_config('home'),
        page=page,
        total_pages=total_pages,
        total_listings=len(filtered),
        pagination_endpoint='index',
    )


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/terms')
def terms_of_use():
    return render_template('terms.html')


@app.route('/events')
def events_page():
    community = request.args.get('community', 'all')
    query = request.args.get('q', '').strip()
    if community != 'all' and community not in EVENT_COMMUNITY_LABELS:
        return render_template('404.html'), 404
    upcoming = [
        {**event, **occurrence}
        for event in load_events(community if community != 'all' else None)
        if event.get('approved')
        for occurrence in get_event_schedule(event)
        if occurrence['date'] >= date.today().isoformat()
    ]
    if query:
        needle = query.casefold()
        upcoming = [
            event for event in upcoming
            if any(needle in str(event.get(field, '')).casefold() for field in ('name', 'description', 'venue'))
            or needle in EVENT_COMMUNITY_LABELS.get(event['community'], event['community']).casefold()
            or needle in event['date'] or needle in uk_date(event['date'])
        ]
    upcoming.sort(key=lambda event: (event['date'], event['start_time'], event['name']))
    paginated, page, total_pages = paginate_listings(upcoming, request.args.get('page', 1))
    return render_template(
        'events.html', events=paginated, selected_community=community,
        communities=get_event_community_options(), query=query,
        event_slugs=get_event_slugs(load_events()),
        page=page, total_pages=total_pages, total_events=len(upcoming),
    )


def get_event_schedule(event):
    if 'schedule' in event:
        return event['schedule']
    if event.get('date'):
        return [{'date': event['date'], 'start_time': event.get('time', ''), 'end_time': ''}]
    return []


def get_event_slugs(events):
    base_slugs = {}
    slug_counts = {}
    for event in events:
        event_id = str(event.get('id', ''))
        base_slug = normalize_listing_slug(event.get('name')) or f'event{event_id}'
        base_slugs[event_id] = base_slug
        slug_counts[base_slug] = slug_counts.get(base_slug, 0) + 1

    return {
        event_id: f'{base_slug}-{event_id}' if slug_counts[base_slug] > 1 else base_slug
        for event_id, base_slug in base_slugs.items()
    }


def format_event_review_value(field, value):
    if field == 'schedule':
        return ', '.join(
            f"{uk_date(occurrence['date'])}: {occurrence['start_time']} - {occurrence['end_time']}"
            for occurrence in (value or [])
        ) or 'Not set'
    return value or 'Not set'


@app.route('/events/<event_id>')
def event_detail(event_id):
    events = load_events()
    requested_identifier = str(event_id)
    event = next(
        (item for item in events if str(item.get('id')) == requested_identifier and item.get('approved')),
        None,
    )
    if event is None:
        event_slugs = get_event_slugs(events)
        event = next(
            (item for item in events if event_slugs.get(str(item.get('id'))) == requested_identifier and item.get('approved')),
            None,
        )
    if event is None:
        return render_template('404.html'), 404
    schedule = sorted(
        (occurrence for occurrence in get_event_schedule(event) if occurrence['date'] >= date.today().isoformat()),
        key=lambda occurrence: (occurrence['date'], occurrence['start_time']),
    )
    if not schedule:
        return render_template('404.html'), 404
    viewed_events = {str(item) for item in session.get('viewed_events', [])}
    event_id = str(event['id'])
    if event_id not in viewed_events:
        event['usage_count'] = int(event.get('usage_count', 0) or 0) + 1
        update_event(event)
        viewed_events.add(event_id)
        session['viewed_events'] = list(viewed_events)
        session.modified = True
    return render_template(
        'event_detail.html', event=event, schedule=schedule,
        community_label=EVENT_COMMUNITY_LABELS.get(event['community'], event['community']),
    )


@app.route('/events/<event_id>/attendance', methods=['POST'])
def event_attendance(event_id):
    event = next(
        (item for item in load_events() if str(item['id']) == event_id and item.get('approved')),
        None,
    )
    if event is None or not any(
        occurrence['date'] >= date.today().isoformat() for occurrence in get_event_schedule(event)
    ):
        return render_template('404.html'), 404

    choice = request.form.get('attendance')
    if choice not in ('going', 'not_going'):
        return Response('Invalid attendance choice.', status=400)

    choices = dict(session.get('event_attendance', {}))
    previous = choices.get(event_id)
    if previous != choice:
        if previous in ('going', 'not_going'):
            previous_field = f'{previous}_count'
            event[previous_field] = max(0, int(event.get(previous_field, 0) or 0) - 1)
        field = f'{choice}_count'
        event[field] = int(event.get(field, 0) or 0) + 1
        update_event(event)
        choices[event_id] = choice
        session['event_attendance'] = choices
        session.modified = True

    if request.form.get('source') == 'detail':
        return redirect(url_for('event_detail', event_id=event_id))
    community = request.form.get('community', 'all')
    if community not in EVENT_COMMUNITY_LABELS:
        community = 'all'
    query = request.form.get('q', '').strip()
    return redirect(url_for('events_page', community=community, q=query))


def parse_event_form(form):
    dates = form.getlist('date[]')
    start_times = form.getlist('start_time[]')
    end_times = form.getlist('end_time[]')
    schedule_rows = [
        {'date': event_date.strip(), 'start_time': start.strip(), 'end_time': end.strip()}
        for event_date, start, end in zip(dates, start_times, end_times)
    ]
    values = {
        'name': form.get('name', '').strip(),
        'description': form.get('description', '').strip(),
        'community': form.get('community', '').strip(),
        'schedule': schedule_rows,
        'venue': form.get('venue', '').strip(),
        'details_url': form.get('details_url', '').strip(),
    }
    valid_schedule = bool(dates) and len(dates) == len(start_times) == len(end_times)
    for occurrence in schedule_rows:
        try:
            event_day = date.fromisoformat(occurrence['date'])
            starts = datetime.strptime(occurrence['start_time'], '%H:%M')
            ends = datetime.strptime(occurrence['end_time'], '%H:%M')
            valid_schedule &= (
                event_day >= date.today()
                and starts.strftime('%H:%M') == occurrence['start_time']
                and ends.strftime('%H:%M') == occurrence['end_time']
                and ends > starts
            )
        except ValueError:
            valid_schedule = False
    if not values['name'] or not values['description'] or values['community'] not in EVENT_COMMUNITY_LABELS or not values['venue'] or not valid_schedule:
        return values, 'Provide an event name, description, community, address or venue, and future dates with end times after start times.'
    if values['details_url']:
        try:
            parsed_url = urlsplit(values['details_url'])
            valid_url = parsed_url.scheme in ('http', 'https') and bool(parsed_url.hostname)
        except ValueError:
            valid_url = False
        if not valid_url:
            return values, 'Enter a valid http:// or https:// event link.'
    return values, None


@app.route('/events/add', methods=['GET', 'POST'])
def add_event():
    communities = get_event_community_options()
    if request.method == 'POST':
        values, error = parse_event_form(request.form)
        if error:
            return render_template(
                'add_event.html', communities=communities, form=request.form,
                schedule_rows=values['schedule'] or [{'date': '', 'start_time': '', 'end_time': ''}],
                error=error, now_date=date.today().isoformat(),
            ), 400

        save_event({
            'id': str(uuid4()), **values, 'approved': False,
            'usage_count': 0, 'going_count': 0, 'not_going_count': 0,
        })
        return redirect(url_for('events_page', submitted='1'))

    return render_template(
        'add_event.html', communities=communities, form={}, now_date=date.today().isoformat(),
        schedule_rows=[{'date': '', 'start_time': '', 'end_time': ''}],
    )


@app.route('/events/<event_id>/edit', methods=['GET', 'POST'])
def edit_event(event_id):
    event = next((item for item in load_events() if str(item['id']) == event_id and item.get('approved')), None)
    if event is None or not any(
        occurrence['date'] >= date.today().isoformat() for occurrence in get_event_schedule(event)
    ):
        return render_template('404.html'), 404
    if event.get('pending_action'):
        return Response('This event already has a change awaiting admin review.', status=409)

    communities = get_event_community_options()
    if request.method == 'POST':
        values, error = parse_event_form(request.form)
        if error:
            return render_template(
                'add_event.html', communities=communities, form=request.form,
                schedule_rows=values['schedule'] or [{'date': '', 'start_time': '', 'end_time': ''}],
                error=error, now_date=date.today().isoformat(), editing=True, event=event,
            ), 400
        event['pending_changes'] = values
        event['pending_action'] = 'edit'
        update_event(event)
        return redirect(url_for('event_detail', event_id=event_id))

    return render_template(
        'add_event.html', communities=communities, form=event,
        schedule_rows=get_event_schedule(event), now_date=date.today().isoformat(),
        editing=True, event=event,
    )


@app.route('/events/<event_id>/delete', methods=['POST'])
def request_event_deletion(event_id):
    event = next((item for item in load_events() if str(item['id']) == event_id and item.get('approved')), None)
    if event is None:
        return render_template('404.html'), 404
    if event.get('pending_action'):
        return Response('This event already has a change awaiting admin review.', status=409)
    event['pending_action'] = 'delete'
    update_event(event)
    return redirect(url_for('events_page'))


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
    listing_slugs = get_listing_slugs(all_listings)
    template_name = get_community_template(normalized)
    return render_template(
        template_name,
        listings=paginated,
        query=query,
        category=category,
        categories=get_categories(listings),
        communities=communities,
        listing_slugs=listing_slugs,
        community_slug=get_community_slug(normalized),
        community_label=get_community_label(normalized),
        selected_community=get_community_slug(normalized),
        listing_features=get_listing_feature_config('community'),
        page=page,
        total_pages=total_pages,
        total_listings=len(filtered),
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
        phone = format_phone_number(request.form.get('phone_number') or request.form.get('phone') or '')
        website = request.form.get('website', '').strip()
        email = request.form.get('email', '').strip()
        instagram = request.form.get('instagram', '').strip()
        facebook = request.form.get('facebook', '').strip()
        google_maps_location = request.form.get('google_maps_location', '').strip()
        google_business_profile = request.form.get('google_business_profile', '').strip()
        whatsapp_group = request.form.get('whatsapp_group') or request.form.get('whatsappgroup') or ''
        whatsapp_group = whatsapp_group.strip()
        community_value = request.form.get('community', '').strip()
        community = normalize_community(community_value) if community_value else ''
        sub_community = request.form.get('sub_community', '').strip()
        opening_hours = parse_opening_hours(request.form)
        additional_information = request.form.get('additional_information', '').strip()
        deals = request.form.get('deals', '').strip()
        logo = request.files.get('logo')

        if not community or not name or category not in CATEGORY_OPTIONS or not description:
            return render_template(
                'add_listing.html',
                error='Please provide a community, business name, valid category, and description.',
                form=request.form,
                communities=communities,
                selected_community=community or selected_community,
            )
        if not is_valid_listing_name(name):
            return render_template(
                'add_listing.html',
                error='Name must contain letters and spaces only and be 40 characters or fewer.',
                form=request.form,
                communities=communities,
                selected_community=community,
            )
        if len(description) > 150:
            return render_template(
                'add_listing.html',
                error='Description must be 150 characters or fewer.',
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
            'description': description,
            'address': address,
            'phone': phone,
            'website': website,
            'email': email,
            'instagram': instagram,
            'facebook': facebook,
            'google_maps_location': google_maps_location,
            'google_business_profile': google_business_profile,
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
    admin_mode = request.args.get('admin') == '1'
    if admin_mode:
        auth = request.authorization
        if not auth or auth.username != ADMIN_USERNAME or auth.password != ADMIN_PASSWORD:
            return Response(
                "Authentication required.",
                401,
                {"WWW-Authenticate": 'Basic realm="Admin Area"'},
            )

    listings = load_listings()
    listing = next((item for item in listings if str(item.get('id')) == str(listing_id)), None)
    if listing is None:
        return render_template('404.html', communities=get_community_options(listings)), 404

    communities = get_community_options(listings)
    selected_community = normalize_community(listing.get('community'))

    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        category = request.form.get('category', '').strip()
        description = request.form.get('description', '').strip()
        address = request.form.get('address', '').strip()
        community_value = request.form.get('community', '').strip()
        community = normalize_community(community_value) if community_value else ''

        if not community or not name or category not in CATEGORY_OPTIONS or not description:
            return render_template(
                'add_listing.html',
                error='Please provide a community, business name, valid category, and description.',
                form=request.form,
                listing=listing,
                editing=True,
                communities=communities,
                selected_community=community or selected_community,
            )
        if not is_valid_listing_name(name):
            return render_template(
                'add_listing.html',
                error='Name must contain letters and spaces only and be 40 characters or fewer.',
                form=request.form,
                listing=listing,
                editing=True,
                communities=communities,
                selected_community=community,
            )
        if len(description) > 150:
            return render_template(
                'add_listing.html',
                error='Description must be 150 characters or fewer.',
                form=request.form,
                listing=listing,
                editing=True,
                communities=communities,
                selected_community=community,
            )

        updated_values = {
            'name': name,
            'category': category,
            'description': description,
            'address': address,
            'phone': format_phone_number(request.form.get('phone_number') or request.form.get('phone') or ''),
            'website': request.form.get('website', '').strip(),
            'email': request.form.get('email', '').strip(),
            'instagram': request.form.get('instagram', '').strip(),
            'facebook': request.form.get('facebook', '').strip(),
            'google_maps_location': request.form.get('google_maps_location', '').strip(),
            'google_business_profile': request.form.get('google_business_profile', '').strip(),
            'whatsapp_group': (request.form.get('whatsapp_group') or request.form.get('whatsappgroup') or '').strip(),
            'community': community,
            'sub_community': request.form.get('sub_community', '').strip(),
            'opening_hours': parse_opening_hours(request.form, listing.get('opening_hours')),
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

        if admin_mode:
            listing.update(updated_values)
            listing.pop('pending_changes', None)
            listing['approved'] = True
            listing['pending_action'] = ''
        else:
            listing['pending_changes'] = updated_values
            listing['pending_action'] = 'edit'
        save_listings(listings)
        return redirect(url_for('admin' if admin_mode else 'index'))

    return render_template(
        'add_listing.html',
        form=listing,
        listing=listing,
        editing=True,
        admin_mode=admin_mode,
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
    requested_identifier = str(listing_id)
    listings = load_listings()
    listing = next((item for item in listings if str(item.get('id')) == requested_identifier), None)
    listing_slugs = get_listing_slugs(listings)
    if listing is None:
        requested_slug = normalize_listing_slug(requested_identifier)
        listing = next(
            (item for item in listings if listing_slugs.get(str(item.get('id'))) == requested_slug),
            None,
        )

    if listing is None:
        return render_template('404.html', communities=get_community_options(listings)), 404

    listing_id = str(listing.get('id'))
    viewed_listings = {str(item) for item in session.get('viewed_listings', [])}
    if listing_id not in viewed_listings:
        listing['usage_count'] = int(listing.get('usage_count', 0) or 0) + 1
        save_listings(listings)
        viewed_listings.add(listing_id)
        session['viewed_listings'] = list(viewed_listings)
        session.modified = True

    return render_template(
        'listing_detail.html',
        listing=listing,
        communities=get_community_options(load_listings()),
        community_label=get_community_label(listing.get('community')),
    )


@app.route('/admin')
@requires_auth
def admin():
    query = request.args.get('q', '').strip().lower()
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
    existing = []
    pending = []
    for item in load_listings():
        review_item = dict(item)
        has_pending_work = not item.get('approved', True) or bool(item.get('pending_action'))
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

        matches_query = not query or any(
            query in str(review_item.get(field, '')).lower()
            for field in ('name', 'category', 'description', 'address', 'phone', 'website', 'community')
        )
        if has_pending_work:
            pending.append(review_item)
        elif query and matches_query:
            existing.append(review_item)

    admin_sections = [
        {
            'kind': 'existing',
            'heading': 'Manage existing listings',
            'description': 'Search and manage published listings directly.',
            'listings': existing,
        },
        {
            'kind': 'pending',
            'heading': 'Approve new and changed listings',
            'description': 'Review new submissions and pending edits or deletions.',
            'listings': pending,
        },
    ]
    events = load_events()
    event_field_labels = {
        'name': 'Name', 'description': 'Description', 'community': 'Community',
        'schedule': 'Date and Time', 'venue': 'Address / Venue', 'details_url': 'Event Link',
    }
    pending_events = []
    for event in events:
        if not event.get('approved') or event.get('pending_action'):
            review_event = dict(event)
            review_event['review_action'] = event.get('pending_action') or 'add'
            if review_event['review_action'] == 'edit':
                changes = event.get('pending_changes') or {}
                review_event['pending_diff'] = [
                    {
                        'label': event_field_labels[field],
                        'before': format_event_review_value(
                            field, get_event_schedule(event) if field == 'schedule' else event.get(field)
                        ),
                        'after': format_event_review_value(field, value),
                    }
                    for field, value in changes.items() if value != event.get(field)
                ]
                review_event.update(changes)
            pending_events.append(review_event)
    pending_events.sort(
        key=lambda event: min((occurrence['date'], occurrence['start_time']) for occurrence in get_event_schedule(event))
    )
    published_events = sorted(
        (event for event in events if event.get('approved') and get_event_schedule(event)),
        key=lambda event: min((occurrence['date'], occurrence['start_time']) for occurrence in get_event_schedule(event)),
    )
    return render_template(
        'admin.html', admin_sections=admin_sections, query=query,
        pending_events=pending_events, published_events=published_events,
        get_event_schedule=get_event_schedule,
    )


@app.route('/admin/events/<event_id>/approve', methods=['POST'])
@requires_auth
def approve_event(event_id):
    event = next((item for item in load_events() if item['id'] == event_id), None)
    if event is not None:
        action = event.get('pending_action')
        if action == 'delete':
            delete_event(event)
        elif action == 'edit':
            updated = {**event, **event.get('pending_changes', {})}
            updated.pop('pending_changes', None)
            updated.pop('pending_action', None)
            if is_cosmos_configured() and updated['community'] != event['community']:
                update_event(updated)
                delete_event(event)
            else:
                update_event(updated)
        elif not event.get('approved'):
            event['approved'] = True
            update_event(event)
        else:
            return Response('No pending event change to approve.', status=409)
    return redirect(url_for('admin'))


@app.route('/admin/events/<event_id>/reject', methods=['POST'])
@requires_auth
def reject_event(event_id):
    event = next((item for item in load_events() if item['id'] == event_id), None)
    if event is not None:
        if not event.get('approved'):
            delete_event(event)
        elif event.get('pending_action') in ('edit', 'delete'):
            event.pop('pending_changes', None)
            event.pop('pending_action', None)
            update_event(event)
        else:
            return Response('No pending event change to reject.', status=409)
    return redirect(url_for('admin'))


@app.route('/admin/listing/<listing_id>/delete', methods=['POST'])
@requires_auth
def admin_delete_listing(listing_id):
    listings = load_listings()
    listing = next((item for item in listings if str(item.get('id')) == str(listing_id)), None)
    if listing is not None:
        delete_listing_record(listings, listing)
    return redirect(url_for('admin'))


@app.route('/admin/listing/<listing_id>/feature/<scope>', methods=['POST'])
@requires_auth
def toggle_listing_feature(listing_id, scope):
    feature_fields = {
        'homepage': 'homepagefeatured',
        'community': 'communitypagefeatured',
    }
    field = feature_fields.get(scope)
    if not field:
        return redirect(url_for('admin'))

    listings = load_listings()
    for item in listings:
        if str(item.get('id')) == str(listing_id):
            item[field] = not bool(item.get(field, False))
            save_listings(listings)
            break
    return redirect(url_for('admin'))


@app.route('/admin/approve/<listing_id>', methods=['POST'])
@requires_auth
def approve_listing(listing_id):
    listings = load_listings()
    for item in listings:
        if str(item.get('id')) == str(listing_id):
            if item.get('pending_action', 'add') == 'delete':
                delete_listing_record(listings, item)
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
