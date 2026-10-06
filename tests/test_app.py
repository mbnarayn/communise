import io
import json
import os
from pathlib import Path
from datetime import date, timedelta
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from app import app, filter_listings, get_seed_data, normalize_listing, save_listings


class AppTests(unittest.TestCase):
    def setUp(self):
        save_listings(get_seed_data())
        self.client = app.test_client()

    def test_listing_ids_are_normalized_to_strings(self):
        item = normalize_listing({'id': 42, 'name': 'Demo'})
        self.assertEqual(item['id'], '42')
        self.assertIsInstance(item['id'], str)

    @patch.dict(os.environ, {
        'COSMOS_ENDPOINT': 'https://example.documents.azure.com:443/',
        'COSMOS_KEY': 'test-key',
        'COSMOS_DATABASE': 'local-directory',
        'COSMOS_CONTAINER': 'listings'
    }, clear=False)
    def test_cosmos_configuration_detected(self):
        from app import is_cosmos_configured
        self.assertTrue(is_cosmos_configured())

    def test_home_page_loads(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Communise', response.data)
        self.assertIn(b'<nav class="site-navigation">', response.data)
        header = response.data.split(b'</header>', 1)[0]
        self.assertNotIn(b'Upcoming Events', header)
        self.assertIn(b'class="about-nav-link" href="/about">About Communise</a>', header)
        self.assertNotIn(b'class="hero-about-link"', response.data)
        self.assertIn(b'class="install-communise-button" data-install-communise', response.data)
        self.assertNotIn(b'data-install-communise hidden', response.data)
        self.assertIn(b'/static/android-logo.svg', response.data)
        self.assertIn(b'/static/apple-logo.svg', response.data)
        self.assertIn(b'/static/windows-logo.svg', response.data)
        self.assertNotIn(b'>Android<', response.data)
        self.assertNotIn(b'>iPhone<', response.data)
        self.assertIn(b'Add Communise to Home Screen', response.data)
        self.assertLess(
            response.data.index(b'Add Communise to Home Screen'),
            response.data.index(b'class="install-device-pair"'),
        )
        self.assertLess(response.data.index(b'>Add Your Listing</a>'), response.data.index(b'data-install-communise'))
        self.assertIn(b'<div class="hero-install-row">', response.data)

    def test_home_page_share_image_uses_absolute_url(self):
        response = self.client.get('/', base_url='https://communise.xyz')
        image_url = b'https://communise.xyz/static/communise-share-small.png'
        self.assertIn(b'<meta property="og:image" content="' + image_url + b'" />', response.data)
        self.assertIn(b'<meta property="og:image:alt" content="Communise logo" />', response.data)
        self.assertIn(b'<meta name="twitter:image" content="' + image_url + b'" />', response.data)
        self.assertIn(b'<img src="/static/communise_logo.png" alt="Communise logo" />', response.data)
        image_response = self.client.get('/static/communise-share-small.png')
        self.assertEqual(image_response.status_code, 200)
        self.assertEqual(image_response.mimetype, 'image/png')
        original_image = (Path(app.static_folder) / 'communise_logo.png').read_bytes()
        self.assertTrue(image_response.data.startswith(b'\x89PNG\r\n\x1a\n'))
        self.assertEqual(image_response.data[16:24], original_image[16:24])
        image_response.close()

    def test_home_hero_events_button_is_centered_below_primary_actions(self):
        response = self.client.get('/')
        self.assertIn(
            b'class="hero-cta hero-event-cta" href="/events">View Upcoming Events</a>',
            response.data,
        )
        self.assertNotIn(b'Browse Local Deals', response.data)
        event_description = b'Find local events, activities, and things to do in your community.'
        self.assertIn(b'class="hero-events-description">' + event_description, response.data)
        self.assertLess(response.data.index(event_description), response.data.index(b'class="hero-event-action"'))
        self.assertLess(response.data.index(b'class="hero-actions"'), response.data.index(event_description))
        self.assertNotIn(b'class="hero-event-preview"', response.data)

    def test_listing_count_shows_current_page_and_filtered_total(self):
        base_listing = dict(get_seed_data()[0])
        listings = [
            {**base_listing, 'id': str(index + 1), 'name': f'Featured Listing {index + 1}'}
            for index in range(23)
        ]

        with patch('app.load_listings', return_value=listings):
            for path in ('/', '/mk'):
                for page, visible_count in ((1, 16), (2, 7)):
                    with self.subTest(path=path, page=page):
                        response = self.client.get(f'{path}?page={page}')
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(
                            f'Showing {visible_count} of 23 listings'.encode(),
                            response.data,
                        )
                        top_controls = response.data.split(
                            b'<div class="listing-pagination-row listing-top-pagination">', 1
                        )[1].split(b'</div>', 1)[0]
                        self.assertLess(
                            response.data.index(b'class="listing-pagination-row listing-top-pagination"'),
                            response.data.index(b'<section class="listing-grid"'),
                        )
                        bottom_controls = response.data.split(
                            b'<div class="listing-pagination-row listing-bottom-pagination">', 1
                        )[1].split(b'</div>', 1)[0]
                        self.assertIn(f'Page {page} of 2'.encode(), top_controls)
                        self.assertIn(f'Page {page} of 2'.encode(), bottom_controls)
                        self.assertEqual(
                            response.data.count(f'Showing {visible_count} of 23 listings'.encode()),
                            2,
                        )
                        if page < 2:
                            self.assertIn(b'>Next</a>', top_controls)
                            self.assertIn(b'>Next</a>', bottom_controls)
                        else:
                            self.assertNotIn(b'>Next</a>', top_controls)
                            self.assertNotIn(b'>Next</a>', bottom_controls)

    def test_upcoming_events_link_is_not_in_page_headers(self):
        for path in ('/', '/mk', '/events', '/events/add', '/add', '/listing/1', '/about', '/terms'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                header = response.data.split(b'</header>', 1)[0]
                self.assertIn(b'<span class="site-nav-links">', header)
                self.assertLess(header.index(b'>Woking</a>'), header.index(b'</span>'))
                self.assertNotIn(b'class="events-nav-link"', header)
                self.assertIn(b'class="about-nav-link" href="/about">About Communise</a>', header)

        admin = self.client.get('/admin', headers={'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'})
        self.assertNotIn(b'class="events-nav-link"', admin.data.split(b'</header>', 1)[0])

    def test_pwa_metadata_and_icons_are_available(self):
        page_paths = ('/', '/about', '/terms', '/add', '/listing/1', '/mk')
        for path in page_paths:
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertIn(b'rel="manifest" href="/static/site.webmanifest"', response.data)
                response.close()

        manifest_response = self.client.get('/static/site.webmanifest')
        self.assertEqual(manifest_response.status_code, 200)
        self.assertIn(manifest_response.mimetype, ('application/manifest+json', 'application/json'))
        manifest = json.loads(manifest_response.get_data(as_text=True))
        self.assertEqual(manifest['name'], 'Communise')
        self.assertEqual(manifest['display'], 'standalone')
        manifest_response.close()
        for icon in manifest['icons']:
            icon_response = self.client.get(f"/static/{icon['src']}")
            self.assertEqual(icon_response.status_code, 200)
            self.assertTrue(icon_response.data.startswith(b'\x89PNG\r\n\x1a\n'))
            icon_response.close()

    def test_about_link_uses_title_case_in_header(self):
        response = self.client.get('/mk')
        self.assertEqual(response.status_code, 200)
        header = response.data.split(b'</header>', 1)[0]
        self.assertIn(b'class="about-nav-link" href="/about">About Communise</a>', header)

    def test_about_page_includes_purpose_sections_before_contact(self):
        response = self.client.get('/about')
        self.assertEqual(response.status_code, 200)
        name_heading_index = response.data.index(b'<h3>The Name Communise</h3>')
        name_paragraph_index = response.data.index(b'The name <strong>Communise</strong> combines the words <strong>Community</strong> and <strong>Advertise</strong>')
        xyz_heading_index = response.data.index(b'<h3>Why the .xyz Domain</h3>')
        purpose_index = response.data.index(b'<h2>Purpose</h2>')
        why_index = response.data.index(b'<h2>Why Communise</h2>')
        local_information_index = response.data.index(b'Communise makes local information easier to find')
        problem_index = response.data.index(b'<h3>The Problem Communise Solves</h3>')
        contact_index = response.data.index(b'<h2>Contact Us</h2>')
        self.assertLess(name_heading_index, name_paragraph_index)
        self.assertLess(name_paragraph_index, xyz_heading_index)
        self.assertLess(xyz_heading_index, purpose_index)
        self.assertLess(purpose_index, why_index)
        self.assertLess(why_index, local_information_index)
        self.assertLess(local_information_index, problem_index)
        self.assertLess(why_index, contact_index)
        self.assertIn(b'The Problem Communise Solves', response.data)
        self.assertIn(b'the businesses and services that matter most to them.', response.data)
        self.assertIn(b'href="/terms">Terms of Use</a>', response.data)
        self.assertIn(b'approval or featuring is not an endorsement', response.data)

    def test_terms_page_clarifies_third_party_listing_responsibility(self):
        response = self.client.get('/terms')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<h1>Terms of Use</h1>', response.data)
        self.assertIn(b'Communise does not endorse or guarantee', response.data)
        self.assertIn(b'Please verify details directly with the provider', response.data)
        self.assertNotIn(b'approved, displayed, or featured', response.data)

    def test_shared_footer_links_appear_on_site_pages(self):
        for path in ('/', '/about', '/terms', '/add', '/listing/1', '/mk'):
            with self.subTest(path=path):
                response = self.client.get(path)
                self.assertEqual(response.status_code, 200)
                self.assertIn(b'<a href="/about">More About Communise</a>', response.data)
                self.assertIn(b'<a href="/terms">Terms of Use</a>', response.data)
                self.assertIn(b'<a href="/add">Add Your Listing</a>', response.data)
                self.assertIn(b'<a href="/events/add">Add an Event</a>', response.data)
                self.assertIn(b'data-install-communise', response.data)
                self.assertIn(b'<div class="container site-footer-install">', response.data)
                footer_html = response.data.split(b'<footer class="site-footer">', 1)[1]
                footer_link_positions = [
                    footer_html.index(b'<a href="/add">Add Your Listing</a>'),
                    footer_html.index(b'<a href="/events">Upcoming Events</a>'),
                    footer_html.index(b'<a href="/events/add">Add an Event</a>'),
                    footer_html.index(b'<a href="/about">More About Communise</a>'),
                    footer_html.index(b'<a href="/terms">Terms of Use</a>'),
                ]
                self.assertEqual(footer_link_positions, sorted(footer_link_positions))
                self.assertLess(
                    footer_link_positions[0],
                    footer_html.index(b'data-install-communise'),
                )

        admin_response = self.client.get('/admin', headers={
            'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l',
        })
        self.assertEqual(admin_response.status_code, 200)
        self.assertIn(b'<nav class="admin-home-nav">', admin_response.data)
        self.assertIn(b'class="admin-search-input"', admin_response.data)
        self.assertIn(b'<a href="/about">More About Communise</a>', admin_response.data)
        self.assertIn(b'<a href="/terms">Terms of Use</a>', admin_response.data)
        self.assertIn(b'<a href="/add">Add Your Listing</a>', admin_response.data)
        self.assertIn(b'<a href="/events/add">Add an Event</a>', admin_response.data)

    def test_education_category_is_available_on_add_listing_form(self):
        response = self.client.get('/add')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Education', response.data)
        self.assertIn(b'Tutors, Training Providers', response.data)

    def test_community_dropdown_always_includes_supported_communities(self):
        save_listings([{
            'id': 1,
            'name': 'Milton Keynes Listing',
            'category': 'Shopping',
            'community': 'miltonkeynes',
            'approved': True,
        }])

        response = self.client.get('/add')
        self.assertEqual(response.status_code, 200)
        for slug, label in (
            (b'value="miltonkeynes"', b'Milton Keynes'),
            (b'value="buckingham"', b'Buckingham'),
            (b'value="woking"', b'Woking'),
        ):
            self.assertIn(slug, response.data)
            self.assertIn(label, response.data)

    def test_daily_opening_hours_are_stored_as_periods(self):
        self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Daily Hours Test',
            'category': 'Education',
            'description': 'A tutor with daily hours.',
            'address': 'Hours Lane',
            'opening_monday_1_open': '09:00',
            'opening_monday_1_close': '17:00',
            'opening_thursday_1_open': '09:00',
            'opening_thursday_1_close': '12:00',
            'opening_thursday_2_open': '13:00',
            'opening_thursday_2_close': '18:00',
        })

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Daily Hours Test')
        self.assertEqual(listing['opening_hours']['monday'][0], {'open': '09:00', 'close': '17:00'})
        self.assertEqual(len(listing['opening_hours']['thursday']), 2)

    def test_home_page_prioritizes_featured_listings_and_shows_all_communities(self):
        save_listings([
            *get_seed_data(),
            {
                'id': 99,
                'name': 'Hidden Listing',
                'category': 'Other',
                'description': 'This should appear after featured listings.',
                'address': '1 Hidden Lane',
                'phone': '555-0000',
                'website': 'https://example.com/hidden',
                'community': 'miltonkeynes',
                'approved': True,
                'homepagefeatured': False,
                'communitypagefeatured': True,
            }
        ])

        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Woking', response.data)
        self.assertIn(b'Buckingham', response.data)
        self.assertIn(b'Supporting Local Communities Through Community Advertising', response.data)
        self.assertNotIn(b'Used this listing', response.data)
        self.assertIn(b'Viewed 0 times', response.data)
        self.assertIn(b'Hidden Listing', response.data)
        self.assertLess(response.data.index(b'Maple Cafe'), response.data.index(b'Hidden Listing'))

    def test_home_page_has_social_preview_metadata(self):
        response = self.client.get('/')
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b'property="og:title" content="Communise - Connecting Local Communities"',
            response.data,
        )
        self.assertIn(
            b'name="description" content="Communise - Connecting Local Communities and Supporting Local Communities Through Community Advertising"',
            response.data,
        )

    def test_non_featured_listing_order_is_deterministic(self):
        listings = [
            {'id': 'featured', 'name': 'Featured', 'approved': True, 'homepagefeatured': True},
            {'id': 'first', 'name': 'First', 'approved': True, 'homepagefeatured': False},
            {'id': 'second', 'name': 'Second', 'approved': True, 'homepagefeatured': False},
            {'id': 'third', 'name': 'Third', 'approved': True, 'homepagefeatured': False},
        ]

        first_order = [item['id'] for item in filter_listings(listings, featured_field='homepagefeatured')]
        second_order = [item['id'] for item in filter_listings(listings, featured_field='homepagefeatured')]

        self.assertEqual(first_order, second_order)
        self.assertEqual(first_order[0], 'featured')
        self.assertCountEqual(first_order, ['featured', 'first', 'second', 'third'])

    def test_mk_community_route_shows_milton_keynes_listings(self):
        response = self.client.get('/mk')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Milton Keynes', response.data)
        self.assertIn(b'Maple Cafe', response.data)

    def test_woking_community_route_shows_woking_listings(self):
        response = self.client.get('/woking')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Woking', response.data)
        self.assertIn(b'Woking Market Hall', response.data)

    def test_only_community_name_category_and_description_are_required(self):
        response = self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Minimal Required Fields Shop',
            'category': 'Shopping',
            'description': 'A listing without an address.',
        })
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Minimal Required Fields Shop')
        self.assertEqual(listing.get('address'), '')

        missing_description = self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Missing Description Shop',
            'category': 'Shopping',
        })
        self.assertEqual(missing_description.status_code, 200)
        self.assertIn(b'Please provide a community, business name, valid category, and description.', missing_description.data)

        missing_community = self.client.post('/add', data={
            'name': 'Missing Community Shop',
            'category': 'Shopping',
            'description': 'A listing with no community.',
        })
        self.assertEqual(missing_community.status_code, 200)
        self.assertIn(b'Please provide a community, business name, valid category, and description.', missing_community.data)

        oversized_description = self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Long Description Shop',
            'category': 'Shopping',
            'description': 'x' * 151,
        })
        self.assertEqual(oversized_description.status_code, 200)
        self.assertIn(b'Description must be 150 characters or fewer.', oversized_description.data)

    def test_listing_name_only_allows_letters_and_spaces_up_to_40_characters(self):
        valid_name = 'Café ' + ('A' * 35)
        valid_response = self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': valid_name,
            'category': 'Shopping',
            'description': 'Valid name length.',
        })
        self.assertEqual(valid_response.status_code, 302)

        for invalid_name in ('Shop 2!', 'A' * 41):
            with self.subTest(name=invalid_name):
                invalid_response = self.client.post('/add', data={
                    'community': 'miltonkeynes',
                    'name': invalid_name,
                    'category': 'Shopping',
                    'description': 'Invalid name.',
                })
                self.assertEqual(invalid_response.status_code, 200)
                self.assertIn(b'Name must contain letters and spaces only and be 40 characters or fewer.', invalid_response.data)

        edit_response = self.client.post('/listing/1/edit', data={
            'community': 'miltonkeynes',
            'name': 'Shop 2!',
            'category': 'Food',
            'description': 'Invalid edit name.',
        })
        self.assertEqual(edit_response.status_code, 200)
        self.assertIn(b'Name must contain letters and spaces only and be 40 characters or fewer.', edit_response.data)

    def test_listing_form_orders_and_marks_fields(self):
        response = self.client.get('/add')
        self.assertEqual(response.status_code, 200)
        for field in (b'name="community"', b'name="name"', b'name="description"', b'name="category"'):
            self.assertIn(field, response.data)
        field_positions = [
            response.data.index(b'name="community"'),
            response.data.index(b'name="name"'),
            response.data.index(b'name="description"'),
            response.data.index(b'name="category"'),
        ]
        self.assertEqual(field_positions, sorted(field_positions))
        self.assertIn(b'maxlength="40"', response.data)
        self.assertIn(b'id="name-character-count" aria-live="polite">0 / 40 characters', response.data)
        self.assertIn(b"nameInput.addEventListener('input', updateNameCharacterCount)", response.data)
        self.assertIn(b'maxlength="150"', response.data)
        self.assertIn(b'placeholder="https://share.google/..."', response.data)
        self.assertIn(b'placeholder="20 Bobbin Road, Whitehouse, Milton Keynes, MK8 1EP"', response.data)
        self.assertIn(b'>Required</span>', response.data)
        self.assertIn(b'>Optional</span>', response.data)
        for icon in (
            b'field-icon-community', b'field-icon-name', b'field-icon-description',
            b'field-icon-category', b'field-icon-logo', b'field-icon-details',
            b'field-icon-phone', b'field-icon-subcommunity', b'field-icon-address',
            b'field-icon-website', b'field-icon-email', b'field-icon-instagram',
            b'field-icon-whatsapp', b'field-icon-facebook', b'field-icon-google',
            b'field-icon-hours', b'field-icon-offers',
        ):
            self.assertIn(icon, response.data)
        optional_field_names = [
            b'name="logo"',
            b'name="additional_information"',
            b'name="phone_number"',
            b'name="sub_community"',
            b'name="address"',
            b'name="instagram"',
            b'name="whatsapp_group"',
            b'name="facebook"',
            b'name="google_maps_location"',
            b'name="google_business_profile"',
            b'name="opening_monday_1_open"',
            b'name="deals"',
        ]
        optional_field_positions = [response.data.index(field) for field in optional_field_names]
        self.assertEqual(optional_field_positions, sorted(optional_field_positions))
        self.assertIn(b'id="description-character-count" aria-live="polite">0 / 150 characters', response.data)
        self.assertIn(b"descriptionInput.addEventListener('input', updateDescriptionCharacterCount)", response.data)
        self.assertIn(b'descriptionInput.style.height = `${descriptionInput.scrollHeight}px`', response.data)

        edit_response = self.client.get('/listing/1/edit')
        description_length = len(get_seed_data()[0]['description'])
        self.assertIn(b'10 / 40 characters', edit_response.data)
        self.assertIn(f'{description_length} / 150 characters'.encode(), edit_response.data)

    def test_can_submit_listing(self):
        response = self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Corner Market Pending Test',
            'category': 'Shopping',
            'description': 'Fresh produce and essentials',
            'address': '12 Maple Ave',
            'phone': '555-0101',
            'website': 'https://example.com'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        public_response = self.client.get('/')
        self.assertNotIn(b'Corner Market Pending Test', public_response.data)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Corner Market Pending Test')
        self.assertFalse(listing.get('homepagefeatured'))
        self.assertFalse(listing.get('communitypagefeatured'))

    def test_local_logo_upload_is_saved_and_referenced(self):
        response = self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Logo Upload Test Shop',
            'category': 'Shopping',
            'description': 'A listing with a local logo.',
            'address': '12 Logo Lane',
            'email': 'hello@logo-shop.example',
            'instagram': '@logo_shop',
            'facebook': 'Logo Shop',
            'whatsapp_group': 'https://chat.whatsapp.com/logo-shop',
            'sub_community': 'Town Centre',
            'opening_monday_1_open': '09:00',
            'opening_monday_1_close': '17:00',
            'opening_tuesday_1_open': '09:00',
            'opening_tuesday_1_close': '17:00',
            'opening_wednesday_1_open': '09:00',
            'opening_wednesday_1_close': '17:00',
            'opening_thursday_1_open': '09:00',
            'opening_thursday_1_close': '17:00',
            'opening_friday_1_open': '09:00',
            'opening_friday_1_close': '17:00',
            'additional_information': 'Accessible entrance.',
            'deals': '10% off this week.',
            'logo': (io.BytesIO(b'fake-png-content'), 'logo.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Logo Upload Test Shop')
        logo_url = listing.get('logo_url', '')
        self.assertTrue(logo_url.startswith('/static/uploads/logos/'))
        self.assertEqual(listing.get('opening_hours', {}).get('monday'), [
            {'open': '09:00', 'close': '17:00'},
        ])
        self.assertEqual(listing.get('opening_hours', {}).get('friday'), [
            {'open': '09:00', 'close': '17:00'},
        ])

        admin_response = self.client.get('/admin', headers={
            'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l',
        })
        for value in (logo_url, 'hello@logo-shop.example', '@logo_shop',
                      'Logo Shop', 'Town Centre', '09:00', '17:00',
                      'Accessible entrance.', '10% off this week.'):
            self.assertIn(value.encode(), admin_response.data)

        logo_path = Path(__file__).resolve().parents[1] / logo_url.lstrip('/')
        self.assertTrue(logo_path.is_file())
        logo_path.unlink()
        if not any(logo_path.parent.iterdir()):
            logo_path.parent.rmdir()

    def test_admin_can_approve_listing(self):
        self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Admin Approval Test Shop',
            'category': 'Shopping',
            'description': 'Fresh produce and essentials',
            'address': '99 Approval Lane',
            'phone': '555-0199',
            'website': 'https://example.com'
        }, follow_redirects=True)

        from app import load_listings
        pending_listing = next(item for item in load_listings() if item.get('name') == 'Admin Approval Test Shop')
        listing_id = pending_listing['id']

        auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}

        admin_response = self.client.get('/admin', headers=auth_headers)
        self.assertEqual(admin_response.status_code, 200)
        self.assertIn(b'Admin Approval Test Shop', admin_response.data)

        approve_response = self.client.post(f'/admin/approve/{listing_id}', headers=auth_headers)
        self.assertEqual(approve_response.status_code, 302)

        public_response = self.client.get('/')
        self.assertIn(b'Admin Approval Test Shop', public_response.data)

    def test_admin_shows_only_pending_listings_and_supports_search(self):
        auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}
        response = self.client.get('/admin', headers=auth_headers)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(b'Maple Cafe', response.data)

        self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Pending Search Listing',
            'category': 'Education',
            'description': 'A pending tutor listing',
            'address': 'Search Lane',
        })
        response = self.client.get('/admin?q=tutor', headers=auth_headers)
        self.assertIn(b'Pending Search Listing', response.data)

        response = self.client.get('/admin?q=Maple', headers=auth_headers)
        self.assertIn(b'Maple Cafe', response.data)

    def test_contact_button_tracks_usage(self):
        self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Contact Count Test Shop',
            'category': 'Shopping',
            'description': 'Fresh produce and essentials',
            'address': '55 Contact Road',
            'phone': '555-0109',
            'website': 'https://example.com/contact-test'
        }, follow_redirects=True)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Contact Count Test Shop')
        auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}
        self.client.post(f"/admin/approve/{listing['id']}", headers=auth_headers)

        response = self.client.post(f"/listing/{listing['id']}/contact", follow_redirects=True)
        self.assertEqual(response.status_code, 200)

        updated = next(item for item in load_listings() if item.get('name') == 'Contact Count Test Shop')
        self.assertEqual(updated.get('usage_count', 0), 1)

    def test_contact_click_is_only_counted_once_per_session(self):
        self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Single Session Count Test Shop',
            'category': 'Shopping',
            'description': 'Fresh produce and essentials',
            'address': '42 Session Road',
            'phone': '555-0118',
            'website': 'https://example.com/session-test'
        }, follow_redirects=True)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Single Session Count Test Shop')
        auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}
        self.client.post(f"/admin/approve/{listing['id']}", headers=auth_headers)

        self.client.post(f"/listing/{listing['id']}/contact", follow_redirects=True)
        self.client.post(f"/listing/{listing['id']}/contact", follow_redirects=True)

        updated = next(item for item in load_listings() if item.get('name') == 'Single Session Count Test Shop')
        self.assertEqual(updated.get('usage_count', 0), 1)

    def test_listing_feature_configuration_is_independent_per_page(self):
        from app import get_listing_feature_config

        home_features = get_listing_feature_config('home')
        community_features = get_listing_feature_config('community')

        self.assertIsInstance(home_features, dict)
        self.assertIsInstance(community_features, dict)
        self.assertIn('community', home_features)
        self.assertIn('community', community_features)
        self.assertIn('sub_community', home_features)
        self.assertIn('sub_community', community_features)
        self.assertIn('usage_counter', home_features)
        self.assertIn('usage_counter', community_features)
        self.assertFalse(home_features.get('phone', True))
        self.assertFalse(community_features.get('phone', True))
        self.assertFalse(community_features.get('website', True))

    def test_home_and_community_visibility_use_independent_flags(self):
        save_listings([
            {
                'id': 100,
                'name': 'Home Only Listing',
                'category': 'Shopping',
                'description': 'Visible on the homepage only.',
                'address': '1 Home Lane',
                'community': 'miltonkeynes',
                'approved': True,
                'homepagefeatured': True,
                'communitypagefeatured': False,
            },
            {
                'id': 101,
                'name': 'Community Only Listing',
                'category': 'Shopping',
                'description': 'Visible on the community page only.',
                'address': '2 Community Lane',
                'community': 'miltonkeynes',
                'approved': True,
                'homepagefeatured': False,
                'communitypagefeatured': True,
            },
        ])

        home_response = self.client.get('/')
        self.assertIn(b'Home Only Listing', home_response.data)
        self.assertIn(b'Community Only Listing', home_response.data)
        self.assertLess(
            home_response.data.index(b'Home Only Listing'),
            home_response.data.index(b'Community Only Listing'),
        )

        community_response = self.client.get('/mk')
        self.assertIn(b'Community Only Listing', community_response.data)
        self.assertIn(b'Home Only Listing', community_response.data)
        self.assertLess(
            community_response.data.index(b'Community Only Listing'),
            community_response.data.index(b'Home Only Listing'),
        )

    def test_listing_tiles_show_community_and_optional_subcommunity_instead_of_address(self):
        save_listings([
            {
                'id': 201,
                'name': 'Tile Location Shop',
                'category': 'Shopping',
                'description': 'Location display test.',
                'address': '20 Bobbin Road',
                'phone': '555-0100',
                'website': 'https://example.com/tile-shop',
                'community': 'miltonkeynes',
                'sub_community': 'Whitehouse',
                'approved': True,
                'homepagefeatured': True,
                'communitypagefeatured': True,
            },
            {
                'id': 202,
                'name': 'Community Only Tile Shop',
                'category': 'Shopping',
                'description': 'No subcommunity supplied.',
                'address': 'Other Road',
                'community': 'woking',
                'approved': True,
                'homepagefeatured': True,
                'communitypagefeatured': True,
            },
        ])

        response = self.client.get('/')
        self.assertIn(b'class="tag">Milton Keynes</div>', response.data)
        self.assertIn(b'class="tag">Whitehouse</div>', response.data)
        self.assertIn(b'class="tag">Woking</div>', response.data)
        self.assertNotIn(b'<strong>Community:</strong>', response.data)
        self.assertNotIn(b'<strong>Subcommunity:</strong>', response.data)
        self.assertNotIn(b'<strong>Address:</strong>', response.data)
        location_index = response.data.index(b'<div class="listing-location-tags">')
        description_index = response.data.index(b'<p>Location display test.</p>')
        self.assertGreater(location_index, description_index)
        self.assertIn(b"/listing/tilelocationshop", response.data)
        slug_detail_response = self.client.get('/listing/tilelocationshop')
        self.assertEqual(slug_detail_response.status_code, 200)
        self.assertIn(b'Tile Location Shop', slug_detail_response.data)
        legacy_id_response = self.client.get('/listing/201')
        self.assertEqual(legacy_id_response.status_code, 200)
        community_only_card = response.data.split(b'Community Only Tile Shop', 1)[1].split(b'</article>', 1)[0]
        self.assertNotIn(b'class="tag"></div>', community_only_card)

        community_response = self.client.get('/mk')
        self.assertIn(b'class="tag">Milton Keynes</div>', community_response.data)
        self.assertIn(b'class="tag">Whitehouse</div>', community_response.data)
        community_location_card = next(
            fragment.split(b'</article>', 1)[0]
            for fragment in community_response.data.split(b'<article')
            if b'<h3>Tile Location Shop</h3>' in fragment
        )
        self.assertNotIn(b'Phone:', community_location_card)
        self.assertNotIn(b'Website:', community_location_card)

    def test_duplicate_listing_slugs_include_listing_id(self):
        from app import get_listing_slugs

        slugs = get_listing_slugs([
            {'id': '1', 'name': 'Coffee Shop'},
            {'id': '2', 'name': 'CoffeeShop'},
        ])
        self.assertEqual(slugs, {'1': 'coffeeshop-1', '2': 'coffeeshop-2'})

    def test_duplicate_event_slugs_include_event_id(self):
        from app import get_event_slugs

        slugs = get_event_slugs([
            {'id': '1', 'name': 'Community Fair'},
            {'id': '2', 'name': 'communityfair'},
        ])
        self.assertEqual(slugs, {'1': 'communityfair-1', '2': 'communityfair-2'})

    def test_add_listing_stores_extended_business_fields(self):
        response = self.client.post('/add', data={
            'name': 'Extended Profile Shop',
            'category': 'Shopping',
            'description': 'Fresh produce and local goods',
            'address': '89 Market Road',
            'phone_number': '555-1234',
            'website': 'https://example.com/extended',
            'email': 'hello@extendedshop.co.uk',
            'instagram': '@extendedshop',
            'facebook': 'Extended Shop',
            'google_maps_location': 'https://maps.google.com/?q=extended-shop',
            'google_business_profile': 'https://maps.app.goo.gl/extended-shop',
            'whatsapp_group': 'https://chat.whatsapp.com/example',
            'community': 'woking',
            'sub_community': 'Town Centre',
            'opening_monday_1_open': '09:00',
            'opening_monday_1_close': '17:00',
            'opening_tuesday_1_open': '09:00',
            'opening_tuesday_1_close': '17:00',
            'opening_wednesday_1_open': '09:00',
            'opening_wednesday_1_close': '17:00',
            'opening_thursday_1_open': '09:00',
            'opening_thursday_1_close': '17:00',
            'opening_friday_1_open': '09:00',
            'opening_friday_1_close': '17:00',
            'opening_saturday_1_open': '09:00',
            'opening_saturday_1_close': '17:00',
            'additional_information': 'Family-owned local business',
            'deals': '10% off this week',
        }, follow_redirects=True)

        self.assertEqual(response.status_code, 200)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Extended Profile Shop')
        self.assertEqual(listing.get('phone'), '555-1234')
        self.assertEqual(listing.get('email'), 'hello@extendedshop.co.uk')
        self.assertEqual(listing.get('instagram'), '@extendedshop')
        self.assertEqual(listing.get('facebook'), 'Extended Shop')
        self.assertEqual(listing.get('google_maps_location'), 'https://maps.google.com/?q=extended-shop')
        self.assertEqual(listing.get('google_business_profile'), 'https://maps.app.goo.gl/extended-shop')
        self.assertEqual(listing.get('whatsapp_group'), 'https://chat.whatsapp.com/example')
        self.assertEqual(listing.get('sub_community'), 'Town Centre')
        self.assertEqual(listing.get('opening_hours', {}).get('monday'), [
            {'open': '09:00', 'close': '17:00'},
        ])
        self.assertEqual(listing.get('opening_hours', {}).get('saturday'), [
            {'open': '09:00', 'close': '17:00'},
        ])
        self.assertEqual(listing.get('additional_information'), 'Family-owned local business')
        self.assertEqual(listing.get('deals'), '10% off this week')

    def test_instagram_label_and_handle_guidance(self):
        form_response = self.client.get('/add')
        self.assertIn(b'Instagram ID', form_response.data)
        self.assertIn(b'placeholder="yourbusiness"', form_response.data)
        self.assertIn(b'Do NOT include the full Instagram URL', form_response.data)

        detail_response = self.client.get('/listing/6')
        self.assertIn(b'href="#field-icon-instagram"', detail_response.data)
        self.assertIn(b'thegrovecommunitymarket', detail_response.data)

    def test_facebook_and_google_business_profile_are_linked(self):
        self.client.post('/add', data={
            'community': 'miltonkeynes',
            'name': 'Link Test Shop',
            'category': 'Shopping',
            'description': 'A shop with profile links.',
            'address': '89 Market Road',
            'facebook': 'Link Test Shop',
            'google_maps_location': 'https://maps.google.com/?q=link-test',
            'google_business_profile': 'https://maps.app.goo.gl/link-test',
        })

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Link Test Shop')
        detail_response = self.client.get(f"/listing/{listing['id']}")
        self.assertIn(b'https://www.facebook.com/search/top/?q=Link%20Test%20Shop', detail_response.data)
        self.assertIn(b'field-icon-google', detail_response.data)
        self.assertIn(b'href="https://maps.google.com/?q=link-test"', detail_response.data)
        self.assertIn(b'href="https://maps.app.goo.gl/link-test"', detail_response.data)

    def test_listing_detail_page_shows_full_information(self):
        listing_id = 6
        response = self.client.get(f'/listing/{listing_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'The Grove Community Market', response.data)
        self.assertIn(b'hello@thegrovecommunitymarket.example', response.data)
        self.assertIn(b'@thegrovecommunitymarket', response.data)
        self.assertIn(b'Thu-Sun 9am-4pm', response.data)
        self.assertIn(b'10% off selected stalls on market day.', response.data)
        for icon in (
            b'field-icon-community', b'field-icon-name', b'field-icon-description',
            b'field-icon-category', b'field-icon-address', b'field-icon-phone',
            b'field-icon-email', b'field-icon-website', b'field-icon-instagram',
            b'field-icon-facebook', b'field-icon-whatsapp', b'field-icon-subcommunity',
            b'field-icon-hours', b'field-icon-details', b'field-icon-offers',
        ):
            self.assertIn(icon, response.data)

    def test_listing_share_metadata_uses_small_logo_for_id_and_slug_links(self):
        listing = {**get_seed_data()[0], 'name': 'JRDA', 'description': 'Classes & community activities.'}
        image_url = b'https://communise.xyz/static/communise-share-small.png'
        with patch('app.load_listings', return_value=[listing]), patch('app.save_listings'):
            for path in (f"/listing/{listing['id']}", '/listing/jrda'):
                with self.subTest(path=path):
                    response = self.client.get(path, base_url='https://communise.xyz')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b'<meta property="og:title" content="JRDA | Communise" />', response.data)
                    self.assertIn(
                        b'<meta property="og:description" content="Classes &amp; community activities." />',
                        response.data,
                    )
                    self.assertIn(
                        f'<meta property="og:url" content="https://communise.xyz{path}" />'.encode(),
                        response.data,
                    )
                    self.assertIn(b'<meta property="og:image" content="' + image_url + b'" />', response.data)
                    self.assertIn(b'<meta name="twitter:image" content="' + image_url + b'" />', response.data)

    def test_listing_more_details_preserves_whitespace_and_escapes_html(self):
        details = 'First paragraph.\n\nSecond paragraph.\n  Indented line.\n<script>alert("test")</script>'
        listing = {**get_seed_data()[0], 'additional_information': details}
        with patch('app.load_listings', return_value=[listing]), patch('app.save_listings'):
            response = self.client.get(f"/listing/{listing['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertIn(
            b'<p class="detail-additional-information">First paragraph.\n\nSecond paragraph.\n  Indented line.\n&lt;script&gt;',
            response.data,
        )
        self.assertNotIn(b'<script>alert(', response.data)
        stylesheet = (Path(app.static_folder) / 'styles.css').read_text(encoding='utf-8')
        self.assertRegex(stylesheet, r'\.detail-additional-information\s*\{\s*white-space:\s*pre-wrap;\s*\}')
        self.assertRegex(stylesheet, r'\.detail-callout\s*\{[^}]*background:\s*#fff;')
        self.assertRegex(
            stylesheet,
            r'\.detail-description,\s*\.detail-callout \.detail-additional-information\s*\{'
            r'\s*font-size:\s*0\.76rem;\s*color:\s*var\(--muted\);\s*line-height:\s*1\.45;\s*\}',
        )

    def test_logo_fallback_uses_first_two_initials_and_stable_color(self):
        from app import listing_fallback_color, listing_initials

        self.assertEqual(listing_initials('The Happy Little Bakery'), 'TH')
        color = listing_fallback_color('listing-6')
        self.assertEqual(color, listing_fallback_color('listing-6'))
        self.assertRegex(color, r'^#[0-9a-f]{6}$')

        card = self.client.get('/')
        self.assertIn(b'class="listing-thumb listing-logo-fallback"', card.data)
        self.assertIn(b'>TG</div>', card.data)
        detail = self.client.get('/listing/6')
        self.assertIn(b'class="detail-logo listing-logo-fallback"', detail.data)
        self.assertIn(b'>TG</div>', detail.data)

    def test_listing_detail_page_shows_listing_image(self):
        response = self.client.get('/listing/1')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<div class="detail-layout">', response.data)
        self.assertLess(response.data.index(b'class="detail-media"'), response.data.index(b'class="detail-content"'))
        self.assertIn(b'photo-1501339847302-ac426a4a7cbb', response.data)

    def test_listing_can_be_edited_and_returns_to_admin_review(self):
        edit_page = self.client.get('/listing/1/edit')
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b'Maple Cafe', edit_page.data)
        self.assertIn(b'value="555-0142"', edit_page.data)

        response = self.client.post('/listing/1/edit', data={
            'community': 'miltonkeynes',
            'name': 'Updated Maple Cafe',
            'category': 'Food',
            'description': 'Updated description.',
            'address': '99 New Maple Street',
            'phone_number': '555-0999',
            'google_business_profile': 'https://maps.app.goo.gl/updated-maple',
        })
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('id') == '1')
        self.assertEqual(listing.get('name'), 'Maple Cafe')
        self.assertEqual(listing.get('address'), '15 Maple Street')
        self.assertTrue(listing.get('approved'))
        self.assertEqual(listing.get('pending_action'), 'edit')
        self.assertEqual(listing['pending_changes'].get('name'), 'Updated Maple Cafe')
        self.assertEqual(listing['pending_changes'].get('google_business_profile'), 'https://maps.app.goo.gl/updated-maple')

        public_response = self.client.get('/')
        self.assertIn(b'Maple Cafe', public_response.data)
        self.assertNotIn(b'Updated Maple Cafe', public_response.data)

        admin_response = self.client.get('/admin', headers={
            'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l',
        })
        self.assertIn(b'Edit Listing', admin_response.data)
        self.assertIn(b'Changes in this edit', admin_response.data)
        self.assertIn(b'Before:', admin_response.data)
        self.assertIn(b'After:', admin_response.data)

    def test_listing_delete_requires_review_before_removal(self):
        response = self.client.post('/listing/1/delete')
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('id') == '1')
        self.assertEqual(listing.get('pending_action'), 'delete')
        self.assertTrue(listing.get('approved'))

        public_response = self.client.get('/')
        self.assertIn(b'Maple Cafe', public_response.data)

        auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}
        admin_response = self.client.get('/admin', headers=auth_headers)
        self.assertIn(b'Delete Listing', admin_response.data)

        self.client.post('/admin/approve/1', headers=auth_headers)
        self.assertFalse(any(item.get('id') == '1' for item in load_listings()))

    @patch('app.get_cosmos_container')
    @patch('app.is_cosmos_configured', return_value=True)
    def test_cosmos_listing_delete_uses_id_and_category_partition_key(self, cosmos_configured, get_container):
        container = get_container.return_value
        from app import delete_listing_record

        listing = {'id': '42', 'category': 'Education'}
        delete_listing_record([listing], listing)

        container.delete_item.assert_called_once_with(item='42', partition_key='Education')

    def test_admin_can_edit_directly_and_toggle_featured_state(self):
        auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}
        edit_page = self.client.get('/listing/1/edit?admin=1', headers=auth_headers)
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b'Edit Listing (Admin)', edit_page.data)

        response = self.client.post('/listing/1/edit?admin=1', data={
            'community': 'miltonkeynes',
            'name': 'Admin Updated Maple Cafe',
            'category': 'Food',
            'description': 'Updated directly by admin.',
            'address': '1 Admin Lane',
        }, headers=auth_headers)
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('id') == '1')
        self.assertEqual(listing.get('name'), 'Admin Updated Maple Cafe')
        self.assertTrue(listing.get('approved'))
        self.assertEqual(listing.get('pending_action'), '')

        self.client.post('/admin/listing/1/feature/homepage', headers=auth_headers)
        listing = next(item for item in load_listings() if item.get('id') == '1')
        self.assertFalse(listing.get('homepagefeatured'))

    def test_listing_detail_view_increments_usage_each_time(self):
        from app import load_listings

        self.client.get('/listing/6')
        self.client.get('/listing/6')

        listing = next(item for item in load_listings() if item.get('id') == '6')
        self.assertEqual(listing.get('usage_count', 0), 1)

    def test_search_filters_listings(self):
        response = self.client.get('/?q=pharmacy')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Oak Pharmacy', response.data)
        self.assertNotIn(b'Maple Cafe', response.data)

    def test_search_matches_more_details_on_home_and_community_pages(self):
        matching = {
            **get_seed_data()[0],
            'additional_information': 'Pottery workshops available on request.',
        }
        pending = {**matching, 'id': 'pending', 'name': 'Pending Workshop', 'approved': False}
        unrelated = {**matching, 'id': 'unrelated', 'name': 'Other Shop', 'additional_information': ''}
        with patch('app.load_listings', return_value=[matching, pending, unrelated]):
            for path in ('/', '/mk'):
                with self.subTest(path=path):
                    response = self.client.get(f'{path}?q=PoTtErY')
                    self.assertEqual(response.status_code, 200)
                    self.assertIn(b'<h3>Maple Cafe</h3>', response.data)
                    self.assertIn(b'Showing 1 of 1 listings', response.data)
                    self.assertNotIn(b'<h3>Pending Workshop</h3>', response.data)
                    self.assertNotIn(b'<h3>Other Shop</h3>', response.data)


