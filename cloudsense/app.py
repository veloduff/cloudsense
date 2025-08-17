#!/usr/bin/env python3
from boto3 import Session
from datetime import datetime, timedelta, timezone
from flask import Flask, jsonify, request, render_template, abort
from decimal import Decimal
from botocore.exceptions import NoCredentialsError, ClientError
import os
import json
import threading

# Thread-safe session management
_local = threading.local()

def get_aws_session():
    """Get thread-safe cached AWS session"""
    if not hasattr(_local, 'session'):
        _local.session = Session()
    return _local.session

def get_ce_client():
    """Get thread-safe cached Cost Explorer client"""
    if not hasattr(_local, 'ce_client'):
        _local.ce_client = get_aws_session().client('ce', region_name='us-east-1')
    return _local.ce_client

def check_auth():
    """Basic auth check - requires AWS credentials"""
    try:
        get_aws_session().client('sts').get_caller_identity()
    except (NoCredentialsError, ClientError):
        abort(401)

def parse_date_params(days=None, specific_date=None, month=None):
    """Parse and validate date parameters with timezone awareness"""
    utc_now = datetime.now(timezone.utc)
    if specific_date:
        start_date = datetime.fromisoformat(specific_date).replace(tzinfo=timezone.utc).date()
        return start_date, start_date + timedelta(days=1)
    elif month:
        if month == 'current':
            today = utc_now.date()
            return today.replace(day=1), today + timedelta(days=1)
        elif month == 'previous':
            today = utc_now.date()
            start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            return start, today.replace(day=1)
        else:
            year, month_num = month.split('-')
            start = datetime(int(year), int(month_num), 1, tzinfo=timezone.utc).date()
            if start.month == 12:
                end = datetime(start.year + 1, 1, 1, tzinfo=timezone.utc).date()
            else:
                end = datetime(start.year, start.month + 1, 1, tzinfo=timezone.utc).date()
            return start, end
    else:
        end = utc_now.date() + timedelta(days=1)
        return end - timedelta(days=(days or 30)+1), end

def create_app():
    """Create and configure the Flask application"""
    template_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'templates')
    app = Flask(__name__, template_folder=template_dir)
    
    @app.before_request
    def before_request():
        if request.endpoint and request.endpoint.startswith('api.'):
            check_auth()
    
    @app.route('/')
    def index():
        try:
            check_auth()
            return render_template('index.html')
        except Exception:
            return "AWS credentials required", 401

    @app.route('/api/billing')
    def get_billing():
        try:
            days = int(request.args.get('days', 30))
            region = request.args.get('region', 'all')
            specific_date = request.args.get('date')
            month = request.args.get('month')
            data = get_cost_data(days, region, specific_date, month)
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/regions')
    def get_regions():
        try:
            data = get_available_regions()
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/service/<service_name>')
    def get_service_data(service_name):
        try:
            days = int(request.args.get('days', 30))
            specific_date = request.args.get('date')
            month = request.args.get('month')
            data = get_service_cost_data(service_name, days, specific_date, month)
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/daily-breakdown')
    def get_daily_breakdown():
        try:
            days = int(request.args.get('days', 30))
            region = request.args.get('region', 'all')
            specific_date = request.args.get('date')
            data = get_daily_service_breakdown(days, region, specific_date)
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/daily-ebs')
    def get_daily_ebs():
        try:
            days = int(request.args.get('days', 30))
            specific_date = request.args.get('date')
            month = request.args.get('month')
            return jsonify(get_ebs_daily_breakdown(days, specific_date, month))
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/daily-ec2')
    def get_daily_ec2():
        try:
            days = int(request.args.get('days', 30))
            specific_date = request.args.get('date')
            month = request.args.get('month')
            return jsonify(get_ec2_daily_breakdown(days, specific_date, month))
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    return app

app = create_app()

class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)

# Service name mapping for performance
SERVICE_NAMES = {
    'Amazon Elastic Compute Cloud - Compute': 'EC2 - Compute',
    'Amazon Simple Storage Service': 'Amazon S3',
    'Stable Diffusion 3.5 Large v1.0 (Amazon Bedrock Edition)': 'Bedrock: SD 3.5 Large',
    'Claude Opus 4 (Amazon Bedrock Edition)': 'Bedrock: Claude Opus 4',
    'Claude Sonnet 4 (Amazon Bedrock Edition)': 'Bedrock: Claude Sonnet 4',
    'Amazon Virtual Private Cloud': 'VPC',
    'Amazon Elastic File System': 'Amazon EFS',
    'AmazonCloudWatch': 'CloudWatch',
    'Amazon DynamoDB': 'DynamoDB',
    'Amazon Route 53': 'Route53'
}

# Reverse mapping for efficient lookups
REVERSE_SERVICE_NAMES = {v: k for k, v in SERVICE_NAMES.items()}

# EBS category mapping
EBS_CATEGORIES = {
    'VolumeUsage.gp3': 'EBS gp3 Storage',
    'VolumeUsage.io2': 'EBS io2 Storage', 
    'VolumeUsage.piops': 'EBS io1 Storage',
    'VolumeP-IOPS.io2': 'EBS io2 IOPS',
    'VolumeP-IOPS.piops': 'EBS io1 IOPS',
    'SnapshotUsage': 'EBS Snapshots'
}

def normalize_service_name(service):
    """Normalize service name using mapping"""
    return SERVICE_NAMES.get(service, service)

def get_original_service_name(display_name):
    """Get original service name from display name"""
    return REVERSE_SERVICE_NAMES.get(display_name, display_name)

def categorize_ebs_usage(usage_type):
    """Categorize EBS usage type"""
    for pattern, category in EBS_CATEGORIES.items():
        if pattern in usage_type:
            return category
    return 'Other EBS'

