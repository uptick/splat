# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Splat is an AWS Lambda function that renders PDFs from HTML/CSS/JS using either PrinceXML or Playwright. It's designed as a self-hosted alternative to DocRaptor.

**Key Technologies:**
- Python 3.11 runtime
- PrinceXML 14 for fast CSS-based PDF rendering
- Playwright 1.43.0 with Chromium for JavaScript-heavy pages
- Docker-based deployment to AWS Lambda
- Boto3 for S3 integration

## Development Commands

### Setup
```bash
mise run install     # Bootstrap project: install deps, setup pre-commit hooks
```

### Testing
```bash
mise run test        # Run tests in docker-compose with Lambda emulation
mise run ci:test     # Run tests in CI mode (builds first, no interactive mode)
```

### Code Quality
```bash
mise run format      # Run ruff formatter
mise run ruff-check  # Run ruff linter with auto-fix
mise run lint        # Run both format and ruff-check
```

### Local Development
```bash
mise run build       # Build docker image
mise run start       # Start local Lambda + MinIO (S3) with hot-reload

# Test with CLI (requires local server running)
./splat_cli.py -o /tmp/test.pdf -c "<h1>Hello</h1>"
./splat_cli.py -o /tmp/google.pdf -b https://google.com

# Test against deployed Lambda
./splat_cli.py -o /tmp/test.pdf -c "<h1>Hello</h1>" --function-name splat-staging
```

### Running Single Tests
```bash
docker compose --profile test run --rm -it dev pytest tests/test_lambda_e2e.py::test_check_license_returns_a_license_payload
docker compose --profile test run --rm -it dev pytest tests/test_lambda_e2e.py -k "princexml and A4"
```

## Architecture

### Lambda Handler Entry Point
**File:** `lambda_function.py:412`
- **Function:** `lambda_handler(event, context)`
- **Main Logic:** `handle_event(payload)` (no error handling, called by handler)

### Request Processing Flow
```
1. init() - Setup fonts if fonts/ directory exists
2. Pydantic validation (Payload model)
3. License check (if check_license=true)
4. create_pdf() - Generate PDF based on input source
   ├─ pdf_from_document_content() - Direct HTML string
   ├─ pdf_from_document_url() - Fetch remote HTML via requests
   └─ pdf_from_browser_url() - Visit with Playwright, extract HTML
5. deliver_pdf() - Send PDF to destination
   ├─ deliver_pdf_to_s3_bucket() - Upload to S3, return presigned URL
   ├─ deliver_pdf_to_presigned_url() - POST to external presigned URL (10 retries)
   └─ deliver_pdf_via_streaming_base64() - Base64 encode (max 5.5MB)
```

### Renderer Selection
- **PrinceXML** (`prince_handler()` at line 272): Fast, CSS-focused, optional JavaScript
  - Binary: `/var/task/prince`
  - License: `./prince-engine/license/license.dat`
  - Custom fonts via `FONTCONFIG_PATH` environment variable

- **Playwright** (`playwright_page_to_pdf()` at line 104): Full browser, JS execution
  - Launch args optimized for Lambda (30+ flags, no sandbox)
  - Network logging for debugging
  - Waits for "domcontentloaded" + "load" events
  - Emulates print media type

### Client Library (uptick_splat Package)
**Purpose:** Django/Python library for invoking Lambda

**Key Functions:**
- `configure_splat()` - Set function name, region, bucket, session
- `pdf_from_html()` - Full S3 workflow (upload HTML to temp location, invoke Lambda with document_url)
- `pdf_from_html_without_s3()` - Streaming mode (embed HTML in payload, receive base64)

**Files:**
- `uptick_splat/__init__.py` - Public API
- `uptick_splat/config.py` - Configuration with defaults
- `uptick_splat/utils.py` - Lambda invocation orchestration (150+ lines)
- `uptick_splat/logging.py` - Structured logging
- `uptick_splat/exceptions.py` - Exception definitions

## Key Code Locations

### Lambda Function
- **Payload Model:** `lambda_function.py:48` - Pydantic validation for all input params
- **PDF Creation:** `lambda_function.py:233-266` - Orchestrates create_pdf() based on input source
- **PrinceXML Handler:** `lambda_function.py:272-309` - Subprocess execution with structured logs
- **Playwright Context Manager:** `lambda_function.py:104-194` - Browser lifecycle with error handling
- **S3 Delivery with Retry:** `lambda_function.py:342-362` - POST with exponential backoff logic
- **License Check:** `lambda_function.py:368-392` - Parse PrinceXML license file

### Client Library
- **PDF Generation:** `uptick_splat/utils.py:39-98` - pdf_from_html() with S3 temp storage
- **Streaming Mode:** `uptick_splat/utils.py:101-126` - pdf_from_html_without_s3()
- **Config Management:** `uptick_splat/config.py:11-21` - Config dataclass with defaults

