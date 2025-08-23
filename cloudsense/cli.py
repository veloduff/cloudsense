#!/usr/bin/env python3
"""CloudSense CLI entry point with enhanced configuration options"""

import argparse
import sys
import os
import logging
from datetime import datetime, timedelta
from .app import create_app, get_cost_data, check_aws_auth, get_ec2_daily_breakdown, get_ebs_daily_breakdown
from .utils.cache import get_cache_stats, generate_cache_key, get_cached_data, get_cache_entry_info, init_persistent_cache, clear_cache
from .config.config import config
from . import __version__

def setup_logging(log_level: str):
    """Setup logging configuration"""
    numeric_level = getattr(logging, log_level.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level}')
    
    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler('cloudsense.log') if log_level.upper() in ['DEBUG', 'INFO'] else logging.NullHandler()
        ]
    )
    
    # Reduce AWS SDK logging noise unless in DEBUG mode
    if log_level.upper() != 'DEBUG':
        logging.getLogger('botocore').setLevel(logging.WARNING)
        logging.getLogger('boto3').setLevel(logging.WARNING)
        logging.getLogger('urllib3').setLevel(logging.WARNING)


def output_cost_data_text(days: int = 30, hide_account: bool = False, force_refresh: bool = False, filter_region: str = 'all', start_date: datetime = None, end_date: datetime = None):
    """Output cost data as formatted text to stdout"""
    try:
        # Create Flask app for context
        app = create_app(hide_account=hide_account)
        
        with app.app_context():
            # Initialize persistent cache
            init_persistent_cache()
            
            # Handle force refresh
            if force_refresh:
                print("Force refresh requested - clearing cache...")
                clear_cache()
                cache_status = "FRESH"
            else:
                # Check cache status before fetching
                cache_key = generate_cache_key('get_cost_data', days=days, filter_region=filter_region, hide_account=hide_account)
                cached_data = get_cached_data(cache_key)
                
                if cached_data:
                    cache_status = "CACHED"
                else:
                    print("Gathering AWS cost data...")
                    cache_status = "FRESH"
            
            # Check AWS authentication
            if not check_aws_auth():
                print("ERROR: AWS credentials not configured or invalid")
                print("Please run 'aws configure' or set AWS environment variables")
                sys.exit(1)
            
            # Get cost data for specified region
            if start_date is not None and end_date is not None:
                # Convert dates to month format for backend
                month_str = start_date.strftime('%Y-%m')
                data = get_cost_data(days=days, filter_region=filter_region, hide_account=hide_account, month=month_str)
            else:
                # Use days mode
                data = get_cost_data(days=days, filter_region=filter_region, hide_account=hide_account)
            
            if 'error' in data:
                print(f"ERROR: {data['error']}")
                sys.exit(1)
            
            # Get EC2 and EBS breakdown data for detailed display
            ec2_breakdown_data = None
            ebs_breakdown_data = None
            if filter_region != 'global':  # Breakdowns not available for global
                try:
                    if start_date is not None and end_date is not None:
                        # Use specific month mode
                        month_str = start_date.strftime('%Y-%m')
                        ec2_breakdown_data = get_ec2_daily_breakdown(days=days, filter_region=filter_region, month=month_str)
                        ebs_breakdown_data = get_ebs_daily_breakdown(days=days, filter_region=filter_region, month=month_str)
                    else:
                        # Use days mode
                        ec2_breakdown_data = get_ec2_daily_breakdown(days=days, filter_region=filter_region)
                        ebs_breakdown_data = get_ebs_daily_breakdown(days=days, filter_region=filter_region)
                except Exception as e:
                    logger.debug(f"Could not fetch breakdown data: {e}")
            
            # Format output
            total_cost = data.get('totalCost', 0)
            services = data.get('serviceBreakdown', [])
            account_id = data.get('accountId', 'Unknown')
            
            # Get cache information after data retrieval
            cache_stats = get_cache_stats()
            if not force_refresh:
                cache_entry_info = get_cache_entry_info(cache_key)
            else:
                # For force refresh, generate cache key for the new entry
                cache_key = generate_cache_key('get_cost_data', days=days, filter_region=filter_region, hide_account=hide_account)
                cache_entry_info = get_cache_entry_info(cache_key)
        
        # Calculate date range
        if start_date is None or end_date is None:
            # Default behavior: days back from today
            end_date = datetime.now()
            start_date = end_date - timedelta(days=days)
        
        date_range = f"{start_date.strftime('%Y-%m-%d')} to {end_date.strftime('%Y-%m-%d')}"
        
        # Header
        print("=" * 74)
        print(f"CloudSense - AWS Cost Report ({days} days)")
        print("=" * 74)
        print(f"Account: {account_id}")
        print(f"Date Range: {date_range}")
        print(f"Region: {filter_region.upper() if filter_region != 'all' else 'All Regions'}")
        print(f"Services: {len(services)}")
        
        # Simplified cache status
        if cache_status == "CACHED" and cache_entry_info:
            cached_at = datetime.fromtimestamp(cache_entry_info['cached_at'])
            print(f"Data Status: CACHED at {cached_at.strftime('%Y-%m-%d %H:%M')}")
        else:
            print(f"Data Status: FRESH (updating cache)")
        print("-" * 74)
        
        # Services breakdown
        if services:
            print("Service Breakdown:")
            print("-" * 74)
            for i, service in enumerate(services, 1):
                service_name = service.get('service', 'Unknown')
                cost = service.get('cost', 0)
                percentage = (cost / total_cost * 100) if total_cost > 0 else 0
                
                # Clean up service name for display if too long
                display_name = service_name
                
                # Only remove prefixes if name is too long to fit (45 chars)
                if len(display_name) > 45:
                    prefixes_to_remove = ['Amazon ', 'AWS ']
                    for prefix in prefixes_to_remove:
                        if display_name.startswith(prefix):
                            display_name = display_name[len(prefix):]
                            break
                
                print(f"{i:2d}. {display_name:<45}   ${cost:>10.2f}   ({percentage:5.1f}%)")
                
                # Show detailed breakdown for EC2 - Other
                if service_name == 'EC2 - Other':
                    breakdown_items = []
                    
                    # EBS breakdown now captures everything from EC2-Other
                    if (ebs_breakdown_data and 'breakdown' in ebs_breakdown_data and 
                        ebs_breakdown_data['breakdown']):
                        breakdown_items.extend(ebs_breakdown_data['breakdown'])
                    
                    # Display breakdown items with tree formatting
                    for j, breakdown_item in enumerate(breakdown_items):
                        category = breakdown_item.get('category', 'Unknown')
                        item_cost = breakdown_item.get('cost', 0)
                        
                        # Determine prefix for breakdown items
                        is_last_breakdown = (j == len(breakdown_items) - 1)
                        breakdown_prefix = "└──" if is_last_breakdown else "├──"
                        
                        # Show more decimal places for very small costs
                        if item_cost < 0.01:
                            cost_str = f"{item_cost:>8.4f}"
                        else:
                            cost_str = f"{item_cost:>8.2f}"
                        print(f"    {breakdown_prefix} {category:<47}    {breakdown_prefix} {cost_str}")
            print("=" * 74)
            print(f"TOTAL COST: ${total_cost:>8.2f}")
            print("=" * 74)
        else:
            print("No services with costs found")
            print("=" * 74)
            print(f"TOTAL COST: ${total_cost:>8.2f}")
            print("=" * 74)
        
        
    except Exception as e:
        print(f"ERROR: Failed to retrieve cost data: {e}")
        sys.exit(1)


