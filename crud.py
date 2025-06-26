# Description: This file contains the CRUD operations for talking to the database.

from typing import List, Optional, Union
from datetime import datetime, timezone

from lnbits.db import Database
from lnbits.helpers import urlsafe_short_hash

from .models import (
    CreateDcaClientData, DcaClient, UpdateDcaClientData,
    CreateDepositData, DcaDeposit, UpdateDepositStatusData,
    CreateDcaPaymentData, DcaPayment,
    ClientBalanceSummary,
    CreateLamassuConfigData, LamassuConfig, UpdateLamassuConfigData,
    CreateLamassuTransactionData, StoredLamassuTransaction
)

db = Database("ext_satoshimachine")


# DCA Client CRUD Operations
async def create_dca_client(data: CreateDcaClientData) -> DcaClient:
    client_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO satoshimachine.dca_clients 
        (id, user_id, wallet_id, username, dca_mode, fixed_mode_daily_limit, status, created_at, updated_at)
        VALUES (:id, :user_id, :wallet_id, :username, :dca_mode, :fixed_mode_daily_limit, :status, :created_at, :updated_at)
        """,
        {
            "id": client_id,
            "user_id": data.user_id,
            "wallet_id": data.wallet_id,
            "username": data.username,
            "dca_mode": data.dca_mode,
            "fixed_mode_daily_limit": data.fixed_mode_daily_limit,
            "status": "active",
            "created_at": datetime.now(),
            "updated_at": datetime.now()
        }
    )
    return await get_dca_client(client_id)


async def get_dca_client(client_id: str) -> Optional[DcaClient]:
    return await db.fetchone(
        "SELECT * FROM satoshimachine.dca_clients WHERE id = :id",
        {"id": client_id},
        DcaClient,
    )


async def get_dca_clients() -> List[DcaClient]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_clients ORDER BY created_at DESC",
        model=DcaClient,
    )


async def get_dca_client_by_user(user_id: str) -> Optional[DcaClient]:
    return await db.fetchone(
        "SELECT * FROM satoshimachine.dca_clients WHERE user_id = :user_id",
        {"user_id": user_id},
        DcaClient,
    )


async def update_dca_client(client_id: str, data: UpdateDcaClientData) -> Optional[DcaClient]:
    update_data = {k: v for k, v in data.dict().items() if v is not None}
    if not update_data:
        return await get_dca_client(client_id)
    
    update_data["updated_at"] = datetime.now()
    set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
    update_data["id"] = client_id
    
    await db.execute(
        f"UPDATE satoshimachine.dca_clients SET {set_clause} WHERE id = :id",
        update_data
    )
    return await get_dca_client(client_id)


async def delete_dca_client(client_id: str) -> None:
    await db.execute(
        "DELETE FROM satoshimachine.dca_clients WHERE id = :id", 
        {"id": client_id}
    )


# DCA Deposit CRUD Operations
async def create_deposit(data: CreateDepositData) -> DcaDeposit:
    deposit_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO satoshimachine.dca_deposits 
        (id, client_id, amount, currency, status, notes, created_at)
        VALUES (:id, :client_id, :amount, :currency, :status, :notes, :created_at)
        """,
        {
            "id": deposit_id,
            "client_id": data.client_id,
            "amount": data.amount,
            "currency": data.currency,
            "status": "pending",
            "notes": data.notes,
            "created_at": datetime.now()
        }
    )
    return await get_deposit(deposit_id)


async def get_deposit(deposit_id: str) -> Optional[DcaDeposit]:
    return await db.fetchone(
        "SELECT * FROM satoshimachine.dca_deposits WHERE id = :id",
        {"id": deposit_id},
        DcaDeposit,
    )


async def get_deposits_by_client(client_id: str) -> List[DcaDeposit]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_deposits WHERE client_id = :client_id ORDER BY created_at DESC",
        {"client_id": client_id},
        DcaDeposit,
    )


async def get_all_deposits() -> List[DcaDeposit]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_deposits ORDER BY created_at DESC",
        model=DcaDeposit,
    )


