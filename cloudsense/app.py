#!/usr/bin/env python3
"""CloudSense Flask Application with enhanced security, logging, and validation"""

import logging
import os
import json
import threading
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Any, Tuple, Union

from boto3 import Session
from botocore.exceptions import NoCredentialsError, ClientError
from flask import Flask, jsonify, request, render_template, abort, current_app
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

from .config.config import config
from . import __version__
from .utils.validators import (
    validate_days, validate_region, validate_date, validate_month,
    validate_budget_limit, sanitize_service_name, ValidationError
)
from .utils.helpers import (
    parse_date_params, normalize_service_name, get_original_service_name,
    categorize_ebs_usage, categorize_ebs_usage_improved, categorize_ec2_usage_improved,
    format_currency, calculate_daily_average, calculate_monthly_projection, is_global_service
)
from .utils.cache import cache_result, get_cache_stats, clear_cache, cleanup_expired_cache

# Configure logging
logger = logging.getLogger(__name__)

# Thread-safe session management
_local = threading.local()


class DecimalEncoder(json.JSONEncoder):
    """JSON encoder for Decimal objects"""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def get_aws_session():
    """Get thread-safe cached AWS session"""
    if not hasattr(_local, 'session'):
        _local.session = Session()
    return _local.session


def get_ce_client():
    """Get thread-safe cached Cost Explorer client
    
    Note: AWS Cost Explorer API only works from us-east-1 endpoint,
    regardless of the region being analyzed for cost data.
    """
    if not hasattr(_local, 'ce_client'):
        session = get_aws_session()
        # Cost Explorer API requires us-east-1 endpoint (AWS requirement)
        _local.ce_client = session.client('ce', region_name='us-east-1')
    return _local.ce_client


def check_aws_auth():
    """Check AWS authentication and log results"""
    try:
        caller_id = get_aws_session().client('sts').get_caller_identity()
        logger.debug(f"AWS authentication successful for account: {caller_id.get('Account', 'Unknown')}")
        return True
    except NoCredentialsError:
        logger.error("AWS credentials not found")
        return False
    except ClientError as e:
        logger.error(f"AWS authentication failed: {e}")
        return False
    except Exception as e:
        logger.error(f"Unexpected error during AWS authentication: {e}")
        return False


def require_auth():
    """Decorator to require AWS authentication"""
    if not check_aws_auth():
        abort(401)


def handle_validation_error(e: ValidationError) -> Tuple[Dict[str, str], int]:
    """Handle validation errors consistently"""
    logger.warning(f"Validation error: {e}")
    return jsonify({'error': str(e)}), 400


def handle_aws_error(e: Exception) -> Tuple[Dict[str, str], int]:
    """Handle AWS-related errors consistently"""
    if isinstance(e, NoCredentialsError):
        logger.error("AWS credentials not configured")
        return jsonify({'error': 'AWS credentials required. Run: aws configure'}), 401
    elif isinstance(e, ClientError):
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        error_message = e.response.get('Error', {}).get('Message', str(e))
        logger.error(f"AWS API error [{error_code}]: {error_message}")
        
        if error_code == 'UnauthorizedOperation':
            return jsonify({'error': 'AWS credentials lack Cost Explorer permissions'}), 403
        return jsonify({'error': f'AWS API error: {error_message}'}), 500
    else:
        logger.error(f"Unexpected AWS error: {e}")
        return jsonify({'error': 'AWS service error'}), 500


