"""Configuration classes for CloudSense application"""

import os
import logging


class Config:
    """Base configuration class"""
    
    # AWS Configuration
    AWS_REGION = os.getenv('AWS_REGION', 'us-east-1')
    AWS_PROFILE = os.getenv('AWS_PROFILE', 'default')
    
    # Application Configuration
    SECRET_KEY = os.getenv('SECRET_KEY', 'dev-key-change-in-production-please')
    DEBUG = os.getenv('FLASK_DEBUG', 'False').lower() == 'true'
    
    # Cache Configuration
    CACHE_DURATION = int(os.getenv('CACHE_DURATION', 3600))  # 1 hour default
    
    # Server Configuration
    HOST = os.getenv('HOST', '127.0.0.1')
    PORT = int(os.getenv('PORT', 8080))
    
    # Rate Limiting Configuration
    RATELIMIT_STORAGE_URL = os.getenv('RATELIMIT_STORAGE_URL', 'memory://')
    RATELIMIT_DEFAULT = os.getenv('RATELIMIT_DEFAULT', '100 per hour')
    
    # Logging Configuration
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO')
    LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    
    # Validation Configuration
    MAX_DAYS_RANGE = int(os.getenv('MAX_DAYS_RANGE', 365))
    MIN_DAYS_RANGE = int(os.getenv('MIN_DAYS_RANGE', 1))
    
    # Security Configuration
    HIDE_ACCOUNT = os.getenv('HIDE_ACCOUNT', 'False').lower() == 'true'
    
    @staticmethod
    def init_app(app):
        """Initialize application with this config"""
        # Set up logging
        logging.basicConfig(
            level=getattr(logging, Config.LOG_LEVEL.upper()),
            format=Config.LOG_FORMAT
        )
        
        # Reduce AWS SDK logging noise unless in DEBUG mode
        if Config.LOG_LEVEL.upper() != 'DEBUG':
            logging.getLogger('botocore').setLevel(logging.WARNING)
            logging.getLogger('boto3').setLevel(logging.WARNING)
            logging.getLogger('urllib3').setLevel(logging.WARNING)


class DevelopmentConfig(Config):
    """Development configuration"""
    DEBUG = True
    LOG_LEVEL = 'DEBUG'
    RATELIMIT_DEFAULT = '1000 per hour'  # More lenient for development


class ProductionConfig(Config):
    """Production configuration"""
    DEBUG = False
    SECRET_KEY = os.getenv('SECRET_KEY')
    LOG_LEVEL = 'WARNING'
    RATELIMIT_DEFAULT = '50 per hour'  # More restrictive for production
    
    @classmethod
    def init_app(cls, app):
        Config.init_app(app)
        
        # Log to file in production
        import logging
        from logging.handlers import RotatingFileHandler
        
        if not app.debug:
            file_handler = RotatingFileHandler(
                'cloudsense.log', maxBytes=10240, backupCount=10
            )
            file_handler.setFormatter(logging.Formatter(cls.LOG_FORMAT))
            file_handler.setLevel(logging.INFO)
            app.logger.addHandler(file_handler)


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}
