"""Helper functions for CloudSense"""

from datetime import datetime, timedelta
from typing import Tuple, Union


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

# AWS Global Services - services that operate globally and don't belong to specific regions
GLOBAL_SERVICES = {
    # Core global services (exact AWS service names as they appear in Cost Explorer)
    'AWS Identity and Access Management': 'IAM',
    'Amazon Route 53': 'Route 53',
    'Route53': 'Route 53',  # Common variation
    'Amazon CloudFront': 'CloudFront',
    'AWS Organizations': 'AWS Organizations',
    'AWS WAF': 'AWS WAF',
    'AWS Shield': 'AWS Shield',
    'AWS Global Accelerator': 'Global Accelerator',
    'AWS Single Sign-On': 'AWS SSO',
    'AWS Resource Access Manager': 'AWS RAM',
    'AWS Certificate Manager': 'ACM',
    'AWS Cost Explorer': 'Cost Explorer',
    
    # Additional common global services
    'AWS CloudTrail': 'CloudTrail',
    'AWS Support (Business)': 'Support',
    'AWS Support (Developer)': 'Support',
    'AWS Support (Enterprise)': 'Support',
    'AWS Trusted Advisor': 'Trusted Advisor',
    'AWS Billing': 'Billing',
    'Amazon Registrar': 'Domain Registration',
    
    # Edge cases and variations
    'AWS Cost and Usage Report': 'Cost and Usage Report',
    'AWS Budgets': 'Budgets',
}

# Create reverse mapping for efficient lookups
GLOBAL_SERVICES_REVERSE = {v: k for k, v in GLOBAL_SERVICES.items()}


def normalize_service_name(service: str) -> str:
    """
    Normalize service name using mapping
    
    Args:
        service: Original AWS service name
        
    Returns:
        str: Normalized display name
    """
    return SERVICE_NAMES.get(service, service)


def is_global_service(service_name: str) -> bool:
    """
    Check if a service is a global AWS service
    
    Args:
        service_name: AWS service name (original or display name)
        
    Returns:
        bool: True if the service is global, False otherwise
    """
    # Check exact match first
    if service_name in GLOBAL_SERVICES:
        return True
    
    # Check if it's a display name that maps to global service
    if service_name in GLOBAL_SERVICES_REVERSE:
        return True
    
    # Check partial matches for service variations
    service_lower = service_name.lower()
    for global_service in GLOBAL_SERVICES.keys():
        if global_service.lower() in service_lower or service_lower in global_service.lower():
            return True
    
    return False


def get_original_service_name(display_name: str) -> str:
    """
    Get original service name from display name
    
    Args:
        display_name: Display name of service
        
    Returns:
        str: Original AWS service name
    """
    return REVERSE_SERVICE_NAMES.get(display_name, display_name)


def categorize_ebs_usage(usage_type: str) -> str:
    """
    Categorize EBS usage type
    
    Args:
        usage_type: AWS usage type string
        
    Returns:
        str: Categorized usage type
    """
    for pattern, category in EBS_CATEGORIES.items():
        if pattern in usage_type:
            return category
    return 'Other EBS'


def parse_date_params(days: Union[int, None] = None, 
                     specific_date: Union[str, None] = None, 
                     month: Union[str, None] = None) -> Tuple[datetime, datetime]:
    """
    Parse and validate date parameters using local time
    
    Args:
        days: Number of days to look back
        specific_date: Specific date in ISO format
        month: Month specification (current, previous, or YYYY-MM)
        
    Returns:
        Tuple[datetime, datetime]: Start date and end date
    """
    local_now = datetime.now()
    
    if specific_date:
        start_date = datetime.fromisoformat(specific_date).date()
        return start_date, start_date + timedelta(days=1)
    elif month:
        if month == 'current':
            today = local_now.date()
            return today.replace(day=1), today + timedelta(days=1)
        elif month == 'previous':
            today = local_now.date()
            start = (today.replace(day=1) - timedelta(days=1)).replace(day=1)
            return start, today.replace(day=1)
        else:
            year, month_num = month.split('-')
            start = datetime(int(year), int(month_num), 1).date()
            if start.month == 12:
                end = datetime(start.year + 1, 1, 1).date()
            else:
                end = datetime(start.year, start.month + 1, 1).date()
            return start, end
    else:
        end = local_now.date() + timedelta(days=1)
        return end - timedelta(days=(days or 30)+1), end


def format_currency(amount: float) -> str:
    """
    Format currency amount with proper precision
    
    Args:
        amount: Dollar amount to format
        
    Returns:
        str: Formatted currency string
    """
    if amount < 0.01:
        return f"${amount:.4f}"
    elif amount < 1:
        return f"${amount:.3f}"
    else:
        return f"${amount:.2f}"