def create_app(config_name: str = None, hide_account: bool = False):
    """Create and configure the Flask application"""
    
    # Determine config
    config_name = config_name or os.getenv('FLASK_CONFIG', 'default')
    app_config = config.get(config_name, config['default'])
    
    # Create Flask app
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
    app = Flask(__name__, template_folder=template_dir, static_folder=static_dir)
    
    # Configure app
    app.config.from_object(app_config)
    app.config['HIDE_ACCOUNT'] = hide_account
    app.json_encoder = DecimalEncoder
    
    # Initialize configuration
    app_config.init_app(app)
    
    # Set up rate limiting
    limiter = Limiter(
        key_func=get_remote_address,
        default_limits=[app.config.get('RATELIMIT_DEFAULT', '100 per hour')],
        storage_uri=app.config.get('RATELIMIT_STORAGE_URL', 'memory://')
    )
    limiter.init_app(app)
    
    @app.after_request
    def add_security_headers(response):
        """Add security headers to all responses"""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
        return response
    
    @app.before_request
    def before_request():
        """Pre-request validation and logging"""
        if request.endpoint and request.endpoint.startswith('api.'):
            require_auth()
        
        # Log API requests (DEBUG level for routine requests)
        if request.path.startswith('/api/'):
            logger.debug(f"API request: {request.method} {request.path} from {request.remote_addr}")
    
    @app.errorhandler(ValidationError)
    def handle_validation_error_route(e):
        """Handle validation errors globally"""
        return handle_validation_error(e)
    
    @app.errorhandler(429)
    def handle_rate_limit(e):
        """Handle rate limit errors"""
        logger.warning(f"Rate limit exceeded for {request.remote_addr}: {request.path}")
        return jsonify({'error': 'Rate limit exceeded. Please try again later.'}), 429
    
    @app.errorhandler(500)
    def handle_server_error(e):
        """Handle internal server errors"""
        logger.error(f"Internal server error: {e}")
        return jsonify({'error': 'Internal server error'}), 500

    # Health check endpoint
    @app.route('/health')
    def health_check():
        """Health check endpoint for monitoring"""
        try:
            # Quick AWS credential check
            get_aws_session().client('sts').get_caller_identity()
            return jsonify({
                'status': 'healthy',
                'aws': 'connected',
                'timestamp': datetime.utcnow().isoformat(),
                'version': __version__
            }), 200
        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return jsonify({
                'status': 'unhealthy',
                'aws': 'disconnected',
                'error': str(e),
                'timestamp': datetime.utcnow().isoformat()
            }), 503
    
    # Main routes
    @app.route('/')
    def index():
        """Main dashboard page"""
        try:
            require_auth()
            return render_template('index.html', debug_mode=app.config.get('DEBUG', False))
        except Exception as e:
            logger.error(f"Error rendering index page: {e}")
            return "AWS credentials required", 401

    @app.route('/api/billing')
    @limiter.limit("30 per minute")
    def get_billing():
        """Get billing data with enhanced validation"""
        try:
            # Validate input parameters
            days = validate_days(request.args.get('days'))
            region = validate_region(request.args.get('region', 'all'))
            specific_date = validate_date(request.args.get('date'))
            month = validate_month(request.args.get('month'))
            
            logger.info(f"Fetching billing data: days={days}, region={region}, date={specific_date}, month={month}")
            
            data = get_cost_data(days, region, specific_date, month, app.config.get('HIDE_ACCOUNT', False))
            return jsonify(data)
            
        except ValidationError as e:
            return handle_validation_error(e)
        except (NoCredentialsError, ClientError) as e:
            return handle_aws_error(e)
        except Exception as e:
            logger.error(f"Unexpected error in get_billing: {e}")
            return jsonify({'error': 'Internal server error'}), 500

    @app.route('/api/regions')
    @limiter.limit("10 per minute")
    def get_regions():
        """Get available AWS regions"""
        try:
            data = get_available_regions()
            return jsonify(data)
        except Exception as e:
            logger.error(f"Error fetching regions: {e}")
            return jsonify({'error': 'Failed to fetch regions'}), 500

    @app.route('/api/service/<service_name>')
    @limiter.limit("60 per minute")
    def get_service_data(service_name):
        """Get cost data for a specific service"""
        try:
            # Sanitize service name
            service_name = sanitize_service_name(service_name)
            if not service_name:
                raise ValidationError("Invalid service name")
            
            days = validate_days(request.args.get('days'))
            specific_date = validate_date(request.args.get('date'))
            month = validate_month(request.args.get('month'))
            
            logger.info(f"Fetching service data for: {service_name}")
            
            data = get_service_cost_data(service_name, days, specific_date, month)
            return jsonify(data)
            
        except ValidationError as e:
            return handle_validation_error(e)
        except (NoCredentialsError, ClientError) as e:
            return handle_aws_error(e)
        except Exception as e:
            logger.error(f"Error fetching service data for {service_name}: {e}")
            return jsonify({'error': 'Failed to fetch service data'}), 500

    @app.route('/api/daily-breakdown')
    @limiter.limit("20 per minute")
    def get_daily_breakdown():
        """Get daily cost breakdown by service"""
        try:
            days = validate_days(request.args.get('days'))
            region = validate_region(request.args.get('region', 'all'))
            specific_date = validate_date(request.args.get('date'))
            
            data = get_daily_service_breakdown(days, region, specific_date)
            return jsonify(data)
            
        except ValidationError as e:
            return handle_validation_error(e)
        except Exception as e:
            logger.error(f"Error fetching daily breakdown: {e}")
            return jsonify({'error': 'Failed to fetch daily breakdown'}), 500

    @app.route('/api/daily-ebs')
    @limiter.limit("20 per minute")
    def get_daily_ebs():
        """Get daily EBS cost breakdown"""
        try:
            days = validate_days(request.args.get('days'))
            specific_date = validate_date(request.args.get('date'))
            month = validate_month(request.args.get('month'))
            region = validate_region(request.args.get('region', 'all'))
            
            data = get_ebs_daily_breakdown(days, specific_date, month, region)
            return jsonify(data)
            
        except ValidationError as e:
            return handle_validation_error(e)
        except Exception as e:
            logger.error(f"Error fetching EBS breakdown: {e}")
            return jsonify({'error': 'Failed to fetch EBS data'}), 500

    @app.route('/api/daily-ec2')
    @limiter.limit("20 per minute")
    def get_daily_ec2():
        """Get daily EC2 cost breakdown"""
        try:
            days = validate_days(request.args.get('days'))
            specific_date = validate_date(request.args.get('date'))
            month = validate_month(request.args.get('month'))
            region = validate_region(request.args.get('region', 'all'))
            
            data = get_ec2_daily_breakdown(days, specific_date, month, region)
            return jsonify(data)
            
        except ValidationError as e:
            return handle_validation_error(e)
        except Exception as e:
            logger.error(f"Error fetching EC2 breakdown: {e}")
            return jsonify({'error': 'Failed to fetch EC2 data'}), 500

    # Cache management endpoints
    @app.route('/api/cache/stats')
    @limiter.limit("10 per minute")
    def get_cache_stats_endpoint():
        """Get cache statistics for monitoring"""
        try:
            stats = get_cache_stats()
            return jsonify(stats)
        except Exception as e:
            logger.error(f"Error getting cache stats: {e}")
            return jsonify({'error': 'Failed to get cache statistics'}), 500

    @app.route('/api/cache/clear', methods=['POST'])
    @limiter.limit("5 per minute")
    def clear_cache_endpoint():
        """Clear server-side cache (admin function)"""
        try:
            clear_cache()
            cleanup_expired_cache()
            return jsonify({'message': 'Cache cleared successfully'})
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return jsonify({'error': 'Failed to clear cache'}), 500

    @app.route('/api/cache/cleanup', methods=['POST'])
    @limiter.limit("10 per minute")
    def cleanup_cache_endpoint():
        """Clean up expired cache entries"""
        try:
            expired_count = cleanup_expired_cache()
            return jsonify({
                'message': 'Cache cleanup completed',
                'expired_entries_removed': expired_count
            })
        except Exception as e:
            logger.error(f"Error cleaning up cache: {e}")
            return jsonify({'error': 'Failed to cleanup cache'}), 500
    
    return app