## Testing Strategy

### Test Files
- `tests/test_lambda_e2e.py` - End-to-end integration tests (151 lines)
  - License validation
  - Renderer matrix (princexml/playwright × A4/Letter)
  - Input sources (document_url, document_content, browser_url)
  - Output modes (presigned_url, base64, bucket_name)
  - Error handling

- `tests/utils.py` - Test helpers (MinIO S3 client, Lambda HTTP wrapper)

### Local Test Environment (docker-compose.yml)
- **lambda service:** Production-like container on port 8080
  - Watch mode: Hot-reload on `lambda_function.py` changes
  - AWS env vars configured

- **minio service:** S3-compatible storage on ports 9000 (API), 9090 (console)
  - Auto-creates "test" bucket
  - Credentials: root/password

- **dev service:** Development container with Poetry for running tests

## Build & Deployment

### Docker Multi-Stage Build (Dockerfile)
**Stage 1 (Build):**
- Base: `mcr.microsoft.com/playwright/python:v1.43.0-jammy`
- Install: gcc, cmake, libcurl for compiling dependencies
- Copy: `lambda_requirements.txt` → `/var/task`

**Stage 2 (Runtime):**
- Base: Same Playwright image
- Install: AWS Lambda RIE, PrinceXML 14.2-aws-lambda
- Copy: Custom fonts from `splat-private/fonts/` (if exists)
- Copy: License from `splat-private/license.dat` (if exists)
- Entrypoint: `/entry_script.sh lambda_function.lambda_handler`

### Private Assets (gitignored)
- `license.dat` - PrinceXML license file (place in root before build)
- `fonts.zip` - Must contain `fonts/` folder with font files (place in root before build)

### Entry Script Logic
```bash
# entry_script.sh
if [ -z "${AWS_LAMBDA_RUNTIME_API}" ]; then
  # Local: Use Lambda RIE
  exec /usr/local/bin/aws-lambda-rie /usr/bin/python -m awslambdaric $@
else
  # AWS: Use native runtime
  exec /usr/bin/python -m awslambdaric $@
fi
```

## Important Constraints

### Lambda Limits
- **Response Size:** 6MB max for base64 streaming (checked at line 318)
- **Timeout:** 10 minutes for Playwright page loads
- **Temp Storage:** `/tmp` directory, cleaned up in finally block

### S3 Presigned URL Uploads
- Retry logic: Up to 10 attempts (line 342-362)
- Handles AWS 500/503 transient failures
- No exponential backoff implemented (constant retries)

### Error Handling
- **SplatPDFGenerationFailure:** Custom exception with status codes (400, 403, 500)
- **Sentry Integration:** Automatic capture with AwsLambdaIntegration
- **Network Logging:** Playwright requests/responses logged for debugging

## Dependencies

### Production (lambda_requirements.txt)
```
requests==2.31.0
boto3==1.34.0
sentry-sdk==1.39.0
awslambdaric
pydantic
playwright==1.43.0
```

### Development (pyproject.toml)
```
python = "^3.9"  # Library supports 3.9+, Lambda uses 3.11
django = ">=3.1, <5.0.0"
boto3 = "*"
playwright = "1.43.0"
pytest = "^8.1.1"
ruff = "^0.3.7"
```

## Code Style

- **Linter:** Ruff with 120 character line length
- **Formatter:** Ruff format
- **Type Hints:** MyPy support (py.typed marker file)
- **Pre-commit Hooks:** Configured in `.pre-commit-config.yaml`

## Environment Variables

### Lambda Runtime
- `SENTRY_DSN` - Error tracking endpoint (optional)
- `FONTCONFIG_PATH` - Custom fonts directory (set by init() if fonts exist)
- `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_DEFAULT_REGION` - AWS credentials

### Local Testing
- `AWS_LAMBDA_RUNTIME_API` - Presence indicates AWS environment vs local RIE

## Common Debugging Scenarios

### Playwright Page Load Issues
- Check network logs in Sentry (automatically captured)
- Verify browser_headers are properly formatted
- Ensure target URL is publicly accessible from Lambda
- Check timeout settings (default: 10 min)

### PDF Rendering Differences
- PrinceXML: CSS-based, no JS execution by default
- Playwright: Full browser, always executes JS
- Hybrid approach: `browser_url` + `renderer: princexml` (visit with Playwright, render with PrinceXML)

### Font Issues
- Ensure `fonts.zip` contains `fonts/` folder (not root-level fonts)
- Verify FONTCONFIG_PATH is set (check init() logs)
- PrinceXML includes Liberation fonts by default

### License Expiration
- Use `{"check_license": true}` payload to check status
- Response includes: type, expiry_date, remaining_count (if limited)
- Demo mode watermarks PDFs if no valid license