async def update_deposit_status(deposit_id: str, data: UpdateDepositStatusData) -> Optional[DcaDeposit]:
    update_data = {
        "status": data.status,
        "notes": data.notes
    }
    
    if data.status == "confirmed":
        update_data["confirmed_at"] = datetime.now()
    
    set_clause = ", ".join([f"{k} = :{k}" for k, v in update_data.items() if v is not None])
    filtered_data = {k: v for k, v in update_data.items() if v is not None}
    filtered_data["id"] = deposit_id
    
    await db.execute(
        f"UPDATE satoshimachine.dca_deposits SET {set_clause} WHERE id = :id",
        filtered_data
    )
    return await get_deposit(deposit_id)


# DCA Payment CRUD Operations
async def create_dca_payment(data: CreateDcaPaymentData) -> DcaPayment:
    payment_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO satoshimachine.dca_payments 
        (id, client_id, amount_sats, amount_fiat, exchange_rate, transaction_type, 
         lamassu_transaction_id, payment_hash, status, created_at, transaction_time)
        VALUES (:id, :client_id, :amount_sats, :amount_fiat, :exchange_rate, :transaction_type,
                :lamassu_transaction_id, :payment_hash, :status, :created_at, :transaction_time)
        """,
        {
            "id": payment_id,
            "client_id": data.client_id,
            "amount_sats": data.amount_sats,
            "amount_fiat": data.amount_fiat,
            "exchange_rate": data.exchange_rate,
            "transaction_type": data.transaction_type,
            "lamassu_transaction_id": data.lamassu_transaction_id,
            "payment_hash": data.payment_hash,
            "status": "pending",
            "created_at": datetime.now(),
            "transaction_time": data.transaction_time
        }
    )
    return await get_dca_payment(payment_id)


async def get_dca_payment(payment_id: str) -> Optional[DcaPayment]:
    return await db.fetchone(
        "SELECT * FROM satoshimachine.dca_payments WHERE id = :id",
        {"id": payment_id},
        DcaPayment,
    )


async def get_payments_by_client(client_id: str) -> List[DcaPayment]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_payments WHERE client_id = :client_id ORDER BY created_at DESC",
        {"client_id": client_id},
        DcaPayment,
    )


async def get_all_payments() -> List[DcaPayment]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_payments ORDER BY created_at DESC",
        model=DcaPayment,
    )


async def update_dca_payment_status(payment_id: str, status: str) -> None:
    """Update the status of a DCA payment"""
    await db.execute(
        "UPDATE satoshimachine.dca_payments SET status = :status WHERE id = :id",
        {"status": status, "id": payment_id}
    )


async def get_payments_by_lamassu_transaction(lamassu_transaction_id: str) -> List[DcaPayment]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_payments WHERE lamassu_transaction_id = :transaction_id",
        {"transaction_id": lamassu_transaction_id},
        DcaPayment,
    )


# Balance and Summary Operations
async def get_client_balance_summary(client_id: str) -> ClientBalanceSummary:
    # Get total confirmed deposits
    total_deposits_result = await db.fetchone(
        """
        SELECT COALESCE(SUM(amount), 0) as total, currency 
        FROM satoshimachine.dca_deposits 
        WHERE client_id = :client_id AND status = 'confirmed'
        GROUP BY currency
        """,
        {"client_id": client_id}
    )
    
    # Get total payments made
    total_payments_result = await db.fetchone(
        """
        SELECT COALESCE(SUM(amount_fiat), 0) as total 
        FROM satoshimachine.dca_payments 
        WHERE client_id = :client_id AND status = 'confirmed'
        """,
        {"client_id": client_id}
    )
    
    total_deposits = total_deposits_result["total"] if total_deposits_result else 0
    total_payments = total_payments_result["total"] if total_payments_result else 0
    currency = total_deposits_result["currency"] if total_deposits_result else "GTQ"
    
    return ClientBalanceSummary(
        client_id=client_id,
        total_deposits=total_deposits,
        total_payments=total_payments,
        remaining_balance=total_deposits - total_payments,
        currency=currency
    )


async def get_flow_mode_clients() -> List[DcaClient]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_clients WHERE dca_mode = 'flow' AND status = 'active'",
        model=DcaClient,
    )


async def get_fixed_mode_clients() -> List[DcaClient]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.dca_clients WHERE dca_mode = 'fixed' AND status = 'active'",
        model=DcaClient,
    )


# Lamassu Configuration CRUD Operations
async def create_lamassu_config(data: CreateLamassuConfigData) -> LamassuConfig:
    config_id = urlsafe_short_hash()
    
    # Deactivate any existing configs first (only one active config allowed)
    await db.execute(
        "UPDATE satoshimachine.lamassu_config SET is_active = false, updated_at = :updated_at",
        {"updated_at": datetime.now()}
    )
    
    await db.execute(
        """
        INSERT INTO satoshimachine.lamassu_config 
        (id, host, port, database_name, username, password, source_wallet_id, commission_wallet_id, is_active, created_at, updated_at,
         use_ssh_tunnel, ssh_host, ssh_port, ssh_username, ssh_password, ssh_private_key)
        VALUES (:id, :host, :port, :database_name, :username, :password, :source_wallet_id, :commission_wallet_id, :is_active, :created_at, :updated_at,
                :use_ssh_tunnel, :ssh_host, :ssh_port, :ssh_username, :ssh_password, :ssh_private_key)
        """,
        {
            "id": config_id,
            "host": data.host,
            "port": data.port,
            "database_name": data.database_name,
            "username": data.username,
            "password": data.password,
            "source_wallet_id": data.source_wallet_id,
            "commission_wallet_id": data.commission_wallet_id,
            "is_active": True,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),
            "use_ssh_tunnel": data.use_ssh_tunnel,
            "ssh_host": data.ssh_host,
            "ssh_port": data.ssh_port,
            "ssh_username": data.ssh_username,
            "ssh_password": data.ssh_password,
            "ssh_private_key": data.ssh_private_key
        }
    )
    return await get_lamassu_config(config_id)


async def get_lamassu_config(config_id: str) -> Optional[LamassuConfig]:
    return await db.fetchone(
        "SELECT * FROM satoshimachine.lamassu_config WHERE id = :id",
        {"id": config_id},
        LamassuConfig,
    )


async def get_active_lamassu_config() -> Optional[LamassuConfig]:
    return await db.fetchone(
        "SELECT * FROM satoshimachine.lamassu_config WHERE is_active = true ORDER BY created_at DESC LIMIT 1",
        model=LamassuConfig,
    )


async def get_all_lamassu_configs() -> List[LamassuConfig]:
    return await db.fetchall(
        "SELECT * FROM satoshimachine.lamassu_config ORDER BY created_at DESC",
        model=LamassuConfig,
    )


async def update_lamassu_config(config_id: str, data: UpdateLamassuConfigData) -> Optional[LamassuConfig]:
    update_data = {k: v for k, v in data.dict().items() if v is not None}
    if not update_data:
        return await get_lamassu_config(config_id)
    
    update_data["updated_at"] = datetime.now()
    set_clause = ", ".join([f"{k} = :{k}" for k in update_data.keys()])
    update_data["id"] = config_id
    
    await db.execute(
        f"UPDATE satoshimachine.lamassu_config SET {set_clause} WHERE id = :id",
        update_data
    )
    return await get_lamassu_config(config_id)


async def update_config_test_result(config_id: str, success: bool) -> None:
    utc_now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE satoshimachine.lamassu_config 
        SET test_connection_last = :test_time, test_connection_success = :success, updated_at = :updated_at
        WHERE id = :id
        """,
        {
            "id": config_id,
            "test_time": utc_now,
            "success": success,
            "updated_at": utc_now
        }
    )


