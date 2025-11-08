# ESP32 AI Debug System - Configuration Guide

## Overview

The ESP32 AI Debug System now uses centralized configuration management to make it easier to manage settings across different environments.

## Configuration Files

### 1. `config.yaml` - Main Configuration

This is the main configuration file that contains all system settings. It uses environment variable substitution for sensitive values.

Key sections:
- **server**: FastAPI server settings
- **redis**: Redis connection configuration
- **minio**: MinIO object storage settings
- **ai**: AI service configuration
- **esp32**: ESP32 communication settings
- **processing**: Log processing parameters
- **cache**: Caching strategy settings
- **logging**: Logging configuration

### 2. `.env` - Environment Variables

Copy from template and customize:

```bash
cp .env.example .env
```

Edit `.env` with your actual values:
```bash
# MinIO Configuration
MINIO_ACCESS_KEY=your-access-key
MINIO_SECRET_KEY=your-secret-key

# AI Service Configuration
ZHIPU_API_KEY=your-zhipu-api-key
```

## Quick Start

### 1. Check Configuration

Run the configuration checker:
```bash
python3 check_config.py
```

This will verify:
- Required packages are installed
- Configuration files exist
- Environment variables are set
- Services are accessible

### 2. Setup Services

```bash
# Setup MinIO container
./setup_docker.sh

# Start the application
cd fastapi
python -m uvicorn fastapi_app:app --reload
```

## Configuration Management

### Using the Config Manager

```python
from config_manager import get_config

config = get_config()

# Get specific configuration
redis_config = config.get_redis_config()
minio_config = config.get_minio_config()
ai_config = config.get_ai_config()

# Get any value using dot notation
port = config.get('server.port', 8000)
debug = config.get('server.debug', False)
```

### Environment Variable Substitution

In `config.yaml`, you can use environment variables:
```yaml
minio:
  access_key: "${MINIO_ACCESS_KEY:minioadmin}"  # Use MINIO_ACCESS_KEY or default to 'minioadmin'
  secret_key: "${MINIO_SECRET_KEY:minioadmin}"

ai:
  api_key: "${ZHIPU_API_KEY}"  # Required, no default
```

## Configuration by Section

### Server Configuration
```yaml
server:
  host: "0.0.0.0"              # Server bind address
  port: 8000                   # Server port
  debug: false                 # Debug mode
  cors_origins: ["*"]          # CORS allowed origins
```

### Redis Configuration
```yaml
redis:
  host: "localhost"            # Redis server host
  port: 6379                   # Redis server port
  db_broker: 0                 # Database for Celery broker
  db_backend: 1                # Database for Celery backend
  db_cache: 2                  # Database for caching
  password: null               # Redis password (optional)
  max_connections: 10          # Maximum connection pool size
```

### AI Configuration
```yaml
ai:
  provider: "zhipu"            # AI provider: zhipu, openai, deepseek
  model: "glm-4.5"             # AI model to use
  api_key: "${ZHIPU_API_KEY}" # API key from environment
  timeout: 30                  # Request timeout in seconds
  max_retries: 3               # Maximum retry attempts
  cache_ttl: 86400             # Cache TTL in seconds (24 hours)
```

### ESP32 Configuration
```yaml
esp32:
  default_baud_rate: 115200    # Default serial baud rate
  timeout_no_log: 20           # Timeout without logs (seconds)
  virtual_serial_dir: "~/vserial"  # Virtual serial port directory
  virtual_serial_path: "~/vserial/ttyVLOG"  # Virtual serial port path
  log_directory: "./logs"      # Log file directory
  max_log_file_size: "100MB"   # Maximum log file size
```

### Processing Configuration
```yaml
processing:
  chunk_size:                  # Chunk sizes based on file length
    very_large: 100           # >2000 lines
    large: 75                 # 1000-2000 lines
    medium: 50                # 500-1000 lines
    small: 25                 # 200-500 lines
    very_small: 15            # <200 lines

  max_workers:                 # Number of parallel workers
    very_large: 12
    large: 10
    medium: 8
    small: 6
    very_small: 4
```

## Environment-Specific Configurations

### Development Environment
```bash
# .env for development
DEVELOPMENT_TEST_MODE=true
DEVELOPMENT_MOCK_AI_RESPONSES=false
SERVER_DEBUG=true
SERVER_HOST=127.0.0.1
```

### Production Environment
```bash
# .env for production
SERVER_DEBUG=false
SERVER_HOST=0.0.0.0
LOGGING_LEVEL=WARNING
SECURITY_ENABLE_AUTH=true
```

## Validation

The configuration manager includes automatic validation:

- Required API keys must be present
- Connection parameters must be valid
- File paths must be accessible
- Port numbers must be valid

Run validation manually:
```python
from config_manager import get_config

config = get_config()
if config.validate_config():
    print("Configuration is valid!")
else:
    print("Configuration has errors")
```

## Troubleshooting

### Configuration Not Loading
1. Check if `config.yaml` exists
2. Verify YAML syntax is correct
3. Check file permissions

### Environment Variables Not Working
1. Ensure `.env` file exists
2. Check environment variable names
3. Use `export VAR=value` or set in `.env`

### Service Connection Issues
1. Run `python3 check_config.py`
2. Verify services are running
3. Check network connectivity
4. Validate credentials

## Best Practices

1. **Never commit `.env` files** to version control
2. **Use environment-specific configs** for different deployments
3. **Run configuration validation** on startup
4. **Use descriptive names** for configuration keys
5. **Document custom configuration** values
6. **Use the configuration checker** before deployment

## Migration from Old Configuration

If you're upgrading from an older version:

1. Backup your current configuration
2. Copy `config.yaml` to your project
3. Create `.env` from `.env.example`
4. Move your environment variables to `.env`
5. Update your scripts to use the new config manager
6. Run `python3 check_config.py` to verify

## Examples

### Custom Configuration
```python
from config_manager import get_config

config = get_config()

# Get custom settings
custom_setting = config.get('my_app.custom_key', 'default_value')

# Override configuration (temporary)
config._config['my_app.new_key'] = 'new_value'
```

### Environment-Specific Setup
```bash
# Development
export CONFIG_ENV=development
python app.py

# Production
export CONFIG_ENV=production
python app.py
```