def calculate_daily_average(total_cost: float, days: int) -> float:
    """
    Calculate daily average cost
    
    Args:
        total_cost: Total cost amount
        days: Number of days
        
    Returns:
        float: Daily average
    """
    if days <= 0:
        return 0.0
    return total_cost / days


def calculate_monthly_projection(daily_avg: float, days_in_month: int = 30) -> float:
    """
    Calculate monthly cost projection
    
    Args:
        daily_avg: Daily average cost
        days_in_month: Number of days to project for
        
    Returns:
        float: Projected monthly cost
    """
    return daily_avg * days_in_month


def categorize_ebs_usage_improved(usage_type: str) -> str:
    """
    Improved EBS usage type categorization to match AWS billing console exactly
    
    Args:
        usage_type: AWS usage type string (e.g., "EBS:VolumeUsage.gp3")
        
    Returns:
        str: Descriptive category name matching AWS console
    """
    # Remove EBS: prefix if present
    clean_type = usage_type.replace('EBS:', '').strip()
    
    # Match AWS console line items exactly - most specific patterns first
    
    # IOPS charges (most specific)
    if 'VolumeP-IOPS.io2' in clean_type:
        return 'EBS io2 IOPS'
    elif 'VolumeP-IOPS.piops' in clean_type:
        return 'EBS io1 IOPS' 
    elif 'P-IOPS' in clean_type and 'io2' in clean_type:
        return 'EBS io2 IOPS'
    elif 'P-IOPS' in clean_type and 'piops' in clean_type:
        return 'EBS io1 IOPS'
    elif 'IOPS' in clean_type and 'io2' in clean_type:
        return 'EBS io2 IOPS'
    elif 'IOPS' in clean_type and ('io1' in clean_type or 'piops' in clean_type):
        return 'EBS io1 IOPS'
    
    # Snapshots
    elif 'Snapshot' in clean_type:
        return 'EBS Snapshots'
    
    # Storage charges (specific volume types) - check broader patterns first
    elif 'gp3' in clean_type and 'VolumeUsage' in clean_type:
        return 'EBS gp3 Storage'
    elif 'VolumeUsage.gp3' in clean_type:
        return 'EBS gp3 Storage'
    elif 'io1' in clean_type and 'VolumeUsage' in clean_type:
        return 'EBS io1 Storage'  
    elif 'VolumeUsage.io1' in clean_type:
        return 'EBS io1 Storage'
    elif 'piops' in clean_type and 'VolumeUsage' in clean_type:
        return 'EBS io1 Storage'  # piops = provisioned IOPS storage (io1)
    elif 'io2' in clean_type and 'VolumeUsage' in clean_type:
        return 'EBS io2 Storage'
    elif 'VolumeUsage.io2' in clean_type:  
        return 'EBS io2 Storage'
    elif 'gp2' in clean_type and 'VolumeUsage' in clean_type:
        return 'EBS gp2 Storage'
    elif 'VolumeUsage.gp2' in clean_type:
        return 'EBS gp2 Storage'
    elif 'VolumeUsage.st1' in clean_type:
        return 'EBS st1 Storage'
    elif 'VolumeUsage.sc1' in clean_type:
        return 'EBS sc1 Storage'
    
    # Generic fallbacks
    elif 'VolumeUsage' in clean_type:
        return 'EBS Storage (Other)'
    else:
        # Log unmatched types for debugging
        import logging
        logger = logging.getLogger(__name__)
        logger.debug(f"Unmatched EBS usage type: {clean_type}")
        return f'EBS Other ({clean_type})'  # Show the actual usage type for debugging


def categorize_ec2_usage_improved(usage_type: str, service: str) -> str:
    """
    Improved EC2 usage type categorization with better pattern matching
    
    Args:
        usage_type: AWS usage type string
        service: AWS service name
        
    Returns:
        str: Descriptive category name
    """
    # Handle NAT Gateway separately
    if service == 'Amazon Elastic Compute Cloud NatGateway' or 'NatGateway' in usage_type:
        return 'NAT Gateway'
    
    # Pattern-based categorization
    if 'DataTransfer' in usage_type:
        if 'In' in usage_type:
            return 'Data Transfer (In)'
        elif 'Out' in usage_type:
            return 'Data Transfer (Out)'
        else:
            return 'Data Transfer'
    elif 'ElasticIP' in usage_type:
        return 'Elastic IP'
    elif 'LoadBalancer' in usage_type:
        return 'Load Balancer'
    elif 'SpotUsage' in usage_type:
        return 'Spot Instances'
    elif 'ReservedInstance' in usage_type:
        return 'Reserved Instances'
    elif 'DedicatedUsage' in usage_type:
        return 'Dedicated Hosts'
    elif 'Instance' in usage_type and 'BoxUsage' not in usage_type:
        return 'Instance Usage'
    else:
        return 'EC2 Other'
