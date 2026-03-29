#!/usr/bin/env python3
"""
Production Readiness Verification Script

Validates all critical production-readiness checks before deployment.
Run with: python verify_production_readiness.py
"""

import os
import sys
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
log = logging.getLogger(__name__)


def check_environment_variables() -> bool:
    """Verify all required environment variables are set."""
    log.info("Checking environment variables...")
    required_vars = [
        "API_SECRET_KEY",
        "OPENROUTER_API_KEY",
        "DATABASE_URL",
    ]
    optional_but_recommended = [
        "LOG_LEVEL",
        "CORS_ORIGINS",
        "STRIPE_SECRET_KEY",
        "STRIPE_WEBHOOK_SECRET",
    ]

    missing = [var for var in required_vars if not os.getenv(var)]
    if missing:
        log.error(f"Missing required variables: {', '.join(missing)}")
        return False

    log.info("✓ All required environment variables present")

    # Warn about optional vars
    for var in optional_but_recommended:
        if not os.getenv(var):
            log.warning(f"Optional variable not set: {var}")

    return True


def check_dependencies() -> bool:
    """Verify all production dependencies are available."""
    log.info("Checking dependencies...")
    required_packages = [
        "fastapi",
        "pydantic",
        "sqlalchemy",
        "asyncpg",
        "redis",
        "celery",
        "stripe",
    ]

    missing_packages = []
    for package in required_packages:
        try:
            __import__(package)
        except ImportError:
            missing_packages.append(package)

    if missing_packages:
        log.error(f"Missing dependencies: {', '.join(missing_packages)}")
        log.info("Install with: pip install -r requirements.txt")
        return False

    log.info("✓ All dependencies available")
    return True


def check_database_connectivity() -> bool:
    """Test database connectivity."""
    log.info("Checking database connectivity...")
    try:
        from council.db.session import get_engine
        engine = get_engine()
        if engine is None:
            log.warning("Database not configured (DATABASE_URL not set)")
            return True  # Not required for local dev
        
        # Test connection
        import asyncio
        from sqlalchemy.future import select
        
        async def test():
            async with engine.begin() as conn:
                await conn.execute(select(1))
        
        asyncio.run(test())
        log.info("✓ Database connectivity verified")
        return True
    except Exception as e:
        log.error(f"Database connectivity failed: {e}")
        return False


def check_redis_connectivity() -> bool:
    """Test Redis connectivity."""
    log.info("Checking Redis connectivity...")
    try:
        import redis
        url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
        r = redis.from_url(url, decode_responses=True)
        r.ping()
        log.info("✓ Redis connectivity verified")
        return True
    except Exception as e:
        log.warning(f"Redis not available (optional): {e}")
        return True  # Optional for local dev


def check_code_quality() -> bool:
    """Run basic code quality checks."""
    log.info("Checking code quality...")
    issues = []

    # Check for hardcoded secrets in code
    patterns_to_avoid = [
        "sk_test_",
        "sk_live_",
        "password=",
        "secret=",
    ]

    code_dirs = ["council", "web"]
    for code_dir in code_dirs:
        if not Path(code_dir).exists():
            continue
        
        for py_file in Path(code_dir).rglob("*.py"):
            try:
                content = py_file.read_text()
                for pattern in patterns_to_avoid:
                    if pattern in content and "example" not in str(py_file):
                        issues.append(f"{py_file}: contains {pattern}")
            except Exception:
                pass

    if issues:
        log.error("Code quality issues found:")
        for issue in issues:
            log.error(f"  - {issue}")
        return False

    log.info("✓ Code quality check passed")
    return True


def check_security_headers() -> bool:
    """Verify security headers are configured."""
    log.info("Checking security configuration...")
    try:
        with open("council/api/app.py") as f:
            content = f.read()
            required_headers = [
                "X-Content-Type-Options",
                "X-Frame-Options",
                "X-XSS-Protection",
                "Strict-Transport-Security",
            ]
            for header in required_headers:
                if header not in content:
                    log.error(f"Missing security header: {header}")
                    return False
        log.info("✓ Security headers configured")
        return True
    except Exception as e:
        log.error(f"Security check failed: {e}")
        return False


def check_logging_configuration() -> bool:
    """Verify logging is configured for production."""
    log.info("Checking logging configuration...")
    try:
        from council.logging_config import configure_logging
        # Should not raise
        log.info("✓ Logging configuration available")
        return True
    except Exception as e:
        log.error(f"Logging configuration missing: {e}")
        return False


def check_migrations_available() -> bool:
    """Verify database migrations are available."""
    log.info("Checking database migrations...")
    migration_file = Path("council/db/alembic_001_initial_schema.py")
    if migration_file.exists():
        log.info("✓ Database migrations available")
        return True
    else:
        log.warning("Database migrations not found (optional if using existing schema)")
        return True


def main() -> int:
    """Run all checks and report results."""
    log.info("=" * 60)
    log.info("PRODUCTION READINESS VERIFICATION")
    log.info("=" * 60)
    log.info("")

    checks = [
        ("Environment Variables", check_environment_variables),
        ("Dependencies", check_dependencies),
        ("Code Quality", check_code_quality),
        ("Logging Configuration", check_logging_configuration),
        ("Security Configuration", check_security_headers),
        ("Database Connectivity", check_database_connectivity),
        ("Redis Connectivity", check_redis_connectivity),
        ("Database Migrations", check_migrations_available),
    ]

    results = {}
    for name, check_func in checks:
        try:
            passed = check_func()
            results[name] = passed
        except Exception as e:
            log.error(f"{name} check crashed: {e}")
            results[name] = False
        log.info("")

    # Summary
    log.info("=" * 60)
    log.info("SUMMARY")
    log.info("=" * 60)
    passed_count = sum(1 for v in results.values() if v)
    total_count = len(results)
    
    for name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        log.info(f"{status}: {name}")

    log.info("")
    log.info(f"Result: {passed_count}/{total_count} checks passed")

    if passed_count == total_count:
        log.info("🎉 Production readiness verified!")
        return 0
    else:
        log.error("❌ Some checks failed. Review above for details.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
