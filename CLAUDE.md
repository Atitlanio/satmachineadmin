# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is the **Satoshi Machine Admin Extension** for LNBits - a Dollar Cost Averaging (DCA) administration system that integrates with Lamassu ATM machines to automatically distribute Bitcoin to registered clients based on their deposit balances.

## Development Commands

### Code Quality & Formatting
```bash
# Format all code
make format

# Check code quality
make check

# Individual commands
poetry run black .                    # Python formatting
poetry run ruff check . --fix         # Python linting with auto-fix
poetry run ./node_modules/.bin/prettier --write .  # JavaScript formatting
poetry run mypy .                     # Python type checking
poetry run ./node_modules/.bin/pyright # JavaScript type checking
```

### Testing
```bash
# Run tests
make test
# or
PYTHONUNBUFFERED=1 DEBUG=true poetry run pytest
```

### Pre-commit Hooks
```bash
# Install pre-commit hooks
make install-pre-commit-hook

# Run pre-commit on all files
make pre-commit
```

## Architecture

### Core Structure
The Satoshi Machine Admin extension follows LNBits architecture patterns:

- **Backend (Python/FastAPI)**:
  - `__init__.py` - Extension initialization and router setup
  - `models.py` - Pydantic data models for DCA system
  - `crud.py` - Database operations for all DCA entities
  - `views.py` - Admin dashboard page route
  - `views_api.py` - DCA API endpoints
  - `migrations.py` - Database schema (condensed single migration)
  - `tasks.py` - Background polling and invoice listening
  - `transaction_processor.py` - Core Lamassu integration logic

- **Frontend (Vue.js 3 Options API + Quasar)**:
  - `static/js/index.js` - Admin dashboard Vue app
  - `templates/myextension/index.html` - Admin interface template

### Key Conventions

1. **Template Syntax Rules**:
   - Use `{{ }}` and `{% %}` ONLY in `index.html` files (Jinja2)
   - In Vue components: Use `v-text='value'` instead of `{{ value }}`
   - Use `:attribute='value'` for binding, `v-html='value'` for HTML content

2. **API Patterns**:
   - Admin extension uses session-based superuser authentication (no API keys)
   - Client extension uses wallet admin keys for user-specific operations  
   - Use `LNbits.api.request()` for all API calls
   - Destructure responses: `const {data} = await LNbits.api.request(...)`

3. **Component Registration**:
   - Templates must be included BEFORE scripts in HTML
   - Components must be registered BEFORE app.mount()

### The Magical G Object
The global `this.g` object provides access to:
- `this.g.user` - Complete user data including wallets array
- `this.g.user.wallets[0].inkey` - Invoice key (client extension only)
- `this.g.user.wallets[0].adminkey` - Admin key (client extension only)
- `this.g.wallet` - Currently selected wallet

**Note**: Admin extension uses superuser session authentication, not wallet keys.

### Built-in Utilities
- Currency conversion: `/api/v1/currencies`, `/api/v1/conversion`
- QR code generation: `/api/v1/qrcode/{data}` or Quasar VueQrcode component
- WebSocket support: `wss://host/api/v1/ws/{id}` with POST to `/api/v1/ws/{id}/{data}`

## Configuration Files

- `config.json` - Extension configuration (name: "DCA Admin")
- `manifest.json` - Extension manifest for installation
- `pyproject.toml` - Python dependencies and tool configuration
- `package.json` - JavaScript dependencies

## DCA System Architecture

### Core Components

#### **1. Lamassu ATM Integration**
- Secure SSH connection to remote Lamassu PostgreSQL database
- Polls `cash_out_txs` table for new confirmed transactions
- Supports both SSH password and private key authentication
- Read-only database access for security

#### **2. Commission Calculation Engine**
- Formula: `base_amount = total_amount / (1 + effective_commission)`
- Effective commission: `commission_percentage * (100 - discount) / 100`
- Supports discount percentages for promotional rates
- Separates commission earnings to configurable wallet

#### **3. DCA Distribution System**
- **Flow Mode**: Proportional distribution based on client balance ratios
- **Fixed Mode**: Daily limit-based allocation (future enhancement)
- Automatic Bitcoin transfers using LNBits internal payment system
- Real-time balance tracking and deduction

#### **4. Audit and Compliance**
- Complete transaction audit trail in `lamassu_transactions` table
- Detailed distribution records in `dca_payments` table
- Clickable transaction history with distribution breakdowns
- CSV export capabilities for accounting

### Database Schema

**Core Tables:**
- `dca_clients` - Client registration and DCA mode settings
- `dca_deposits` - Fiat deposit tracking and confirmation workflow
- `dca_payments` - Bitcoin payment records and status tracking
- `lamassu_config` - Database connection and polling configuration
- `lamassu_transactions` - Complete audit trail of processed ATM transactions

**Key Features:**
- Single migration (`m001_initial_dca_schema`) creates complete schema
- UTC timezone handling throughout
- Comprehensive indexing for performance
- Foreign key relationships maintained

