"""Input validation functions for CloudSense"""

import re
from datetime import datetime
from typing import Union
from flask import current_app


class ValidationError(Exception):
    """Custom exception for validation errors"""
    pass


def validate_days(days_str: Union[str, int, None], default: int = 30) -> int:
    """
    Validate and sanitize days parameter
    
    Args:
        days_str: String or int representing number of days
        default: Default value if days_str is None or invalid
        
    Returns:
        int: Validated number of days
        
    Raises:
        ValidationError: If days is outside valid range
    """
    if days_str is None:
        return default
        
    try:
        days = int(days_str)
    except (ValueError, TypeError):
        raise ValidationError(f"Invalid days parameter: {days_str}")
    
    min_days = getattr(current_app.config, 'MIN_DAYS_RANGE', 1)
    max_days = getattr(current_app.config, 'MAX_DAYS_RANGE', 365)
    
    if not min_days <= days <= max_days:
        raise ValidationError(f"Days must be between {min_days} and {max_days}")
    
    return days


def validate_region(region: str) -> str:
    """
    Validate AWS region parameter
    
    Args:
        region: AWS region string
        
    Returns:
        str: Validated region
        
    Raises:
        ValidationError: If region format is invalid
    """
    if not region:
        return 'all'
    
    if region in ['all', 'global']:
        return region
    
    # AWS region pattern: us-east-1, eu-west-1, ap-southeast-2, etc.
    # Also accept 'global' for services like CloudFront, Route 53, etc.
    region_pattern = r'^[a-z]{2,3}-[a-z]+-\d+$|^us-gov-[a-z]+-\d+$'
    
    if not re.match(region_pattern, region):
        raise ValidationError(f"Invalid AWS region format: {region}")
    
    return region


def validate_date(date_str: Union[str, None]) -> Union[str, None]:
    """
    Validate date parameter
    
    Args:
        date_str: Date string in YYYY-MM-DD format
        
    Returns:
        str or None: Validated date string or None
        
    Raises:
        ValidationError: If date format is invalid
    """
    if not date_str:
        return None
    
    try:
        # Parse date to validate format
        datetime.fromisoformat(date_str).date()
        return date_str
    except ValueError:
        raise ValidationError(f"Invalid date format. Expected YYYY-MM-DD, got: {date_str}")


def validate_month(month_str: Union[str, None]) -> Union[str, None]:
    """
    Validate month parameter
    
    Args:
        month_str: Month string (current, previous, or YYYY-MM format)
        
    Returns:
        str or None: Validated month string or None
        
    Raises:
        ValidationError: If month format is invalid
    """
    if not month_str:
        return None
    
    if month_str in ['current', 'previous']:
        return month_str
    
    # Validate YYYY-MM format
    month_pattern = r'^\d{4}-\d{2}$'
    if not re.match(month_pattern, month_str):
        raise ValidationError(f"Invalid month format. Expected YYYY-MM, got: {month_str}")
    
    try:
        year, month = month_str.split('-')
        year, month = int(year), int(month)
        
        if not 1 <= month <= 12:
            raise ValidationError(f"Month must be between 01 and 12, got: {month:02d}")
        
        if not 2000 <= year <= 9999:
            raise ValidationError(f"Year must be between 2000 and 9999, got: {year}")
            
        return month_str
    except ValueError:
        raise ValidationError(f"Invalid month format: {month_str}")


def validate_budget_limit(budget_str: Union[str, None]) -> Union[float, None]:
    """
    Validate budget limit parameter
    
    Args:
        budget_str: Budget limit as string
        
    Returns:
        float or None: Validated budget limit or None
        
    Raises:
        ValidationError: If budget format is invalid
    """
    if not budget_str:
        return None
    
    try:
        budget = float(budget_str)
        if budget < 0:
            raise ValidationError("Budget limit cannot be negative")
        if budget > 1000000:  # $1M limit
            raise ValidationError("Budget limit cannot exceed $1,000,000")
        return budget
    except ValueError:
        raise ValidationError(f"Invalid budget limit format: {budget_str}")


def sanitize_service_name(service_name: str) -> str:
    """
    Sanitize service name for safe usage
    
    Args:
        service_name: AWS service name
        
    Returns:
        str: Sanitized service name
    """
    if not service_name:
        return ""
    
    # Remove potentially dangerous characters
    sanitized = re.sub(r'[<>"\']', '', service_name)
    # Limit length
    return sanitized[:100]
