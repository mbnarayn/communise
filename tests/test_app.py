import io
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
        self.assertIn(b'Listings across all of Communise', response.data)
        self.assertNotIn(b'Used this listing', response.data)
        self.assertIn(b'Viewed 0 times', response.data)
        self.assertIn(b'Hidden Listing', response.data)
        self.assertLess(response.data.index(b'Maple Cafe'), response.data.index(b'Hidden Listing'))

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

    def test_can_submit_listing(self):
        response = self.client.post('/add', data={
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

    def test_local_logo_upload_is_saved_and_referenced(self):
        response = self.client.post('/add', data={
            'name': 'Logo Upload Test Shop',
            'category': 'Shopping',
            'description': 'A listing with a local logo.',
            'address': '12 Logo Lane',
            'email': 'hello@logo-shop.example',
            'instagram': '@logo_shop',
            'facebook': 'Logo Shop',
            'whatsapp_group': 'https://chat.whatsapp.com/logo-shop',
            'sub_community': 'Town Centre',
            'opening_hours': 'Mon-Fri 9am-5pm',
            'additional_information': 'Accessible entrance.',
            'deals': '10% off this week.',
            'logo': (io.BytesIO(b'fake-png-content'), 'logo.png'),
        }, content_type='multipart/form-data')
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('name') == 'Logo Upload Test Shop')
        logo_url = listing.get('logo_url', '')
        self.assertTrue(logo_url.startswith('/static/uploads/logos/'))

        admin_response = self.client.get('/admin', headers={
            'Authorization': 'Basic YWRtaW46Y2hhbmdlLW1l',
        })
        for value in (logo_url, 'hello@logo-shop.example', '@logo_shop',
                      'Logo Shop', 'Town Centre', 'Mon-Fri 9am-5pm',
                      'Accessible entrance.', '10% off this week.'):
            self.assertIn(value.encode(), admin_response.data)

        logo_path = Path(__file__).resolve().parents[1] / logo_url.lstrip('/')
        self.assertTrue(logo_path.is_file())
        logo_path.unlink()
        if not any(logo_path.parent.iterdir()):
            logo_path.parent.rmdir()

    def test_admin_can_approve_listing(self):
        self.client.post('/add', data={
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

    def test_contact_button_tracks_usage(self):
        self.client.post('/add', data={
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
        self.assertIn('address', home_features)
        self.assertIn('address', community_features)
        self.assertIn('usage_counter', home_features)
        self.assertIn('usage_counter', community_features)
        self.assertFalse(home_features.get('phone', True))
        self.assertTrue(community_features.get('phone', False))

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
        self.assertNotIn(b'Community Only Listing', home_response.data)

        community_response = self.client.get('/mk')
        self.assertIn(b'Community Only Listing', community_response.data)
        self.assertNotIn(b'Home Only Listing', community_response.data)

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
            'whatsapp_group': 'https://chat.whatsapp.com/example',
            'community': 'woking',
            'sub_community': 'Town Centre',
            'opening_hours': 'Mon-Sat 9am-5pm',
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
        self.assertEqual(listing.get('whatsapp_group'), 'https://chat.whatsapp.com/example')
        self.assertEqual(listing.get('sub_community'), 'Town Centre')
        self.assertEqual(listing.get('opening_hours'), 'Mon-Sat 9am-5pm')
        self.assertEqual(listing.get('additional_information'), 'Family-owned local business')
        self.assertEqual(listing.get('deals'), '10% off this week')

    def test_listing_detail_page_shows_full_information(self):
        listing_id = 6
        response = self.client.get(f'/listing/{listing_id}')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'The Grove Community Market', response.data)
        self.assertIn(b'hello@thegrovecommunitymarket.example', response.data)
        self.assertIn(b'@thegrovecommunitymarket', response.data)
        self.assertIn(b'Thu-Sun 9am-4pm', response.data)
        self.assertIn(b'10% off selected stalls on market day.', response.data)

    def test_listing_detail_page_shows_listing_image(self):
        response = self.client.get('/listing/1')
        self.assertEqual(response.status_code, 200)
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
        })
        self.assertEqual(response.status_code, 302)

        from app import load_listings
        listing = next(item for item in load_listings() if item.get('id') == '1')
        self.assertEqual(listing.get('name'), 'Maple Cafe')
        self.assertEqual(listing.get('address'), '15 Maple Street')
        self.assertTrue(listing.get('approved'))
        self.assertEqual(listing.get('pending_action'), 'edit')
        self.assertEqual(listing['pending_changes'].get('name'), 'Updated Maple Cafe')

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