def get_cost_data(days=30, filter_region='all', specific_date=None, month=None):
    """Fetch AWS cost data using Cost Explorer API"""
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
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
        
        # Add region filter if specified
        if filter_region != 'all':
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
        daily_service_by_date = {}  # date -> service -> cost
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
                if service not in service_totals:
                    service_totals[service] = 0
                service_totals[service] += cost
                
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
        
        # Sort services by cost and clean up names - show ALL services with meaningful cost
        service_breakdown = [
            {'service': normalize_service_name(service), 'cost': cost}
            for service, cost in sorted(service_totals.items(), key=lambda x: x[1], reverse=True)
            if cost >= 0.0001  # Only show services with at least $0.0001 cost
        ]  # No limit - show all services with meaningful cost
        
        # Get account ID
        try:
            sts_client = get_aws_session().client('sts')
            account_id = sts_client.get_caller_identity()['Account']
        except Exception:
            account_id = 'Unknown'
        
        return {
            'totalCost': total_cost,
            'dailyCosts': daily_costs,
            'serviceBreakdown': service_breakdown,
            'dailyServiceBreakdown': daily_service_breakdown,
            'accountId': account_id,
            'dateRange': f"{start_date.strftime('%Y-%m-%d')} to {(end_date - timedelta(days=1)).strftime('%Y-%m-%d')}"
        }
        
    except NoCredentialsError:
        return {'error': 'AWS credentials not configured. Run: aws configure'}
    except ClientError as e:
        if e.response['Error']['Code'] == 'UnauthorizedOperation':
            return {'error': 'AWS credentials lack Cost Explorer permissions'}
        return {'error': f'AWS API error: {e.response["Error"]["Message"]}'}
    except Exception as e:
        return {'error': str(e)}

def get_available_regions():
    """Get list of regions with cost data"""
    try:
        client = get_ce_client()
        end_date = datetime.now(timezone.utc).date()
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
        
    except (NoCredentialsError, ClientError):
        return []
    except Exception:
        return []

def get_service_cost_data(service_name, days=30, specific_date=None, month=None):
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
        return {'error': str(e), 'dailyCosts': []}

def get_ebs_daily_breakdown(days=30, specific_date=None, month=None):
    """Get EBS daily breakdown by usage type"""
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
            ]
        )
        
        ebs_costs = {}
        for result in response['ResultsByTime']:
            for group in result['Groups']:
                usage_type = group['Keys'][1]
                cost = float(group['Metrics']['BlendedCost']['Amount'])
                
                if 'EBS:' in usage_type and cost >= 0.0001:
                    category = categorize_ebs_usage(usage_type)
                    ebs_costs[category] = ebs_costs.get(category, 0) + cost
        
        breakdown = [{'category': cat, 'cost': cost} 
                    for cat, cost in sorted(ebs_costs.items(), key=lambda x: x[1], reverse=True)]
        return {'breakdown': breakdown}
        
    except Exception as e:
        return {'error': str(e), 'breakdown': []}

def _update_ec2_category(ec2_costs, daily_ec2_data, category, cost, index, dates_len):
    """Helper function to update EC2 category costs"""
    if category not in ec2_costs:
        ec2_costs[category] = 0
        daily_ec2_data[category] = [0] * dates_len
    ec2_costs[category] += cost
    daily_ec2_data[category][index] += cost

def get_ec2_daily_breakdown(days=30, specific_date=None, month=None):
    """Get EC2 daily breakdown by usage type"""
    try:
        client = get_ce_client()
        start_date, end_date = parse_date_params(days, specific_date, month)
        
        response = client.get_cost_and_usage(
            TimePeriod={
                'Start': start_date.strftime('%Y-%m-%d'),
                'End': end_date.strftime('%Y-%m-%d')
            },
            Granularity='DAILY',
            Metrics=['BlendedCost'],
            GroupBy=[
                {'Type': 'DIMENSION', 'Key': 'SERVICE'},
                {'Type': 'DIMENSION', 'Key': 'USAGE_TYPE'}
            ]
        )
        
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
                
                category = 'Other EC2'
                if 'SpotUsage' in usage_type:
                    category = 'Spot Instances'
                elif 'DataTransfer' in usage_type:
                    category = 'Data Transfer'
                elif 'ElasticIP' in usage_type:
                    category = 'Elastic IP'
                elif 'LoadBalancer' in usage_type:
                    category = 'Load Balancer'
                elif 'NatGateway' in usage_type:
                    category = 'NAT Gateway'
                
                if service in ['Amazon Elastic Compute Cloud - Compute', 'EC2 - Other', 'Amazon Elastic Compute Cloud NatGateway']:
                    if service == 'Amazon Elastic Compute Cloud NatGateway':
                        category = 'NAT Gateway'
                    _update_ec2_category(ec2_costs, daily_ec2_data, category, cost, i, len(dates))
        
        breakdown = [{'category': cat, 'cost': cost} 
                    for cat, cost in sorted(ec2_costs.items(), key=lambda x: x[1], reverse=True)]
        return {'breakdown': breakdown, 'dailyData': daily_ec2_data, 'dates': dates}
        
    except Exception as e:
        return {'error': str(e), 'breakdown': []}

def get_daily_service_breakdown(days=30, filter_region='all', specific_date=None):
    """Get daily cost breakdown by service for stacked bar chart"""
    try:
        # Reuse get_cost_data to avoid duplicate API calls
        cost_data = get_cost_data(days, filter_region, specific_date, None)
        if 'error' in cost_data:
            return {}
        return cost_data.get('dailyServiceBreakdown', {})
    except Exception:
        return {}

if __name__ == '__main__':
    app.run(debug=False, host='127.0.0.1', port=8080)