### API Endpoints

#### **Client Management**
- `GET /api/v1/dca/clients` - List all DCA clients
- `GET /api/v1/dca/clients/{id}/balance` - Get client balance summary
- `POST /api/v1/dca/clients` - Create test client (development)

#### **Deposit Administration**
- `GET /api/v1/dca/deposits` - List all deposits
- `POST /api/v1/dca/deposits` - Create new deposit
- `PUT /api/v1/dca/deposits/{id}/status` - Confirm deposits

#### **Transaction Processing**
- `GET /api/v1/dca/transactions` - List processed Lamassu transactions
- `GET /api/v1/dca/transactions/{id}/distributions` - View distribution details
- `POST /api/v1/dca/manual-poll` - Trigger manual database poll
- `POST /api/v1/dca/test-transaction` - Process test transaction

#### **Configuration**
- `GET /api/v1/dca/config` - Get Lamassu database configuration
- `POST /api/v1/dca/config` - Save database and wallet settings
- `POST /api/v1/dca/test-connection` - Verify connectivity

### Frontend Architecture

#### **Vue.js Components**
- **Dashboard Overview** - System status and recent activity
- **Client Management** - DCA client table with balance tracking
- **Deposit Workflow** - Quick deposit forms and confirmation
- **Transaction History** - Lamassu transaction audit with drill-down
- **Configuration Panel** - Database and wallet setup with testing

#### **Key UX Features**
- Real-time balance updates during polling
- Loading states for all async operations
- Error handling with user-friendly notifications
- Responsive design for mobile administration
- Export functionality for audit and compliance

## Technical Implementation Details

### SSH Connection Setup
```bash
# On Lamassu server:
sudo mkdir -p /var/lib/postgresql/.ssh
sudo echo "your-public-key" >> /var/lib/postgresql/.ssh/authorized_keys
sudo chown -R postgres:postgres /var/lib/postgresql/.ssh
sudo chmod 700 /var/lib/postgresql/.ssh
sudo chmod 600 /var/lib/postgresql/.ssh/authorized_keys
```

### Commission Calculation Example
```python
# Real transaction: 2000 GTQ → 266,800 sats (3% commission, 0% discount)
crypto_atoms = 266800  # Total sats from Lamassu
commission_percentage = 0.03  # 3%
discount = 0.0  # No discount

effective_commission = 0.03 * (100 - 0) / 100 = 0.03
base_amount = 266800 / (1 + 0.03) = 258,835 sats (for DCA)
commission_amount = 266800 - 258835 = 7,965 sats (to commission wallet)
```

### Polling Strategy
- **Automatic**: Hourly background task via LNBits task system
- **Manual**: Admin-triggered polling for immediate processing
- **Smart Recovery**: Tracks last successful poll to prevent missed transactions
- **Error Handling**: Graceful failure with detailed logging

### Security Considerations
- **Superuser Authentication**: Admin extension requires LNBits superuser login
- **Wallet Admin Keys**: Client extension uses wallet admin keys for user operations
- **Database Access**: Only superusers can write to satoshimachine database
- SSH tunnel encryption for database connectivity
- Read-only database permissions for Lamassu access
- Input sanitization and type validation
- Audit logging for all administrative actions

## Development Workflow

### Adding New Features
1. **Models**: Update `models.py` with new Pydantic schemas
2. **Database**: Add migration to `migrations.py` (append only)
3. **CRUD**: Implement database operations in `crud.py`
4. **API**: Add endpoints to `views_api.py`
5. **Frontend**: Update Vue.js components in `static/js/index.js`
6. **Templates**: Modify HTML template if needed

### Testing
- Use "Test Connection" for database connectivity verification
- Use "Test Transaction" for DCA flow validation
- Manual polling for real-world transaction testing
- Monitor LNBits logs for detailed error information

### Debugging
- Enable debug logging: `DEBUG=true`
- Check SSH tunnel connectivity independently
- Verify Lamassu database query results
- Monitor wallet balance changes
- Review transaction audit trail

## Key Files Reference

- `transaction_processor.py` - Core Lamassu integration and DCA logic
- `models.py` - Complete data models for DCA system
- `crud.py` - Database operations with optimized queries
- `migrations.py` - Single condensed schema migration
- `static/js/index.js` - Admin dashboard Vue.js application
- `templates/myextension/index.html` - Admin interface template
- `config.json` - Extension metadata and configuration
- `tasks.py` - Background polling and invoice listeners

## Important Notes

- Extension uses LNBits internal payment system for Bitcoin transfers
- All timestamps stored and processed in UTC timezone
- Commission calculations handle edge cases and rounding
- SSH authentication prefers private keys over passwords
- Database polling is stateful and resumable after downtime
- UI displays human-readable usernames where available
- Export functions generate CSV files for external analysis

## Extension Status

**Current Version**: v0.0.1 (Initial Release)  
**Status**: Production Ready  
**Dependencies**: LNBits v1.0.0+, SSH access to Lamassu server  
**License**: MIT