class EventTests(unittest.TestCase):
    def setUp(self):
        temporary_directory = TemporaryDirectory()
        self.addCleanup(temporary_directory.cleanup)
        event_file = str(Path(temporary_directory.name) / 'events.json')
        event_file_patch = patch('app.EVENT_DATA_FILE', event_file)
        event_file_patch.start()
        self.addCleanup(event_file_patch.stop)
        self.client = app.test_client()
        self.event_date = (date.today() + timedelta(days=7)).isoformat()
        self.auth_headers = {'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l'}

    def submit_event(self, **overrides):
        data = {
            'name': 'Local Fair', 'description': 'A local community fair.',
            'community': 'buckingham', 'date[]': [self.event_date],
            'start_time[]': ['10:30'], 'end_time[]': ['12:30'],
            'venue': 'Town Hall',
        }
        data.update(overrides)
        return self.client.post('/events/add', data=data)

    def test_add_event_button_precedes_date_order_heading(self):
        response = self.client.get('/events')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'<section class="hero">', response.data)
        hero = response.data.split(b'<section class="hero">', 1)[1].split(b'</section>', 1)[0]
        self.assertIn(b'<h1>Find local events, activities, and things to do in your community.</h1>', hero)
        self.assertNotIn(b'Supporting Local Communities Through Community Advertising', hero)
        self.assertNotIn(b'Discover, share, and support local businesses and services', hero)
        self.assertNotIn(b'View Upcoming Events', hero)
        self.assertNotIn(b'hero-events-description', hero)
        self.assertIn(b'Upcoming Events by Date', response.data)
        self.assertLess(response.data.index(b'>Add an Event</a>'), response.data.index(b'Upcoming Events by Date'))
        self.assertLess(response.data.index(b'aria-label="Filter events by location"'), response.data.index(b'Upcoming Events by Date'))
        self.assertLess(response.data.index(b'Upcoming Events by Date'), response.data.index(b'id="events-list"') if b'id="events-list"' in response.data else response.data.index(b'No upcoming events'))

    def test_events_are_paginated_with_counts_and_preserve_filters(self):
        events = [
            {
                'id': str(index),
                'name': f'Community Event {index:02}',
                'description': 'A local event.',
                'community': 'buckingham',
                'approved': True,
                'schedule': [{
                    'date': (date.today() + timedelta(days=index + 1)).isoformat(),
                    'start_time': '10:00',
                    'end_time': '11:00',
                }],
            }
            for index in range(17)
        ]

        with patch('app.load_events', return_value=events):
            first_page = self.client.get('/events?community=buckingham&q=community')
            self.assertEqual(first_page.data.count(b'<article class="card event-card">'), 16)
            self.assertEqual(first_page.data.count(b'Showing 16 of 17 events'), 2)
            self.assertIn(b'Page 1 of 2', first_page.data)
            self.assertIn(
                b'href="/events?community=buckingham&amp;q=community&amp;page=2">Next</a>',
                first_page.data,
            )

            last_page = self.client.get('/events?community=buckingham&q=community&page=2')
            self.assertEqual(last_page.data.count(b'<article class="card event-card">'), 1)
            self.assertEqual(last_page.data.count(b'Showing 1 of 17 events'), 2)
            self.assertIn(b'Page 2 of 2', last_page.data)
            self.assertNotIn(b'>Next</a>', last_page.data)

    def test_events_require_admin_approval_and_filter_by_community(self):
        from app import load_events

        response = self.submit_event()
        self.assertEqual(response.status_code, 302)
        self.assertNotIn(b'Local Fair', self.client.get('/events').data)
        event = load_events()[0]
        self.assertEqual(self.client.get(f"/events/{event['id']}").status_code, 404)
        self.assertFalse(event['approved'])
        self.assertEqual(event['schedule'], [
            {'date': self.event_date, 'start_time': '10:30', 'end_time': '12:30'},
        ])
        self.assertEqual(self.client.post(f"/admin/events/{event['id']}/approve").status_code, 401)
        admin_page = self.client.get('/admin', headers=self.auth_headers)
        self.assertIn(b'Local Fair', admin_page.data)
        self.assertIn(b'Approve Event', admin_page.data)
        self.assertEqual(self.client.post(f"/admin/events/{event['id']}/approve", headers=self.auth_headers).status_code, 302)

        events_page = self.client.get('/events')
        self.assertIn(b'href="/events/localfair"', events_page.data)
        self.assertEqual(self.client.get('/events/localfair').status_code, 200)
        self.assertIn(b'Local Fair', self.client.get('/events?community=buckingham').data)
        self.assertNotIn(b'Local Fair', self.client.get('/events?community=woking').data)
        self.assertIn(b'Local Fair', self.client.get('/events').data)
        self.assertIn(b'Town Hall', self.client.get(f"/events/{event['id']}").data)

    def test_event_edit_remains_private_until_admin_approves(self):
        from app import load_events

        self.submit_event()
        event_id = load_events()[0]['id']
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)

        edit_page = self.client.get(f'/events/{event_id}/edit')
        self.assertEqual(edit_page.status_code, 200)
        self.assertIn(b'Local Fair', edit_page.data)
        self.assertIn(f'action="/events/{event_id}/edit"'.encode(), edit_page.data)
        self.assertIn(b'Submit Changes for Review', edit_page.data)
        initial_detail = self.client.get(f'/events/{event_id}')
        self.assertIn(f'href="/events/{event_id}/edit">Edit Event</a>'.encode(), initial_detail.data)
        self.assertIn(f'action="/events/{event_id}/delete"'.encode(), initial_detail.data)
        invalid_edit = self.client.post(f'/events/{event_id}/edit', data={
            'name': 'Invalid Fair', 'description': 'Missing venue', 'community': 'buckingham',
            'date[]': [self.event_date], 'start_time[]': ['10:30'], 'end_time[]': ['12:30'],
        })
        self.assertEqual(invalid_edit.status_code, 400)
        self.assertNotIn('pending_action', load_events()[0])
        changed_date = (date.today() + timedelta(days=9)).isoformat()
        changed = self.client.post(f'/events/{event_id}/edit', data={
            'name': 'Updated Local Fair', 'description': 'Revised event details',
            'community': 'woking', 'venue': 'New Hall',
            'date[]': [changed_date], 'start_time[]': ['14:00'], 'end_time[]': ['16:00'],
            'details_url': 'https://example.com/new-tickets',
        })
        self.assertEqual(changed.status_code, 302)
        stored = load_events()[0]
        self.assertEqual(stored['name'], 'Local Fair')
        self.assertEqual(stored['community'], 'buckingham')
        self.assertEqual(stored['pending_action'], 'edit')
        self.assertEqual(stored['pending_changes']['name'], 'Updated Local Fair')
        self.assertIn(b'Local Fair', self.client.get(f'/events/{event_id}').data)
        self.assertIn(b'change awaiting admin review', self.client.get(f'/events/{event_id}').data)
        self.assertIn(b'Local Fair', self.client.get('/events?community=buckingham').data)
        self.assertNotIn(b'Updated Local Fair', self.client.get('/events').data)
        self.assertEqual(self.client.post(f'/events/{event_id}/edit', data={}).status_code, 409)
        self.assertEqual(self.client.post(f'/events/{event_id}/delete').status_code, 409)

        review = self.client.get('/admin', headers=self.auth_headers)
        self.assertIn(b'Updated Local Fair', review.data)
        self.assertIn(b'Edit Event', review.data)
        self.assertIn(b'<b>Before:</b> Local Fair', review.data)
        self.assertIn(b'<b>After:</b> Updated Local Fair', review.data)
        self.assertIn(f'{date.fromisoformat(changed_date):%d/%m/%Y}: 14:00 - 16:00'.encode(), review.data)
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)
        updated = load_events()[0]
        self.assertEqual(updated['name'], 'Updated Local Fair')
        self.assertEqual(updated['community'], 'woking')
        self.assertNotIn('pending_changes', updated)
        self.assertIn(b'Updated Local Fair', self.client.get('/events?community=woking').data)
        self.assertNotIn(b'Updated Local Fair', self.client.get('/events?community=buckingham').data)

    def test_event_edit_rejection_keeps_public_event_and_delete_needs_approval(self):
        from app import load_events

        self.submit_event()
        event_id = load_events()[0]['id']
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)
        self.assertEqual(self.client.post(f'/admin/events/{event_id}/reject', headers=self.auth_headers).status_code, 409)
        self.submit_event(name='Another Pending Fair')
        pending_id = load_events()[1]['id']
        self.assertEqual(self.client.post(f'/events/{pending_id}/delete').status_code, 404)

        self.submit_event(name='Yet Another Pending Fair')
        self.assertEqual(self.client.post(f'/events/{event_id}/edit', data={
            'name': 'Changed Fair', 'description': 'Revised', 'community': 'buckingham',
            'venue': 'Town Hall', 'date[]': [self.event_date],
            'start_time[]': ['10:30'], 'end_time[]': ['12:30'],
        }).status_code, 302)
        self.client.post(f'/admin/events/{event_id}/reject', headers=self.auth_headers)
        self.assertEqual(load_events()[0]['name'], 'Local Fair')
        self.assertNotIn('pending_action', load_events()[0])

        response = self.client.post(f'/events/{event_id}/delete')
        self.assertEqual(response.status_code, 302)
        self.assertEqual(load_events()[0]['pending_action'], 'delete')
        self.assertIn(b'Local Fair', self.client.get('/events').data)
        review = self.client.get('/admin', headers=self.auth_headers)
        self.assertIn(b'Delete Event', review.data)
        self.client.post(f'/admin/events/{event_id}/reject', headers=self.auth_headers)
        self.assertIn(b'Local Fair', self.client.get('/events').data)
        self.client.post(f'/events/{event_id}/delete')
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)
        self.assertFalse(any(item['id'] == event_id for item in load_events()))
        self.assertEqual(self.client.get(f'/events/{event_id}').status_code, 404)

    @patch('app.is_cosmos_configured', return_value=True)
    @patch('app.get_events_container')
    @patch('app.load_events')
    def test_approving_event_community_edit_moves_cosmos_partition(self, load_events, get_container, _configured):
        event = {
            'id': 'event-one', 'community': 'buckingham', 'approved': True,
            'pending_action': 'edit', 'pending_changes': {'community': 'woking'},
        }
        load_events.return_value = [event]

        response = self.client.post('/admin/events/event-one/approve', headers=self.auth_headers)
        self.assertEqual(response.status_code, 302)
        updated = get_container.return_value.upsert_item.call_args.args[0]
        self.assertEqual(updated['community'], 'woking')
        self.assertNotIn('pending_action', updated)
        get_container.return_value.delete_item.assert_called_once_with(
            item='event-one', partition_key='buckingham',
        )

    def test_event_details_count_once_per_session(self):
        from app import load_events

        self.submit_event()
        event_id = load_events()[0]['id']
        self.assertEqual(self.client.get(f'/events/{event_id}').status_code, 404)
        self.assertEqual(load_events()[0]['usage_count'], 0)
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)

        self.client.get(f'/events/{event_id}')
        self.client.get(f'/events/{event_id}')
        self.assertEqual(load_events()[0]['usage_count'], 1)

        another_visitor = app.test_client()
        another_visitor.get(f'/events/{event_id}')
        self.assertEqual(load_events()[0]['usage_count'], 2)

    def test_event_attendance_counts_one_choice_per_session_and_allows_switching(self):
        from app import load_events

        self.submit_event()
        event_id = load_events()[0]['id']
        vote_url = f'/events/{event_id}/attendance'
        self.assertEqual(self.client.post(vote_url, data={'attendance': 'going'}).status_code, 404)
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)
        self.assertEqual(self.client.post(vote_url, data={'attendance': 'invalid'}).status_code, 400)

        data = {'attendance': 'going', 'community': 'buckingham', 'q': 'Local'}
        first = self.client.post(vote_url, data=data)
        self.assertEqual(first.status_code, 302)
        self.assertIn('community=buckingham', first.location)
        self.assertIn('q=Local', first.location)
        self.client.post(vote_url, data=data)
        self.assertEqual(load_events()[0]['going_count'], 1)
        self.assertEqual(load_events()[0]['not_going_count'], 0)
        tile = self.client.get('/events?community=buckingham&q=Local')
        self.assertIn(b'Going 1</button>', tile.data)
        self.assertIn(b'Not Going 0</button>', tile.data)
        self.assertIn(b'name="q" value="Local"', tile.data)
        tile_actions = tile.data.split(b'<div class="card-actions event-card-actions">', 1)[1].split(b'</article>', 1)[0]
        self.assertLess(tile_actions.index(b'View details'), tile_actions.index(b'Going 1</button>'))
        self.assertLess(tile_actions.index(b'Going 1</button>'), tile_actions.index(b'Not Going 0</button>'))
        self.assertLess(tile_actions.index(b'Not Going 0</button>'), tile_actions.index(b'Viewed 0 times'))

        switched = self.client.post(vote_url, data={'attendance': 'not_going', 'source': 'detail'})
        self.assertEqual(switched.location, f'/events/{event_id}')
        self.assertEqual(load_events()[0]['going_count'], 0)
        self.assertEqual(load_events()[0]['not_going_count'], 1)
        details = self.client.get(f'/events/{event_id}')
        self.assertIn(b'Not Going 1</button>', details.data)
        self.assertIn(b'event-attendance-not_going" aria-pressed="true"', details.data)

        another_visitor = app.test_client()
        another_visitor.post(vote_url, data={'attendance': 'going'})
        self.assertEqual(load_events()[0]['going_count'], 1)
        self.assertEqual(load_events()[0]['not_going_count'], 1)

    def test_other_is_available_for_events_without_changing_listing_communities(self):
        from app import load_events

        form = self.client.get('/events/add')
        self.assertIn(b'<option value="other"', form.data)
        self.assertIn(b'>Other</option>', form.data)
        self.assertNotIn(b'<option value="other"', self.client.get('/add').data)

        response = self.submit_event(community='other', name='Other Area Fair')
        self.assertEqual(response.status_code, 302)
        event = load_events()[0]
        self.assertEqual(event['community'], 'other')
        self.assertNotIn(b'Other Area Fair', self.client.get('/events?community=other').data)
        self.client.post(f"/admin/events/{event['id']}/approve", headers=self.auth_headers)
        filtered = self.client.get('/events?community=other')
        self.assertEqual(filtered.status_code, 200)
        self.assertIn(b'Other Area Fair', filtered.data)
        self.assertIn(b'class="tag">Other</span>', filtered.data)
        self.assertIn(b'href="/events?community=other"', filtered.data)
        self.assertNotIn(b'Other Area Fair', self.client.get('/events?community=woking').data)

    def test_event_search_filters_upcoming_approved_events_by_text_and_location(self):
        from app import load_events

        self.submit_event(name='Autumn Craft Fair', description='Handmade gifts')
        event_id = load_events()[0]['id']
        self.assertNotIn(b'Autumn Craft Fair', self.client.get('/events?q=craft').data)
        self.client.post(f'/admin/events/{event_id}/approve', headers=self.auth_headers)
        self.submit_event(name='Garden Concert', description='Outdoor music', community='woking')
        second_id = load_events()[1]['id']
        self.client.post(f'/admin/events/{second_id}/approve', headers=self.auth_headers)

        response = self.client.get('/events?community=buckingham&q=CrAfT')
        self.assertIn(b'Autumn Craft Fair', response.data)
        self.assertNotIn(b'Garden Concert', response.data)
        self.assertIn(b'class="search-form hero-search events-search"', response.data)
        self.assertIn(b'name="community" value="buckingham"', response.data)
        self.assertIn(b'name="q" value="CrAfT"', response.data)
        self.assertIn(b'href="/events?community=buckingham">Clear</a>', response.data)
        self.assertIn(b'community=woking&amp;q=CrAfT', response.data)
        self.assertIn(b'Autumn Craft Fair', self.client.get('/events?q=handmade').data)
        self.assertIn(b'Autumn Craft Fair', self.client.get('/events?q=town%20hall').data)
        self.assertIn(b'Autumn Craft Fair', self.client.get('/events?q=buckingham').data)
        self.assertIn(b'Autumn Craft Fair', self.client.get(f'/events?q={date.fromisoformat(self.event_date):%d/%m/%Y}').data)
        self.assertNotIn(b'Autumn Craft Fair', self.client.get('/events?q=concert').data)
        self.assertIn(b'No upcoming events match your search.', self.client.get('/events?q=unmatched').data)
        self.assertNotIn(b'>Clear</a>', self.client.get('/events').data)

    def test_events_reject_invalid_or_past_dates_and_can_be_removed(self):
        from app import load_events

        for data in ({'date[]': [(date.today() - timedelta(days=1)).isoformat()]},
                 {'date[]': ['invalid']}, {'start_time[]': ['later']},
                 {'end_time[]': ['09:00']}, {'end_time[]': []},
                     {'community': 'unknown'}, {'name': ''}, {'start_time[]': []},
                     {'venue': ''}, {'venue': '   '}):
            with self.subTest(data=data):
                self.assertEqual(self.submit_event(**data).status_code, 400)
        self.assertEqual(load_events(), [])

        self.submit_event()
        event_id = load_events()[0]['id']
        self.client.post(f'/admin/events/{event_id}/reject', headers=self.auth_headers)
        self.assertEqual(load_events(), [])

    def test_past_events_are_hidden_from_public_listing(self):
        from app import save_event

        save_event({
            'id': 'past', 'name': 'Old Fair', 'description': 'Already finished',
            'community': 'woking', 'date': (date.today() - timedelta(days=1)).isoformat(),
            'time': '10:30', 'venue': '', 'approved': True,
        })
        self.assertNotIn(b'Old Fair', self.client.get('/events').data)
        self.assertIn(b'Woking', self.client.get('/events/add').data)

        save_event({
            'id': 'mixed', 'name': 'Recurring Fair', 'description': 'Two event dates',
            'community': 'woking', 'venue': '', 'approved': True,
            'schedule': [
                {'date': (date.today() - timedelta(days=1)).isoformat(), 'start_time': '09:00', 'end_time': '10:00'},
                {'date': self.event_date, 'start_time': '11:00', 'end_time': '12:00'},
            ],
        })
        response = self.client.get('/events?community=woking')
        self.assertEqual(response.data.count(b'<h3>Recurring Fair</h3>'), 1)
        self.assertIn(b'11:00 - 12:00', response.data)
        self.assertNotIn(b'09:00 - 10:00', response.data)
        self.assertEqual(self.client.get('/events/past').status_code, 404)

    def test_multiple_dates_have_independent_times_and_appear_in_admin_review(self):
        from app import load_events

        later_date = (date.today() + timedelta(days=8)).isoformat()
        response = self.submit_event(**{
            'date[]': [self.event_date, later_date],
            'start_time[]': ['10:30', '18:00'],
            'end_time[]': ['12:30', '20:15'],
            'details_url': 'https://example.com/fair-tickets',
        })
        self.assertEqual(response.status_code, 302)
        event = load_events()[0]
        self.assertEqual(len(event['schedule']), 2)
        self.assertEqual(event['venue'], 'Town Hall')
        self.assertEqual(event['details_url'], 'https://example.com/fair-tickets')
        admin_response = self.client.get('/admin', headers=self.auth_headers)
        self.assertIn(b'Name: Local Fair', admin_response.data)
        self.assertIn(b'<strong>Community:</strong> buckingham', admin_response.data)
        self.assertIn(f'<strong>Date and Time:</strong> <time datetime="{self.event_date}">{date.fromisoformat(self.event_date):%d/%m/%Y}</time> 10:30 - 12:30'.encode(), admin_response.data)
        self.assertIn(f'<strong>Date and Time:</strong> <time datetime="{later_date}">{date.fromisoformat(later_date):%d/%m/%Y}</time> 18:00 - 20:15'.encode(), admin_response.data)
        self.assertIn(b'<strong>Address / Venue:</strong> Town Hall', admin_response.data)
        self.assertIn(b'<strong>Description:</strong> A local community fair.', admin_response.data)
        self.assertIn(b'>https://example.com/fair-tickets</a>', admin_response.data)

        self.client.post(f"/admin/events/{event['id']}/approve", headers=self.auth_headers)
        published_review = self.client.get('/admin', headers=self.auth_headers)
        self.assertIn(b'<h3>Name: Local Fair</h3>', published_review.data)
        self.assertIn(b'<strong>Date and Time:</strong>', published_review.data)
        public_response = self.client.get('/events?community=buckingham')
        self.assertEqual(public_response.data.count(b'<h3>Local Fair</h3>'), 2)
        self.assertIn(b'class="listing-grid events-grid"', public_response.data)
        self.assertIn(b'class="tag">Buckingham</span>', public_response.data)
        self.assertNotIn(b'24-hour', public_response.data)
        self.assertIn(date.fromisoformat(self.event_date).strftime('%d/%m/%Y').encode(), public_response.data)
        self.assertIn(b'10:30 - 12:30', public_response.data)
        self.assertIn(b'18:00 - 20:15', public_response.data)
        first_card = public_response.data.split(b'<h3>Local Fair</h3>', 1)[1].split(b'</article>', 1)[0]
        self.assertIn(
            f'<time datetime="{self.event_date}">{date.fromisoformat(self.event_date):%d/%m/%Y}</time> <span>10:30 - 12:30</span>'.encode(),
            first_card,
        )
        self.assertLess(first_card.index(b'class="listing-location-tags"'), first_card.index(b'class="card-actions event-card-actions"'))
        actions = first_card.split(b'<div class="card-actions event-card-actions">', 1)[1]
        self.assertLess(actions.index(b'View details'), actions.index(b'Viewed 0 times'))
        self.assertIn(b'class="details-cta"', actions)
        self.assertIn(b'href="/events/localfair"', public_response.data)
        self.assertNotIn(b'Town Hall', public_response.data)
        self.assertNotIn(b'href="https://example.com/fair-tickets"', public_response.data)
        self.client.post(f"/events/{event['id']}/attendance", data={'attendance': 'going'})
        voted_tiles = self.client.get('/events?community=buckingham')
        self.assertEqual(voted_tiles.data.count(b'Going 1</button>'), 2)

        details = self.client.get(f"/events/{event['id']}")
        self.assertEqual(details.status_code, 200)
        self.assertIn(b'<main class="container detail-page">', details.data)
        self.assertIn(b'<section class="detail-card">', details.data)
        self.assertIn(b'class="detail-grid"', details.data)
        self.assertIn(b'class="detail-item event-detail-dates"', details.data)
        self.assertIn(b'</use></svg>Date and Time</span>', details.data)
        self.assertIn(b'href="#field-icon-calendar"', details.data)
        updated_tiles = self.client.get('/events?community=buckingham')
        self.assertEqual(updated_tiles.data.count(b'Viewed 1 time'), 2)
        self.assertIn(b'Town Hall', details.data)
        self.assertIn(b'Buckingham', details.data)
        self.assertIn(b'href="https://example.com/fair-tickets" target="_blank" rel="noopener noreferrer">https://example.com/fair-tickets</a>', details.data)
        self.assertLess(details.data.index(b'<div class="event-attendance"'), details.data.index(b'>Back to Events</a>'))
        self.assertIn(b'18:00 - 20:15', details.data)
        self.assertNotIn(b'24-hour', details.data)

    def test_upcoming_event_rows_sort_nearest_date_first(self):
        from app import save_event

        late_date = (date.today() + timedelta(days=12)).isoformat()
        early_date = (date.today() + timedelta(days=2)).isoformat()
        save_event({
            'id': 'late', 'name': 'Later Fair', 'description': 'Coming later', 'venue': 'Hall',
            'community': 'woking', 'approved': True,
            'schedule': [{'date': late_date, 'start_time': '08:00', 'end_time': '09:00'}],
        })
        save_event({
            'id': 'early', 'name': 'Sooner Fair', 'description': 'Coming soon', 'venue': 'Town Hall',
            'community': 'woking', 'approved': True,
            'schedule': [{'date': early_date, 'start_time': '18:00', 'end_time': '19:00'}],
        })
        response = self.client.get('/events?community=woking')
        self.assertLess(response.data.index(b'Sooner Fair'), response.data.index(b'Later Fair'))
        self.assertIn(date.fromisoformat(early_date).strftime('%d/%m/%Y').encode(), response.data)
        self.assertIn(b'18:00 - 19:00', response.data)
        self.assertNotIn(b'Town Hall', response.data)

    def test_event_form_keeps_multiple_dates_after_invalid_submission(self):
        later_date = (date.today() + timedelta(days=8)).isoformat()
        response = self.submit_event(**{
            'date[]': [self.event_date, later_date],
            'start_time[]': ['10:30', '18:00'],
            'end_time[]': ['12:30', '17:00'],
        })
        self.assertEqual(response.status_code, 400)
        self.assertIn(b'Address / Venue', response.data)
        self.assertIn(b'data-add-event-date', response.data)
        self.assertIn(b'<strong>Event happening over multiple days?</strong>', response.data)
        self.assertIn(b'Date and Time <span class="field-marker required">Required</span>', response.data)
        self.assertIn(b'href="#field-icon-calendar"', response.data)
        self.assertIn(b'href="#field-icon-hours"', response.data)
        self.assertLess(
            response.data.index(b'id="event-schedule-title"'),
            response.data.index(b'<fieldset class="event-schedule" aria-labelledby="event-schedule-title">'),
        )
        self.assertIn(b'field-icon-name', response.data)
        self.assertIn(b'field-icon-address', response.data)
        self.assertIn(f'value="{later_date}"'.encode(), response.data)
        self.assertIn(b'value="18:00"', response.data)
        self.assertEqual(response.data.split(b'<template id="event-date-template">')[0].count(b'data-remove-date'), 1)

    def test_event_url_validation_and_first_date_remove_button(self):
        form_response = self.client.get('/events/add')
        form_markup = form_response.data.split(b'<template id="event-date-template">')[0]
        self.assertIn(b'<button type="submit" class="primary-btn">Submit Event</button>', form_markup)
        self.assertNotIn(b'data-remove-date', form_markup)
        self.assertIn(b'name="venue"', form_markup)
        self.assertIn(b'name="details_url"', form_markup)
        self.assertIn(b'Event Details or Tickets Link', form_markup)
        self.assertIn(b'data-add-event-date', form_markup)
        self.assertIn(b'href="#field-icon-calendar"></use></svg>Date', form_markup)
        self.assertIn(b'href="#field-icon-hours"></use></svg>Start Time', form_markup)
        self.assertIn(b'href="#field-icon-hours"></use></svg>End Time', form_markup)
        self.assertIn(b'href="#field-icon-calendar"></use></svg>Date', form_response.data.split(b'<template id="event-date-template">')[1])

        for url in ('javascript:alert(1)', 'https://[broken'):
            with self.subTest(url=url):
                response = self.submit_event(details_url=url)
                self.assertEqual(response.status_code, 400)
                self.assertIn(b'Enter a valid http:// or https:// event link.', response.data)
        from app import load_events
        self.assertEqual(load_events(), [])

    @patch.dict(os.environ, {
        'COSMOS_ENDPOINT': 'https://example.documents.azure.com:443/',
        'COSMOS_KEY': 'test-key',
        'COSMOS_DATABASE': 'local-directory',
        'COSMOS_CONTAINER': 'listings',
    })
    @patch('app.CosmosClient')
    def test_cosmos_events_use_separate_community_partition(self, cosmos_client):
        from app import PartitionKey, delete_event, get_events_container, load_events, save_event

        container = cosmos_client.return_value.get_database_client.return_value.create_container_if_not_exists.return_value
        get_events_container()
        cosmos_client.return_value.get_database_client.return_value.create_container_if_not_exists.assert_called_with(
            id='events', partition_key=PartitionKey(path='/community'),
        )

        container.query_items.return_value = []
        self.assertEqual(load_events('woking'), [])
        container.query_items.assert_called_with(
            query='SELECT * FROM c WHERE c.community = @community',
            parameters=[{'name': '@community', 'value': 'woking'}],
            partition_key='woking',
        )
        event = {'id': 'event-one', 'community': 'woking'}
        save_event(event)
        container.upsert_item.assert_called_with(event)
        delete_event(event)
        container.delete_item.assert_called_with(item='event-one', partition_key='woking')


if __name__ == '__main__':
    unittest.main()
