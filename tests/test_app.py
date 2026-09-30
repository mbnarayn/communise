import io
import json
import os
from pathlib import Path
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
        self.assertIn(b'class="hero-about-link" href="/about">More About Communise</a>', response.data)
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

    def test_community_hero_about_link_uses_title_case(self):
        response = self.client.get('/mk')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'class="hero-about-link" href="/about">More About Communise</a>', response.data)

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
                self.assertIn(b'data-install-communise', response.data)

        admin_response = self.client.get('/admin', headers={
            'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l',
        })
        self.assertEqual(admin_response.status_code, 200)
        self.assertIn(b'<a href="/about">More About Communise</a>', admin_response.data)
        self.assertIn(b'<a href="/terms">Terms of Use</a>', admin_response.data)
        self.assertIn(b'<a href="/add">Add Your Listing</a>', admin_response.data)

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


if __name__ == '__main__':
    unittest.main()
