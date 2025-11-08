#!/usr/bin/env python3
"""
Centralized Configuration Manager for ESP32 AI Debug System
"""

import os
import yaml
import logging
from typing import Dict, Any, Optional
from pathlib import Path
from string import Template

class ConfigManager:
    """Centralized configuration management with environment variable support"""

    _instance: Optional['ConfigManager'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls) -> 'ConfigManager':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not hasattr(self, 'initialized'):
            self.initialized = True
            self.logger = logging.getLogger(__name__)
            self._load_config()

    def _load_config(self):
        """Load configuration from YAML file with environment variable substitution"""
        config_path = Path(__file__).parent / "config.yaml"

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                raw_config = f.read()

            # Load .env file if it exists
            env_file = Path(__file__).parent.parent / ".env"
            if env_file.exists():
                with open(env_file, 'r') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#') and '=' in line:
                            key, value = line.split('=', 1)
                            os.environ[key.strip()] = value.strip()
                print(f"[DEBUG] Loaded environment from {env_file}")

            # Substitute environment variables
            template = Template(raw_config)
            substituted_config = template.safe_substitute(os.environ)

            print(f"[DEBUG] After substitution: MINIO_ACCESS_KEY='{os.environ.get('MINIO_ACCESS_KEY', 'NOT FOUND')}'")

            # Parse YAML
            self._config = yaml.safe_load(substituted_config)
            self.logger.info("Configuration loaded successfully from %s", config_path)

        except FileNotFoundError:
            self.logger.error("Configuration file not found: %s", config_path)
            raise
        except yaml.YAMLError as e:
            self.logger.error("Error parsing configuration file: %s", e)
            raise
        except Exception as e:
            self.logger.error("Error loading configuration: %s", e)
            raise

    def get(self, key_path: str, default: Any = None) -> Any:
        """
        Get configuration value using dot notation (e.g., 'redis.host')

        Args:
            key_path: Dot-separated path to configuration key
            default: Default value if key not found

        Returns:
            Configuration value or default
        """
        keys = key_path.split('.')
        value = self._config

        try:
            for key in keys:
                value = value[key]
            return value
        except (KeyError, TypeError):
            return default

    def get_section(self, section: str) -> Dict[str, Any]:
        """
        Get entire configuration section

        Args:
            section: Section name

        Returns:
            Configuration section as dictionary
        """
        return self.get(section, {})

    def get_redis_config(self) -> Dict[str, Any]:
        """Get Redis configuration with proper defaults"""
        config = self.get_section('redis')
        return {
            'host': config.get('host', 'localhost'),
            'port': config.get('port', 6379),
            'db_broker': config.get('db_broker', 0),
            'db_backend': config.get('db_backend', 1),
            'db_cache': config.get('db_cache', 2),
            'password': config.get('password'),
            'max_connections': config.get('max_connections', 10)
        }

    def get_minio_config(self) -> Dict[str, Any]:
        """Get MinIO configuration"""
        config = self.get_section('minio')

        # Handle environment variable substitution for MinIO keys
        access_key = config.get('access_key', 'minioadmin')
        secret_key = config.get('secret_key', 'minioadmin')

        # If values are still template strings, substitute them
        if isinstance(access_key, str) and access_key.startswith('${') and access_key.endswith('}'):
            var_name = access_key[2:-1].split(':')[0]  # Extract variable name from ${VAR:default}
            access_key = os.environ.get(var_name, access_key.split(':')[1] if ':' in access_key else 'minioadmin')
            print(f"[DEBUG] Substituted access_key from environment: {access_key}")

        if isinstance(secret_key, str) and secret_key.startswith('${') and secret_key.endswith('}'):
            var_name = secret_key[2:-1].split(':')[0]
            secret_key = os.environ.get(var_name, secret_key.split(':')[1] if ':' in secret_key else 'minioadmin')
            print(f"[DEBUG] Substituted secret_key from environment: {secret_key}")

        result = {
            'endpoint': config.get('endpoint', 'localhost:9000'),
            'secure': config.get('secure', False),
            'bucket': config.get('bucket', 'ble1'),
            'access_key': access_key,
            'secret_key': secret_key
        }

        # Debug print
        print(f"[DEBUG] get_minio_config() returning: access_key='{result['access_key']}', secret_key='{result['secret_key']}'")

        return result

    def get_ai_config(self) -> Dict[str, Any]:
        """Get AI service configuration"""
        config = self.get_section('ai')
        return {
            'provider': config.get('provider', 'zhipu'),
            'model': config.get('model', 'glm-4.5'),
            'api_key': config.get('api_key'),
            'timeout': config.get('timeout', 30),
            'max_retries': config.get('max_retries', 3),
            'cache_ttl': config.get('cache_ttl', 86400)
        }

    def get_processing_config(self) -> Dict[str, Any]:
        """Get processing configuration"""
        return self.get_section('processing')

    def get_esp32_config(self) -> Dict[str, Any]:
        """Get ESP32 communication configuration"""
        config = self.get_section('esp32')

        # Expand paths
        config = dict(config)  # Make a copy
        config['log_directory'] = os.path.expanduser(config.get('log_directory', './logs'))
        config['virtual_serial_dir'] = os.path.expanduser(config.get('virtual_serial_dir', '~/vserial'))
        config['virtual_serial_path'] = os.path.expanduser(config.get('virtual_serial_path', '~/vserial/ttyVLOG'))

        return config

    def get_server_config(self) -> Dict[str, Any]:
        """Get server configuration"""
        return self.get_section('server')

    def get_logging_config(self) -> Dict[str, Any]:
        """Get logging configuration"""
        config = self.get_section('logging')
        config['file'] = os.path.expanduser(config.get('file', 'logs/app.log'))
        return config

    def get_cache_config(self) -> Dict[str, Any]:
        """Get cache configuration"""
        return self.get_section('cache')

    def is_development(self) -> bool:
        """Check if running in development mode"""
        return self.get('development.test_mode', False) or self.get('server.debug', False)

    def is_production(self) -> bool:
        """Check if running in production mode"""
        return not self.is_development()

    def validate_config(self) -> bool:
        """Validate critical configuration values"""
        errors = []

        # Check required API keys
        ai_config = self.get_ai_config()
        if not ai_config.get('api_key'):
            errors.append("AI API key is required")

        # Check Redis configuration
        redis_config = self.get_redis_config()
        if not redis_config.get('host'):
            errors.append("Redis host is required")

        # Check MinIO configuration
        minio_config = self.get_minio_config()
        if not all([minio_config.get('endpoint'), minio_config.get('bucket')]):
            errors.append("MinIO endpoint and bucket are required")

        if errors:
            self.logger.error("Configuration validation failed: %s", errors)
            for error in errors:
                self.logger.error("  - %s", error)
            return False

        self.logger.info("Configuration validation passed")
        return True

    def reload(self):
        """Reload configuration from file"""
        self._load_config()
        self.logger.info("Configuration reloaded")

    def get_all_config(self) -> Dict[str, Any]:
        """Get entire configuration dictionary"""
        return self._config.copy()


# Global configuration instance
config = ConfigManager()


def get_config() -> ConfigManager:
    """Get global configuration instance"""
    return config


# Convenience functions for common use cases
def get_redis_config() -> Dict[str, Any]:
    return config.get_redis_config()


def get_minio_config() -> Dict[str, Any]:
    return config.get_minio_config()


def get_ai_config() -> Dict[str, Any]:
    return config.get_ai_config()


def get_esp32_config() -> Dict[str, Any]:
    return config.get_esp32_config()


def get_server_config() -> Dict[str, Any]:
    return config.get_server_config()


def is_development() -> bool:
    return config.is_development()


def is_production() -> bool:
    return config.is_production()