def main():
    """Enhanced CLI entry point with better configuration options"""
    parser = argparse.ArgumentParser(
        description='A CLI and interactive GUI for AWS cost tracking.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Text Output (Default):
    cloudsense                          # Show current month cost report
    cloudsense --days 7                 # Show 7-day cost report
    cloudsense --days 90 --hide-acct    # 90-day report, hide account number
    cloudsense --aws-region eu-west-1   # Use specific AWS region

  Web Interface:
    cloudsense --gui                    # Launch web interface
    cloudsense --gui --port 5000        # Web interface on custom port
    cloudsense --gui --host 0.0.0.0     # Web interface on all interfaces (WARNING: Security risk)

  AWS Configuration:
    cloudsense --aws-profile myprofile  # Use specific AWS profile
    cloudsense --hide-acct               # Hide AWS account number
    cloudsense --aws-region us-west-2   # Filter costs by specific region

  Advanced Examples:
    cloudsense --days 14 --log-level DEBUG     # 14-day report with debug logging
    cloudsense --force-refresh                 # Force fresh data, bypass cache
    cloudsense --gui --config production --log-level WARNING --port 80
    cloudsense --gui --aws-region us-west-2 --cache-duration 1800 --hide-acct

Security Notes:
  --host 127.0.0.1 (default): Localhost only - most secure
  --host 0.0.0.0: All interfaces - requires firewall protection
  Rate limiting protects against abuse and DoS attacks
  Input validation prevents injection attacks

Environment Variables:
  Copy .env.example to .env and customize configuration
  AWS_REGION, LOG_LEVEL, CACHE_DURATION, RATELIMIT_DEFAULT, etc.
        """
    )
    
    # Server configuration
    parser.add_argument('--host', default='127.0.0.1', 
                       help='Host to bind to (default: 127.0.0.1 for security)')
    parser.add_argument('--port', type=int, default=8080, 
                       help='Port to bind to (default: 8080)')
    parser.add_argument('--debug', action='store_true', 
                       help='Enable debug mode (development only)')
    
    # Application configuration
    parser.add_argument('--config', default='default',
                       choices=['development', 'production', 'default'],
                       help='Configuration environment (default: default)')
    parser.add_argument('--hide-acct', action='store_true', 
                       help='Hide AWS account number in interface')
    
    # AWS configuration
    parser.add_argument('--aws-region', default=None,
                       help='Filter costs by AWS region (e.g., us-east-1, global)')
    parser.add_argument('--aws-profile', default=None,
                       help='AWS profile to use (default: default)')
    
    # Logging configuration
    parser.add_argument('--log-level', default='INFO',
                       choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
                       help='Set logging level (default: INFO)')
    
    # Cache configuration
    parser.add_argument('--cache-duration', type=int, default=3600,
                       help='Cache duration in seconds (default: 3600)')
    
    # Rate limiting configuration
    parser.add_argument('--rate-limit', default=None,
                       help='Rate limit (e.g., "100 per hour", default: varies by config)')
    
    # Output mode
    parser.add_argument('--gui', action='store_true',
                       help='Launch web interface (default: text output)')
    parser.add_argument('--days', type=int, default=None,
                       help='Number of days for cost report (default: current month, text mode only)')
    parser.add_argument('--month', type=str, default=None,
                       help='Specific month for cost report (format: YYYY-MM, e.g., 2025-07, text mode only)')
    parser.add_argument('--force-refresh', action='store_true',
                       help='Force fresh data fetch, bypassing cache')
    
    # Version
    parser.add_argument('--version', action='version', version=f'CloudSense {__version__}')
    
    args = parser.parse_args()

    # Setup logging (quieter for CLI text mode)
    try:
        # For CLI text mode, default to WARNING unless user specified otherwise
        if not args.gui and args.log_level == 'INFO':
            effective_log_level = 'WARNING'
        else:
            effective_log_level = args.log_level
            
        setup_logging(effective_log_level)
        logger = logging.getLogger(__name__)
        
        # For CLI text mode, also suppress app logging to WARNING unless explicitly requested
        if not args.gui and args.log_level == 'INFO':
            logging.getLogger('cloudsense.app').setLevel(logging.WARNING)
            logging.getLogger('cloudsense').setLevel(logging.WARNING)
        
        # Only log startup for GUI mode when debug explicitly requested  
        if not args.gui and effective_log_level in ['DEBUG', 'INFO']:
            logger.info(f"Starting CloudSense with config: {args.config}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Set environment variables if provided
    # Note: aws_region is NOT set as AWS_REGION to avoid affecting API endpoint
    if args.aws_profile:
        os.environ['AWS_PROFILE'] = args.aws_profile
    if args.rate_limit:
        os.environ['RATELIMIT_DEFAULT'] = args.rate_limit
    
    os.environ['CACHE_DURATION'] = str(args.cache_duration)
    os.environ['LOG_LEVEL'] = args.log_level

    # Check if GUI mode is requested
    if args.gui:
        # GUI mode - launch web interface
        
        # Validate host for security
        if args.host == '0.0.0.0':
            logger.warning("WARNING: Binding to all interfaces (0.0.0.0) - ensure firewall is configured!")
            response = input("Continue? (y/N): ")
            if response.lower() != 'y':
                print("Aborted for security.")
                sys.exit(1)

        try:
            app = create_app(config_name=args.config, hide_account=args.hide_acct)
            # Suppress verbose logging for GUI startup unless debug mode
            if args.log_level not in ['DEBUG']:
                pass  # Don't log app creation success
            else:
                logger.info(f"CloudSense application created successfully (config: {args.config})")
        except ImportError as e:
            logger.error(f"Missing dependencies: {e}")
            print(f"Error: Missing dependencies - {e}")
            print("Try: pip install -r requirements.txt")
            sys.exit(1)
        except Exception as e:
            logger.error(f"Error creating app: {e}")
            print(f"Error creating app: {e}")
            sys.exit(1)
        
        try:
            # Suppress verbose logging for cleaner GUI output
            if args.log_level not in ['DEBUG']:
                # Suppress werkzeug and app logging during GUI operation
                werkzeug_logger = logging.getLogger('werkzeug')
                app_logger = logging.getLogger('cloudsense.app')
                cloudsense_logger = logging.getLogger('cloudsense')
                
                werkzeug_logger.setLevel(logging.ERROR)
                app_logger.setLevel(logging.WARNING)
                cloudsense_logger.setLevel(logging.WARNING)
            
            # Only log server startup in debug mode
            if args.log_level in ['DEBUG']:
                logger.info(f"Starting CloudSense server on {args.host}:{args.port} (cache duration: {args.cache_duration}s)")
                
            print(f"Starting CloudSense on http://{args.host}:{args.port}")
            print(f"Configuration: {args.config}")
            print(f"AWS Region: {os.getenv('AWS_REGION', 'us-east-1')}")
            print(f"Cache Duration: {args.cache_duration}s")
            print(f"Log Level: {args.log_level}")
            if args.hide_acct:
                print("Account number will be hidden")
            print("\nPress Ctrl+C to stop the server")
            print("-" * 50)
            
            # Show Flask info in non-debug mode
            if args.log_level not in ['DEBUG']:
                print(" * Serving Flask app 'cloudsense.app'")
                print(f" * Debug mode: {'on' if args.debug else 'off'}")
                print(f" * Running on http://{args.host}:{args.port}")
            
            # Completely suppress Flask/werkzeug startup messages in non-debug mode
            if args.log_level not in ['DEBUG']:
                # Redirect both stdout and stderr to suppress all Flask messages
                with open(os.devnull, 'w') as devnull:
                    old_stdout = sys.stdout
                    old_stderr = sys.stderr
                    sys.stdout = devnull
                    sys.stderr = devnull
                    try:
                        app.run(debug=args.debug, host=args.host, port=args.port, threaded=True, use_reloader=False)
                    finally:
                        sys.stdout = old_stdout
                        sys.stderr = old_stderr
            else:
                app.run(debug=args.debug, host=args.host, port=args.port, threaded=True, use_reloader=False)
            
        except OSError as e:
            if "Address already in use" in str(e):
                logger.error(f"Port {args.port} is already in use")
                print(f"Error: Port {args.port} is already in use. Try a different port with --port")
            elif "Permission denied" in str(e):
                logger.error(f"Permission denied for {args.host}:{args.port}")
                print(f"Error: Permission denied. Try a different port or run as administrator")
            else:
                logger.error(f"OS error starting server: {e}")
                print(f"Error starting server: {e}")
                sys.exit(1)
        except KeyboardInterrupt:
            logger.info("Server shutdown requested by user")
            print("\nShutting down CloudSense...")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Unexpected error running server: {e}")
            print(f"Error running server: {e}")
            sys.exit(1)
    else:
        # Text mode - output cost data to stdout (default)
        # Convert AWS region to filter region format
        filter_region = 'all' if not args.aws_region else args.aws_region
        
        # Validate that only one time option is specified
        if sum(bool(x) for x in [args.days, args.month]) > 1:
            print("Error: Cannot specify both --days and --month options")
            sys.exit(1)
        
        if args.month:
            # Parse and validate month format (YYYY-MM)
            try:
                from datetime import datetime
                import calendar
                
                year, month = args.month.split('-')
                year = int(year)
                month = int(month)
                
                if not (1 <= month <= 12):
                    raise ValueError("Month must be between 1 and 12")
                
                # Calculate month range
                start_of_month = datetime(year, month, 1)
                _, days_in_month = calendar.monthrange(year, month)
                end_of_month = datetime(year, month, days_in_month)
                
                output_cost_data_text(
                    days=days_in_month,
                    hide_account=args.hide_acct,
                    force_refresh=args.force_refresh,
                    filter_region=filter_region,
                    start_date=start_of_month,
                    end_date=end_of_month
                )
            except ValueError as e:
                print(f"Error: Invalid month format '{args.month}'. Use YYYY-MM format (e.g., 2025-07)")
                sys.exit(1)
        elif args.days is None:
            # Default to full current month if no options specified
            from datetime import datetime
            import calendar
            
            now = datetime.now()
            start_of_month = now.replace(day=1)
            _, days_in_month = calendar.monthrange(now.year, now.month)
            end_of_month = datetime(now.year, now.month, days_in_month)
            
            output_cost_data_text(
                days=days_in_month, 
                hide_account=args.hide_acct, 
                force_refresh=args.force_refresh, 
                filter_region=filter_region,
                start_date=start_of_month,
                end_date=end_of_month
            )
        else:
            # Use specified days
            output_cost_data_text(
                days=args.days, 
                hide_account=args.hide_acct, 
                force_refresh=args.force_refresh, 
                filter_region=filter_region
            )

if __name__ == '__main__':
    main()