async def delete_lamassu_config(config_id: str) -> None:
    await db.execute(
        "DELETE FROM satoshimachine.lamassu_config WHERE id = :id", 
        {"id": config_id}
    )


async def update_poll_start_time(config_id: str) -> None:
    """Update the last poll start time"""
    utc_now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE satoshimachine.lamassu_config 
        SET last_poll_time = :poll_time, updated_at = :updated_at
        WHERE id = :id
        """,
        {
            "id": config_id,
            "poll_time": utc_now,
            "updated_at": utc_now
        }
    )


async def update_poll_success_time(config_id: str) -> None:
    """Update the last successful poll time"""
    utc_now = datetime.now(timezone.utc)
    await db.execute(
        """
        UPDATE satoshimachine.lamassu_config 
        SET last_successful_poll = :poll_time, updated_at = :updated_at
        WHERE id = :id
        """,
        {
            "id": config_id,
            "poll_time": utc_now,
            "updated_at": utc_now
        }
    )


# Lamassu Transaction Storage CRUD Operations
async def create_lamassu_transaction(data: CreateLamassuTransactionData) -> StoredLamassuTransaction:
    """Store a processed Lamassu transaction"""
    transaction_id = urlsafe_short_hash()
    await db.execute(
        """
        INSERT INTO satoshimachine.lamassu_transactions 
        (id, lamassu_transaction_id, fiat_amount, crypto_amount, commission_percentage, 
         discount, effective_commission, commission_amount_sats, base_amount_sats, 
         exchange_rate, crypto_code, fiat_code, device_id, transaction_time, processed_at,
         clients_count, distributions_total_sats)
        VALUES (:id, :lamassu_transaction_id, :fiat_amount, :crypto_amount, :commission_percentage,
                :discount, :effective_commission, :commission_amount_sats, :base_amount_sats,
                :exchange_rate, :crypto_code, :fiat_code, :device_id, :transaction_time, :processed_at,
                :clients_count, :distributions_total_sats)
        """,
        {
            "id": transaction_id,
            "lamassu_transaction_id": data.lamassu_transaction_id,
            "fiat_amount": data.fiat_amount,
            "crypto_amount": data.crypto_amount,
            "commission_percentage": data.commission_percentage,
            "discount": data.discount,
            "effective_commission": data.effective_commission,
            "commission_amount_sats": data.commission_amount_sats,
            "base_amount_sats": data.base_amount_sats,
            "exchange_rate": data.exchange_rate,
            "crypto_code": data.crypto_code,
            "fiat_code": data.fiat_code,
            "device_id": data.device_id,
            "transaction_time": data.transaction_time,
            "processed_at": datetime.now(),
            "clients_count": 0,  # Will be updated after distributions
            "distributions_total_sats": 0  # Will be updated after distributions
        }
    )
    return await get_lamassu_transaction(transaction_id)


async def get_lamassu_transaction(transaction_id: str) -> Optional[StoredLamassuTransaction]:
    """Get a stored Lamassu transaction by ID"""
    return await db.fetchone(
        "SELECT * FROM satoshimachine.lamassu_transactions WHERE id = :id",
        {"id": transaction_id},
        StoredLamassuTransaction,
    )


async def get_lamassu_transaction_by_lamassu_id(lamassu_transaction_id: str) -> Optional[StoredLamassuTransaction]:
    """Get a stored Lamassu transaction by Lamassu transaction ID"""
    return await db.fetchone(
        "SELECT * FROM satoshimachine.lamassu_transactions WHERE lamassu_transaction_id = :lamassu_id",
        {"lamassu_id": lamassu_transaction_id},
        StoredLamassuTransaction,
    )


async def get_all_lamassu_transactions() -> List[StoredLamassuTransaction]:
    """Get all stored Lamassu transactions"""
    return await db.fetchall(
        "SELECT * FROM satoshimachine.lamassu_transactions ORDER BY transaction_time DESC",
        model=StoredLamassuTransaction,
    )


async def update_lamassu_transaction_distribution_stats(
    transaction_id: str, 
    clients_count: int, 
    distributions_total_sats: int
) -> None:
    """Update distribution statistics for a Lamassu transaction"""
    await db.execute(
        """
        UPDATE satoshimachine.lamassu_transactions 
        SET clients_count = :clients_count, distributions_total_sats = :distributions_total_sats 
        WHERE id = :id
        """,
        {
            "clients_count": clients_count,
            "distributions_total_sats": distributions_total_sats,
            "id": transaction_id
        }
    )
