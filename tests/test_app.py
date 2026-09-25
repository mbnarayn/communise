import os
import unittest
from unittest.mock import patch

from app import app, get_seed_data, normalize_listing, save_listings


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

    def test_home_page_shows_only_featured_listings_and_all_communities(self):
        save_listings([
            *get_seed_data(),
            {
                'id': 99,
                'name': 'Hidden Listing',
                'category': 'Other',
                'description': 'This should not appear on the homepage.',
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
        self.assertIn(b'Bedford', response.data)
        self.assertIn(b'Buckingham', response.data)
        self.assertIn(b'Featured listings', response.data)
        self.assertNotIn(b'Hidden Listing', response.data)

    def test_mk_community_route_shows_milton_keynes_listings(self):
        response = self.client.get('/mk')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Milton Keynes', response.data)
        self.assertIn(b'Maple Cafe', response.data)

    def test_bedford_community_route_shows_bedford_listings(self):
        response = self.client.get('/bedford')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Bedford', response.data)
        self.assertIn(b'Bedford Market Hall', response.data)

    def test_can_submit_listing(self):
        response = self.client.post('/add', data={
            'name': 'Corner Market Pending Test',
            'category': 'Shop',
            'description': 'Fresh produce and essentials',
            'address': '12 Maple Ave',
            'phone': '555-0101',
            'website': 'https://example.com'
        }, follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        public_response = self.client.get('/')
        self.assertNotIn(b'Corner Market Pending Test', public_response.data)

    def test_admin_can_approve_listing(self):
        self.client.post('/add', data={
            'name': 'Admin Approval Test Shop',
            'category': 'Shop',
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
            'category': 'Shop',
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
            'category': 'Shop',
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
                'category': 'Shop',
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
                'category': 'Shop',
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
            'category': 'Shop',
            'description': 'Fresh produce and local goods',
            'address': '89 Market Road',
            'phone_number': '555-1234',
            'website': 'https://example.com/extended',
            'email': 'hello@extendedshop.co.uk',
            'instagram': '@extendedshop',
            'facebook': 'Extended Shop',
            'whatsapp_group': 'https://chat.whatsapp.com/example',
            'community': 'bedford',
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

    def test_search_filters_listings(self):
        response = self.client.get('/?q=pharmacy')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Oak Pharmacy', response.data)
        self.assertNotIn(b'Maple Cafe', response.data)


if __name__ == '__main__':
    unittest.main()
