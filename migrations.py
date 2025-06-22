# DCA Admin Extension Database Migrations
# Creates all necessary tables for Dollar Cost Averaging administration
# with Lamassu ATM integration


async def m001_initial_dca_schema(db):
    """
    Create complete DCA admin schema from scratch.
    """
    # DCA Clients table
    await db.execute(
        f"""
        CREATE TABLE satmachineadmin.dca_clients (
            id TEXT PRIMARY KEY NOT NULL,
            user_id TEXT NOT NULL,
            wallet_id TEXT NOT NULL,
            username TEXT,
            dca_mode TEXT NOT NULL DEFAULT 'flow',
            fixed_mode_daily_limit INTEGER,
            status TEXT NOT NULL DEFAULT 'active',
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            updated_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
        """
    )

    # DCA Deposits table
    await db.execute(
        f"""
        CREATE TABLE satmachineadmin.dca_deposits (
            id TEXT PRIMARY KEY NOT NULL,
            client_id TEXT NOT NULL,
            amount INTEGER NOT NULL,
            currency TEXT NOT NULL DEFAULT 'GTQ',
            status TEXT NOT NULL DEFAULT 'pending',
            notes TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            confirmed_at TIMESTAMP
        );
        """
    )

    # DCA Payments table
    await db.execute(
        f"""
        CREATE TABLE satmachineadmin.dca_payments (
            id TEXT PRIMARY KEY NOT NULL,
            client_id TEXT NOT NULL,
            amount_sats INTEGER NOT NULL,
            amount_fiat INTEGER NOT NULL,
            exchange_rate REAL NOT NULL,
            transaction_type TEXT NOT NULL,
            lamassu_transaction_id TEXT,
            payment_hash TEXT,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
        """
    )

    # Lamassu Configuration table
    await db.execute(
        f"""
        CREATE TABLE satmachineadmin.lamassu_config (
            id TEXT PRIMARY KEY NOT NULL,
            host TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 5432,
            database_name TEXT NOT NULL,
            username TEXT NOT NULL,
            password TEXT NOT NULL,
            source_wallet_id TEXT,
            commission_wallet_id TEXT,
            is_active BOOLEAN NOT NULL DEFAULT true,
            test_connection_last TIMESTAMP,
            test_connection_success BOOLEAN,
            last_poll_time TIMESTAMP,
            last_successful_poll TIMESTAMP,
            use_ssh_tunnel BOOLEAN NOT NULL DEFAULT false,
            ssh_host TEXT,
            ssh_port INTEGER NOT NULL DEFAULT 22,
            ssh_username TEXT,
            ssh_password TEXT,
            ssh_private_key TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            updated_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now}
        );
        """
    )

    # Lamassu Transactions table (for audit trail)
    await db.execute(
        f"""
        CREATE TABLE satmachineadmin.lamassu_transactions (
            id TEXT PRIMARY KEY NOT NULL,
            lamassu_transaction_id TEXT NOT NULL UNIQUE,
            fiat_amount INTEGER NOT NULL,
            crypto_amount INTEGER NOT NULL,
            commission_percentage REAL NOT NULL,
            discount REAL NOT NULL DEFAULT 0.0,
            effective_commission REAL NOT NULL,
            commission_amount_sats INTEGER NOT NULL,
            base_amount_sats INTEGER NOT NULL,
            exchange_rate REAL NOT NULL,
            crypto_code TEXT NOT NULL DEFAULT 'BTC',
            fiat_code TEXT NOT NULL DEFAULT 'GTQ',
            device_id TEXT,
            transaction_time TIMESTAMP NOT NULL,
            processed_at TIMESTAMP NOT NULL DEFAULT {db.timestamp_now},
            clients_count INTEGER NOT NULL DEFAULT 0,
            distributions_total_sats INTEGER NOT NULL DEFAULT 0
        );
        """
    )


async def m002_add_transaction_time_to_dca_payments(db):
    """
    Add transaction_time field to dca_payments table to store original ATM transaction time
    """
    await db.execute(
        """
        ALTER TABLE satmachineadmin.dca_payments 
        ADD COLUMN transaction_time TIMESTAMP
        """
    )