# Description: Pydantic data models dictate what is passed between frontend and backend.

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


# DCA Client Models
class CreateDcaClientData(BaseModel):
    user_id: str
    wallet_id: str
    username: str
    dca_mode: str = "flow"  # 'flow' or 'fixed'
    fixed_mode_daily_limit: Optional[int] = None


class DcaClient(BaseModel):
    id: str
    user_id: str
    wallet_id: str
    username: Optional[str]
    dca_mode: str
    fixed_mode_daily_limit: Optional[int]
    status: str
    created_at: datetime
    updated_at: datetime


class UpdateDcaClientData(BaseModel):
    username: Optional[str] = None
    dca_mode: Optional[str] = None
    fixed_mode_daily_limit: Optional[int] = None
    status: Optional[str] = None


# Deposit Models
class CreateDepositData(BaseModel):
    client_id: str
    amount: int  # Amount in smallest currency unit (centavos for GTQ)
    currency: str = "GTQ"
    notes: Optional[str] = None


class DcaDeposit(BaseModel):
    id: str
    client_id: str
    amount: int
    currency: str
    status: str  # 'pending' or 'confirmed'
    notes: Optional[str]
    created_at: datetime
    confirmed_at: Optional[datetime]


class UpdateDepositStatusData(BaseModel):
    status: str
    notes: Optional[str] = None


# Payment Models
class CreateDcaPaymentData(BaseModel):
    client_id: str
    amount_sats: int
    amount_fiat: int
    exchange_rate: float
    transaction_type: str  # 'flow', 'fixed', 'manual', 'commission'
    lamassu_transaction_id: Optional[str] = None
    payment_hash: Optional[str] = None
    transaction_time: Optional[datetime] = None  # Original ATM transaction time


class DcaPayment(BaseModel):
    id: str
    client_id: str
    amount_sats: int
    amount_fiat: int
    exchange_rate: float
    transaction_type: str
    lamassu_transaction_id: Optional[str]
    payment_hash: Optional[str]
    status: str  # 'pending', 'confirmed', 'failed'
    created_at: datetime
    transaction_time: Optional[datetime] = None  # Original ATM transaction time


# Client Balance Summary
class ClientBalanceSummary(BaseModel):
    client_id: str
    total_deposits: int  # Total confirmed deposits
    total_payments: int  # Total payments made
    remaining_balance: int  # Available balance for DCA
    currency: str


# Transaction Processing Models
class LamassuTransaction(BaseModel):
    transaction_id: str
    amount_fiat: int
    amount_crypto: int
    exchange_rate: float
    transaction_type: str  # 'cash_in' or 'cash_out'
    status: str
    timestamp: datetime


# Lamassu Transaction Storage Models
class CreateLamassuTransactionData(BaseModel):
    lamassu_transaction_id: str
    fiat_amount: int
    crypto_amount: int
    commission_percentage: float
    discount: float = 0.0
    effective_commission: float
    commission_amount_sats: int
    base_amount_sats: int
    exchange_rate: float
    crypto_code: str = "BTC"
    fiat_code: str = "GTQ"
    device_id: Optional[str] = None
    transaction_time: datetime


class StoredLamassuTransaction(BaseModel):
    id: str
    lamassu_transaction_id: str
    fiat_amount: int
    crypto_amount: int
    commission_percentage: float
    discount: float
    effective_commission: float
    commission_amount_sats: int
    base_amount_sats: int
    exchange_rate: float
    crypto_code: str
    fiat_code: str
    device_id: Optional[str]
    transaction_time: datetime
    processed_at: datetime
    clients_count: int  # Number of clients who received distributions
    distributions_total_sats: int  # Total sats distributed to clients


# Lamassu Configuration Models
class CreateLamassuConfigData(BaseModel):
    host: str
    port: int = 5432
    database_name: str
    username: str
    password: str
    # Source wallet for DCA distributions
    source_wallet_id: Optional[str] = None
    # Commission wallet for storing commission earnings
    commission_wallet_id: Optional[str] = None
    # SSH Tunnel settings
    use_ssh_tunnel: bool = False
    ssh_host: Optional[str] = None
    ssh_port: int = 22
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None  # Path to private key file or key content


class LamassuConfig(BaseModel):
    id: str
    host: str
    port: int
    database_name: str
    username: str
    password: str
    is_active: bool
    test_connection_last: Optional[datetime]
    test_connection_success: Optional[bool]
    created_at: datetime
    updated_at: datetime
    # Source wallet for DCA distributions
    source_wallet_id: Optional[str] = None
    # Commission wallet for storing commission earnings
    commission_wallet_id: Optional[str] = None
    # SSH Tunnel settings
    use_ssh_tunnel: bool = False
    ssh_host: Optional[str] = None
    ssh_port: int = 22
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None
    # Poll tracking
    last_poll_time: Optional[datetime] = None
    last_successful_poll: Optional[datetime] = None


class UpdateLamassuConfigData(BaseModel):
    host: Optional[str] = None
    port: Optional[int] = None
    database_name: Optional[str] = None
    username: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    # Source wallet for DCA distributions
    source_wallet_id: Optional[str] = None
    # Commission wallet for storing commission earnings
    commission_wallet_id: Optional[str] = None
    # SSH Tunnel settings
    use_ssh_tunnel: Optional[bool] = None
    ssh_host: Optional[str] = None
    ssh_port: Optional[int] = None
    ssh_username: Optional[str] = None
    ssh_password: Optional[str] = None
    ssh_private_key: Optional[str] = None


