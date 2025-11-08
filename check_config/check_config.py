#!/usr/bin/env python3
"""
Configuration Check Script for ESP32 AI Debug System
"""

import sys
import os
from pathlib import Path

def check_dependencies():
    """Check if required Python packages are installed"""
    required_packages = ['yaml', 'dotenv', 'redis', 'minio', 'fastapi', 'celery']
    missing_packages = []

    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        print("❌ Missing required packages:")
        for package in missing_packages:
            print(f"   - {package}")
        print("\n📦 Install with:")
        print("   pip install -r requirements.txt")
        return False
    else:
        print("✅ All required packages are installed")
        return True

def check_config_files():
    """Check if configuration files exist"""
    required_files = ['config.yaml', '.env']
    missing_files = []

    for file_name in required_files:
        if not Path(file_name).exists():
            missing_files.append(file_name)

    if missing_files:
        print("❌ Missing configuration files:")
        for file_name in missing_files:
            print(f"   - {file_name}")

        if '.env' in missing_files:
            print("\n💡 Create .env file:")
            print("   cp .env.example .env")
            print("   # Then edit .env with your actual values")
        return False
    else:
        print("✅ All configuration files exist")
        return True

def check_environment_variables():
    """Check critical environment variables"""
    config_manager = None
    try:
        from config_manager import ConfigManager
        config_manager = ConfigManager()
    except Exception as e:
        print(f"❌ Failed to load configuration: {e}")
        return False

    # Check if configuration validation passes
    if config_manager.validate_config():
        print("✅ Configuration validation passed")
        return True
    else:
        print("❌ Configuration validation failed")
        return False

def check_services():
    """Check service configuration validity (without testing connections)"""
    try:
        from config_manager import get_config
        config = get_config()

        # Check Redis configuration
        redis_config = config.get_redis_config()
        if all([
            redis_config.get('host'),
            redis_config.get('port'),
            isinstance(redis_config.get('port'), int),
            redis_config.get('db_broker') is not None,
            redis_config.get('db_backend') is not None,
            redis_config.get('db_cache') is not None
        ]):
            print("✅ Redis configuration is valid")
            print(f"   Host: {redis_config['host']}:{redis_config['port']}")
            print(f"   Databases: broker={redis_config['db_broker']}, backend={redis_config['db_backend']}, cache={redis_config['db_cache']}")
        else:
            print("❌ Redis configuration is invalid")
            return False

        # Check MinIO configuration
        minio_config = config.get_minio_config()
        if all([
            minio_config.get('endpoint'),
            minio_config.get('bucket'),
            minio_config.get('access_key'),
            minio_config.get('secret_key')
        ]):
            print("✅ MinIO configuration is valid")
            print(f"   Endpoint: {minio_config['endpoint']}")
            print(f"   Bucket: {minio_config['bucket']}")
            print(f"   Access Key: {minio_config['access_key'][:8]}...")
        else:
            print("❌ MinIO configuration is invalid")
            return False

        # Check AI configuration
        ai_config = config.get_ai_config()
        if all([
            ai_config.get('provider'),
            ai_config.get('model'),
            ai_config.get('api_key')
        ]):
            print("✅ AI service configuration is valid")
            print(f"   Provider: {ai_config['provider']}")
            print(f"   Model: {ai_config['model']}")
            print(f"   API Key: {ai_config['api_key'][:10]}...")
        else:
            print("❌ AI service configuration is invalid")
            return False

        return True

    except Exception as e:
        print(f"❌ Service configuration check failed: {e}")
        return False

def main():
    """Main configuration check function"""
    print("🔍 ESP32 AI Debug System Configuration Check")
    print("=" * 50)

    checks = [
        ("Dependencies", check_dependencies),
        ("Configuration Files", check_config_files),
        ("Environment Variables", check_environment_variables),
        ("Services", check_services)
    ]

    all_passed = True

    for check_name, check_func in checks:
        print(f"\n📋 Checking {check_name}...")
        try:
            if not check_func():
                all_passed = False
        except Exception as e:
            print(f"❌ {check_name} check failed with error: {e}")
            all_passed = False

    print("\n" + "=" * 50)
    if all_passed:
        print("🎉 Configuration validation passed!")
        print("\n📝 Next steps:")
        print("   1. Start required services:")
        print("      - Redis: sudo docker run -d --name redis -p 6379:6379 redis:alpine")
        print("      - MinIO: ./setup_docker.sh")
        print("   2. Start the application:")
        print("      cd fastapi && python -m uvicorn fastapi_app:app --reload")
        print("   3. Run ESP32 debug:")
        print("      ./flash_auto.sh /dev/ttyUSB0")
        return 0
    else:
        print("❌ Configuration validation failed. Please fix the issues above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())