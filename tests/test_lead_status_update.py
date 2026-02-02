#!/usr/bin/env python3
"""
Unit tests for lead status update endpoint
Tests controller layer with mocked service
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
from unittest.mock import Mock
from flask import Flask, g
from backend.crm.controllers.crm_controller import CRMController


class TestLeadStatusUpdate(unittest.TestCase):
    """Test cases for update_lead_status controller method"""
    
    def setUp(self):
        """Set up test fixtures"""
        self.app = Flask(__name__)
        self.app.config['TESTING'] = True
        self.controller = CRMController()
        self.controller.crm_service = Mock()
    
    def test_update_status_success(self):
        """Test successful status update"""
        with self.app.test_request_context(json={'stage_id': 2}):
            # Arrange
            g.tenant_id = 1
            
            self.controller.crm_service.update_lead_status.return_value = {
                'success': True,
                'data': {'opportunity_id': 10, 'stage_id': 2},
                'message': 'Lead status updated successfully'
            }
            
            # Act
            response, status_code = self.controller.update_lead_status(10)
            
            # Assert
            self.assertEqual(status_code, 200)
            self.controller.crm_service.update_lead_status.assert_called_once_with(1, 10, 2)
            response_data = response.get_json()
            self.assertTrue(response_data['success'])
            self.assertEqual(response_data['data']['stage_id'], 2)
    
    def test_update_status_empty_body(self):
        """Test error when request body is empty dict - Flask behavior test"""
        with self.app.test_request_context(json={}):
            # Arrange - empty JSON body (Flask may treat as None)
            g.tenant_id = 1
            
            # Act
            response, status_code = self.controller.update_lead_status(10)
            
            # Assert
            self.assertEqual(status_code, 400)
            response_data = response.get_json()
            self.assertFalse(response_data['success'])
            # Flask test client returns None for {}, so we get "Request body is required"
            self.assertIn('required', response_data['message'])
    
    def test_update_status_missing_stage_id(self):
        """Test error when stage_id is missing from body"""
        with self.app.test_request_context(json={'other_field': 'value'}):
            # Arrange - body exists but stage_id is missing
            g.tenant_id = 1
            
            # Act
            response, status_code = self.controller.update_lead_status(10)
            
            # Assert
            self.assertEqual(status_code, 400)
            response_data = response.get_json()
            self.assertFalse(response_data['success'])
            self.assertIn('stage_id is required', response_data['message'])
    
    def test_update_status_invalid_stage_id(self):
        """Test error when stage_id is not a number"""
        with self.app.test_request_context(json={'stage_id': 'invalid'}):
            # Arrange
            g.tenant_id = 1
            
            # Act
            response, status_code = self.controller.update_lead_status(10)
            
            # Assert
            self.assertEqual(status_code, 400)
            response_data = response.get_json()
            self.assertFalse(response_data['success'])
            self.assertIn('stage_id must be a number', response_data['message'])
    
    def test_update_status_not_found(self):
        """Test 404 when lead not found or tenant mismatch"""
        with self.app.test_request_context(json={'stage_id': 2}):
            # Arrange
            g.tenant_id = 1
            
            self.controller.crm_service.update_lead_status.return_value = {
                'success': False,
                'error': 'Lead not found',
                'message': 'No lead found with ID 999 or access denied'
            }
            
            # Act
            response, status_code = self.controller.update_lead_status(999)
            
            # Assert
            self.assertEqual(status_code, 404)
            response_data = response.get_json()
            self.assertFalse(response_data['success'])
            self.assertIn('Lead not found', response_data['error'])
    
    def test_update_status_tenant_isolation(self):
        """Test that tenant_id from JWT is used for isolation"""
        with self.app.test_request_context(json={'stage_id': 3}):
            # Arrange
            g.tenant_id = 5  # Different tenant
            
            self.controller.crm_service.update_lead_status.return_value = {
                'success': False,
                'error': 'Lead not found',
                'message': 'No lead found with ID 10 or access denied'
            }
            
            # Act
            response, status_code = self.controller.update_lead_status(10)
            
            # Assert
            self.assertEqual(status_code, 404)
            # Verify tenant_id from JWT was passed to service
            self.controller.crm_service.update_lead_status.assert_called_once_with(5, 10, 3)


if __name__ == '__main__':
    # Run tests with verbose output
    unittest.main(verbosity=2)