# Data fetching functions (moved from original app.py)
@cache_result()
def get_cost_data(days: int = 30, filter_region: str = 'all', specific_date: str = None, 
                  month: str = None, hide_account: bool = False) -> Dict[str, Any]:
    """
    Fetch AWS cost data using Cost Explorer API with enhanced error handling
    """
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
        logger.info(f"Fetching AWS cost data: {start_date} to {end_date}, region={filter_region}")
        
        # Build request parameters
        request_params = {
            'TimePeriod': {
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            'Granularity': 'DAILY',
            'Metrics': ['BlendedCost'],
            'GroupBy': [{'Type': 'DIMENSION', 'Key': 'SERVICE'}]
        }
        
        # Add region filter if specified (skip for 'all', 'global', or empty values)
        if filter_region and filter_region not in ['all', 'global', '']:
            request_params['Filter'] = {
                'Dimensions': {
                    'Key': 'REGION',
                    'Values': [filter_region]
                }
            }
        
        # Get daily costs
        daily_response = client.get_cost_and_usage(**request_params)
        
        # Process daily costs and daily service breakdown together
        daily_costs = []
        service_totals = {}
        daily_service_by_date = {}
        total_cost = 0
        
        for result in daily_response['ResultsByTime']:
            date = result['TimePeriod']['Start']
            day_total = 0
            daily_service_by_date[date] = {}
            
            for group in result['Groups']:
                service = group['Keys'][0]
                cost = float(group['Metrics']['BlendedCost']['Amount'])
                day_total += cost
                
                # Track service totals
                service_totals[service] = service_totals.get(service, 0) + cost
                
                # Track daily service breakdown with display names
                display_name = normalize_service_name(service)
                daily_service_by_date[date][display_name] = cost
            
            daily_costs.append({'date': date, 'cost': day_total})
            total_cost += day_total
        
        # Convert to arrays aligned with dates
        all_services = set()
        for date_services in daily_service_by_date.values():
            all_services.update(date_services.keys())
        
        daily_service_breakdown = {}
        for service in all_services:
            daily_service_breakdown[service] = []
            for result in daily_response['ResultsByTime']:
                date = result['TimePeriod']['Start']
                cost = daily_service_by_date[date].get(service, 0)
                daily_service_breakdown[service].append(cost)
        
        # Sort services by cost and clean up names
        service_breakdown = [
            {'service': normalize_service_name(service), 'cost': cost}
            for service, cost in sorted(service_totals.items(), key=lambda x: x[1], reverse=True)
            if cost >= 0.0001
        ]
        
        # Apply global service filtering if 'global' region is selected
        if filter_region == 'global':
            service_breakdown = [
                s for s in service_breakdown 
                if is_global_service(s['service'])
            ]
            
            # Recalculate total cost for global services only
            total_cost = sum(s['cost'] for s in service_breakdown)
            
            # Filter daily costs to only include global services
            filtered_daily_service_breakdown = {}
            for service_display, daily_costs in daily_service_breakdown.items():
                if is_global_service(service_display):
                    filtered_daily_service_breakdown[service_display] = daily_costs
            daily_service_breakdown = filtered_daily_service_breakdown
            
            # Recalculate daily costs totals
            daily_costs = []
            for i, result in enumerate(daily_response['ResultsByTime']):
                date = result['TimePeriod']['Start']
                day_total = sum(
                    daily_service_breakdown[service][i] 
                    for service in daily_service_breakdown.keys()
                    if i < len(daily_service_breakdown[service])
                )
                daily_costs.append({'date': date, 'cost': day_total})
        
        # Get account ID
        if hide_account:
            account_id = '***HIDDEN***'
        else:
            try:
                sts_client = get_aws_session().client('sts')
                account_id = sts_client.get_caller_identity()['Account']
            except Exception:
                account_id = 'Unknown'
        
        logger.debug(f"Successfully fetched cost data: total=${total_cost:.2f}, services={len(service_breakdown)}")
        
        return {
            'totalCost': total_cost,
            'dailyCosts': daily_costs,
            'serviceBreakdown': service_breakdown,
            'dailyServiceBreakdown': daily_service_breakdown,
            'accountId': account_id,
            'dateRange': f"{start_date.strftime('%Y-%m-%d')} to {(end_date - timedelta(days=1)).strftime('%Y-%m-%d')} (Local Time)"
        }
        
    except Exception as e:
        logger.error(f"Error fetching cost data: {e}")
        raise


@cache_result()
def get_available_regions() -> list:
    """Get list of regions with cost data"""
    try:
        client = get_ce_client()
        end_date = datetime.now().date()
        start_date = end_date - timedelta(days=30)
        
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='MONTHLY',
            Metrics=['BlendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'REGION'}]
        )
        
        regions = set()
        for result in response['ResultsByTime']:
            for group in result['Groups']:
                if group['Keys'][0] and float(group['Metrics']['BlendedCost']['Amount']) > 0:
                    regions.add(group['Keys'][0])
        
        return sorted(list(regions))
        
    except Exception as e:
        logger.error(f"Error fetching regions: {e}")
        return []


@cache_result()
def get_service_cost_data(service_name: str, days: int = 30, specific_date: str = None, 
                         month: str = None) -> Dict[str, Any]:
    """Fetch cost data for a specific AWS service"""
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
        # Get original service name efficiently
        original_service_name = get_original_service_name(service_name)
        
        # Filter for specific service to reduce API response size
        daily_response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[{'Type': 'DIMENSION', 'Key': 'SERVICE'}],
            Filter={
                'Dimensions': {
                    'Key': 'SERVICE',
                    'Values': [original_service_name]
                }
            }
        )
        
        daily_costs = []
        for result in daily_response['ResultsByTime']:
            date = result['TimePeriod']['Start']
            cost = sum(float(group['Metrics']['BlendedCost']['Amount']) 
                      for group in result['Groups'] 
                      if group['Keys'][0] == original_service_name)
            daily_costs.append({'date': date, 'cost': cost})
        
        return {'dailyCosts': daily_costs}
        
    except Exception as e:
        logger.error(f"Error fetching service data for {service_name}: {e}")
        return {'error': str(e), 'dailyCosts': []}


