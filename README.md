# CloudSense

A secure, minimal web interface for tracking AWS costs with customizable budget alerts and service breakdowns.

## Features

- **Secure AWS cost tracking** using Cost Explorer API with authentication
- **Intelligent caching** - Cost data cached for 1 hour to improve performance
- **Flexible time ranges** (7, 14, 30, 90 days, current month, previous month, custom month, specific day)
- **Budget comparison** and usage tracking with alerts
- **Daily cost trends** visualization with interactive charts
- **Detailed service breakdown** by cost with EBS/EC2 analysis
- **Responsive web interface** with real-time updates
- **Performance optimized** with AWS session caching

## Caching cost data to reduce cost 

AWS Cost Explorer API calls are $.01 for each call.

- CloudSense caches cost data for **1 hour** to reduce cost
- Cache is status displayed in the interface with last update timestamp
- Click **"Update Cost Data"** button to force refresh cached data

## Installation

**Recommended: Use a virtual environment**
```bash
# Create virtual environment
python -m venv cloudsense-env

# Activate virtual environment
source cloudsense-env/bin/activate
```

1. **Install CloudSense:**
   ```bash
   pip install cloudsense
   ```

2. **Configure AWS credentials (Required):**
   ```bash
   aws configure
   # or set environment variables:
   export AWS_ACCESS_KEY_ID=<your-key>
   export AWS_SECRET_ACCESS_KEY=<your-secret>
   export AWS_DEFAULT_REGION=us-east-1
   ```
   
   **Authentication Required**: CloudSense requires valid AWS credentials to access cost data.

3. **Run CloudSense:**
   ```bash
   cloudsense
   ```
   
   **Security Note**: By default, CloudSense binds to `127.0.0.1` (localhost only) for security.

4. **Access the interface:**
   Open http://localhost:8080 in your browser

## Command Line Options

```bash
cloudsense --help                   # Show help
cloudsense --port 5000              # Run on custom port
cloudsense --host 127.0.0.1         # Bind to specific host (default: localhost)
cloudsense --debug                  # Enable debug mode (development only)
```

**Security Options:**
- `--host 127.0.0.1` (default): Localhost only - most secure
- `--host 0.0.0.0`: All interfaces - use with caution, requires firewall

## AWS Permissions Required

Your AWS credentials need the following permissions:
```json
{
    "Version": "2012-10-17",
    "Statement": [
        {
            "Effect": "Allow",
            "Action": [
                "ce:GetCostAndUsage",
                "ce:GetUsageReport",
                "sts:GetCallerIdentity"
            ],
            "Resource": "*"
        }
    ]
}
```

**Note**: `sts:GetCallerIdentity` is required for authentication validation and account ID display.

## Customization

- **Budget Tracking**: Set custom budget amounts with usage alerts
- **Time Ranges**: Choose from multiple date ranges or select specific periods
- **Service Filtering**: View all services with meaningful costs (≥$0.0001)
- **Interactive Charts**: Line, bar, pie, and stacked charts with service breakdowns
- **Real-time Updates**: Automatic refresh with cached data optimization

## Usage

1. **Authentication**: Ensure AWS credentials are configured (required for access)
2. **Budget Setup**: Set custom budget amounts to compare against actual spending
3. **Time Selection**: Choose from multiple date ranges or select specific periods
4. **Cost Analysis**: View detailed metrics, trends, and service breakdowns
5. **Performance**: Data cached for 1 hour - use "Update Cost Data" to refresh
6. **Monitoring**: Track budget usage percentage and monthly projections

## Security Features

- **Authentication Required**: AWS credentials validated before access
- **Localhost Binding**: Secure default host configuration (127.0.0.1)
- **Updated Dependencies**: Latest Flask version with security patches
- **Error Handling**: Comprehensive error handling prevents information leakage
- **Session Caching**: Optimized AWS API usage with secure session management