@cache_result()
def get_ebs_daily_breakdown(days: int = 30, specific_date: str = None, month: str = None, 
                           filter_region: str = 'all') -> Dict[str, Any]:
    """Get EBS daily breakdown by usage type group"""
    # EBS is a regional service - return empty for global region
    if filter_region == 'global':
        return {'breakdown': []}
        
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
        request_params = {
            'TimePeriod': {
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            'Granularity': 'DAILY',
            'Metrics': ['BlendedCost'],
            'GroupBy': [
                {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
            ]
        }
        
        # Add region filter if specified (skip for 'all', 'global', or empty values)
        if filter_region and filter_region not in ['all', 'global', '']:
            request_params['Filter'] = {
                'Dimensions': {
                    'Key': 'REGION',
                    'Values': [filter_region]
                }
            }
        
        response = client.get_cost_and_usage(**request_params)
        
        ebs_costs = {}
        other_items = {}  # Track "Other" items separately
        
        for result in response['ResultsByTime']:
            for group in result['Groups']:
                service = group['Keys'][0]
                usage_type = group['Keys'][1]
                cost = float(group['Metrics']['BlendedCost']['Amount'])
                
                # Filter for EBS-related usage types and costs
                if cost >= 0.0001 and 'EBS:' in usage_type:
                    # Improved categorization based on usage type patterns
                    category = categorize_ebs_usage_improved(usage_type)
                    
                    # If it's a generic "Other" category, track the original usage type
                    if category == 'EBS Storage (Other)':
                        clean_type = usage_type.replace('EBS:', '').strip()
                        other_items[clean_type] = other_items.get(clean_type, 0) + cost
                    else:
                        ebs_costs[category] = ebs_costs.get(category, 0) + cost
        
        # Handle "Other" items - if only one type, use the actual usage type name
        if other_items:
            if len(other_items) == 1:
                # Only one "other" item, use the actual usage type
                usage_type, cost = next(iter(other_items.items()))
                ebs_costs[f'EBS {usage_type}'] = cost
            else:
                # Multiple "other" items, combine under generic label
                total_other_cost = sum(other_items.values())
                ebs_costs['EBS Storage (Other)'] = total_other_cost
        
        breakdown = [{'category': cat, 'cost': cost} 
                    for cat, cost in sorted(ebs_costs.items(), key=lambda x: x[1], reverse=True)]
        return {'breakdown': breakdown}
        
    except Exception as e:
        logger.error(f"Error fetching EBS breakdown: {e}")
        return {'error': str(e), 'breakdown': []}


def _update_ec2_category(ec2_costs: dict, daily_ec2_data: dict, category: str, 
                        cost: float, index: int, dates_len: int):
    """Helper function to update EC2 category costs"""
    if category not in ec2_costs:
        ec2_costs[category] = 0
        daily_ec2_data[category] = [0] * dates_len
    ec2_costs[category] += cost
    daily_ec2_data[category][index] += cost


@cache_result()
def get_ec2_daily_breakdown(days: int = 30, specific_date: str = None, month: str = None, 
                           filter_region: str = 'all') -> Dict[str, Any]:
    """Get EC2 daily breakdown by usage type group"""
    # EC2 is a regional service - return empty for global region
    if filter_region == 'global':
        return {'breakdown': []}
        
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
        request_params = {
            'TimePeriod': {
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            'Granularity': 'DAILY',
            'Metrics': ['BlendedCost'],
            'GroupBy': [
                {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
            ]
        }
        
        # Add region filter if specified (skip for 'all', 'global', or empty values)
        if filter_region and filter_region not in ['all', 'global', '']:
            request_params['Filter'] = {
                'Dimensions': {
                    'Key': 'REGION',
                    'Values': [filter_region]
                }
            }
        
        response = client.get_cost_and_usage(**request_params)
        
        ec2_costs = {}
        daily_ec2_data = {}
        dates = [result['TimePeriod']['Start'] for result in response['ResultsByTime']]
        
        # Process costs efficiently
        for i, result in enumerate(response['ResultsByTime']):
            for group in result['Groups']:
                service = group['Keys'][0]
                usage_type = group['Keys'][1]
                cost = float(group['Metrics']['BlendedCost']['Amount'])
                
                # Skip if cost too low or contains excluded patterns
                if cost < 0.0001 or 'EBS:' in usage_type or 'BoxUsage' in usage_type:
                    continue
                
                # Improved categorization for EC2-related services
                if service in ['Amazon Elastic Compute Cloud - Compute', 'EC2 - Other', 'Amazon Elastic Compute Cloud NatGateway']:
                    category = categorize_ec2_usage_improved(usage_type, service)
                    _update_ec2_category(ec2_costs, daily_ec2_data, category, cost, i, len(dates))
        
        breakdown = [{'category': cat, 'cost': cost} 
                    for cat, cost in sorted(ec2_costs.items(), key=lambda x: x[1], reverse=True)]
        return {'breakdown': breakdown, 'dailyData': daily_ec2_data, 'dates': dates}
        
    except Exception as e:
        logger.error(f"Error fetching EC2 breakdown: {e}")
        return {'error': str(e), 'breakdown': []}


@cache_result()
def get_daily_service_breakdown(days: int = 30, filter_region: str = 'all', 
                               specific_date: str = None) -> Dict[str, Any]:
    """Get daily cost breakdown by service for stacked bar chart"""
    try:
        # Reuse get_cost_data to avoid duplicate API calls
        cost_data = get_cost_data(days, filter_region, specific_date, None, False)
        if 'error' in cost_data:
            return {}
        return cost_data.get('dailyServiceBreakdown', {})
    except Exception as e:
        logger.error(f"Error fetching daily service breakdown: {e}")
        return {}


# Create default app instance
app = create_app()

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=8080)