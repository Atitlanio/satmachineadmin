# Description: This file contains the extensions API endpoints.

from http import HTTPStatus
from typing import Optional

from fastapi import APIRouter, Depends, Request
from lnbits.core.crud import get_user
from lnbits.core.models import WalletTypeInfo
from lnbits.core.services import create_invoice
from lnbits.decorators import require_admin_key
from starlette.exceptions import HTTPException

from .crud import (
    # DCA CRUD operations
    create_dca_client,
    get_dca_clients,
    get_dca_client,
    update_dca_client,
    delete_dca_client,
    create_deposit,
    get_all_deposits,
    get_deposit,
    update_deposit_status,
    get_client_balance_summary,
    # Lamassu config CRUD operations
    create_lamassu_config,
    get_lamassu_config,
    get_active_lamassu_config,
    get_all_lamassu_configs,
    update_lamassu_config,
    update_config_test_result,
    delete_lamassu_config,
    # Lamassu transaction CRUD operations
    get_all_lamassu_transactions,
    get_lamassu_transaction,
)
from .models import (
    # DCA models
    CreateDcaClientData,
    DcaClient,
    UpdateDcaClientData,
    CreateDepositData,
    DcaDeposit,
    UpdateDepositStatusData,
    ClientBalanceSummary,
    CreateLamassuConfigData,
    LamassuConfig,
    UpdateLamassuConfigData,
    StoredLamassuTransaction,
)

satmachineadmin_api_router = APIRouter()


###################################################
################ DCA API ENDPOINTS ################
###################################################

# DCA Client Endpoints


@satmachineadmin_api_router.get("/api/v1/dca/clients")
async def api_get_dca_clients(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[DcaClient]:
    """Get all DCA clients"""
    return await get_dca_clients()


@satmachineadmin_api_router.get("/api/v1/dca/clients/{client_id}")
async def api_get_dca_client(
    client_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> DcaClient:
    """Get a specific DCA client"""
    client = await get_dca_client(client_id)
    if not client:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="DCA client not found."
        )
    return client


# Note: Client creation/update/delete will be handled by the DCA client extension
# Admin extension only reads existing clients and manages their deposits


# TEMPORARY: Test client creation endpoint (remove in production)
@satmachineadmin_api_router.post("/api/v1/dca/clients", status_code=HTTPStatus.CREATED)
async def api_create_test_dca_client(
    data: CreateDcaClientData,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> DcaClient:
    """Create a test DCA client (temporary for testing)"""
    return await create_dca_client(data)


@satmachineadmin_api_router.get("/api/v1/dca/clients/{client_id}/balance")
async def api_get_client_balance(
    client_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> ClientBalanceSummary:
    """Get client balance summary"""
    client = await get_dca_client(client_id)
    if not client:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="DCA client not found."
        )

    return await get_client_balance_summary(client_id)


# DCA Deposit Endpoints


@satmachineadmin_api_router.get("/api/v1/dca/deposits")
async def api_get_deposits(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[DcaDeposit]:
    """Get all deposits"""
    return await get_all_deposits()


@satmachineadmin_api_router.get("/api/v1/dca/deposits/{deposit_id}")
async def api_get_deposit(
    deposit_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> DcaDeposit:
    """Get a specific deposit"""
    deposit = await get_deposit(deposit_id)
    if not deposit:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Deposit not found."
        )
    return deposit


@satmachineadmin_api_router.post("/api/v1/dca/deposits", status_code=HTTPStatus.CREATED)
async def api_create_deposit(
    data: CreateDepositData,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> DcaDeposit:
    """Create a new deposit"""
    # Verify client exists
    client = await get_dca_client(data.client_id)
    if not client:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="DCA client not found."
        )

    return await create_deposit(data)


@satmachineadmin_api_router.put("/api/v1/dca/deposits/{deposit_id}/status")
async def api_update_deposit_status(
    deposit_id: str,
    data: UpdateDepositStatusData,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> DcaDeposit:
    """Update deposit status (e.g., confirm deposit)"""
    deposit = await get_deposit(deposit_id)
    if not deposit:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Deposit not found."
        )

    updated_deposit = await update_deposit_status(deposit_id, data)
    if not updated_deposit:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update deposit.",
        )
    return updated_deposit


# Transaction Polling Endpoints


@satmachineadmin_api_router.post("/api/v1/dca/test-connection")
async def api_test_database_connection(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Test connection to Lamassu database with detailed reporting"""
    try:
        from .transaction_processor import transaction_processor

        # Use the detailed test method
        result = await transaction_processor.test_connection_detailed()
        return result

    except Exception as e:
        return {
            "success": False,
            "message": f"Test connection error: {str(e)}",
            "steps": [f"❌ Unexpected error: {str(e)}"],
            "ssh_tunnel_used": False,
            "ssh_tunnel_success": False,
            "database_connection_success": False,
        }


@satmachineadmin_api_router.post("/api/v1/dca/manual-poll")
async def api_manual_poll(
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Manually trigger a poll of the Lamassu database"""
    try:
        from .transaction_processor import transaction_processor
        from .crud import update_poll_start_time, update_poll_success_time

        # Get database configuration
        db_config = await transaction_processor.connect_to_lamassu_db()
        if not db_config:
            raise HTTPException(
                status_code=HTTPStatus.SERVICE_UNAVAILABLE,
                detail="Could not get Lamassu database configuration",
            )

        config_id = db_config["config_id"]

        # Record manual poll start time
        await update_poll_start_time(config_id)

        # Fetch and process transactions via SSH
        new_transactions = await transaction_processor.fetch_new_transactions(db_config)

        transactions_processed = 0
        for transaction in new_transactions:
            await transaction_processor.process_transaction(transaction)
            transactions_processed += 1

        # Record successful manual poll completion
        await update_poll_success_time(config_id)

        return {
            "success": True,
            "transactions_processed": transactions_processed,
            "message": f"Processed {transactions_processed} new transactions since last poll",
        }

    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error during manual poll: {str(e)}",
        )


@satmachineadmin_api_router.post("/api/v1/dca/test-transaction")
async def api_test_transaction(
    wallet: WalletTypeInfo = Depends(require_admin_key),
    crypto_atoms: int = 103,
    commission_percentage: float = 0.03,
    discount: float = 0.0,
) -> dict:
    """Test transaction processing with simulated Lamassu transaction data"""
    try:
        from .transaction_processor import transaction_processor
        import uuid
        from datetime import datetime, timezone

        # Create a mock transaction that mimics Lamassu database structure
        mock_transaction = {
            "transaction_id": str(uuid.uuid4())[:8],  # Short ID for testing
            "crypto_amount": crypto_atoms,  # Total sats including commission
            "fiat_amount": 100,  # Mock fiat amount (100 centavos = 1 GTQ)
            "commission_percentage": commission_percentage,  # Already as decimal
            "discount": discount,
            "transaction_time": datetime.now(timezone.utc),
            "crypto_code": "BTC",
            "fiat_code": "GTQ",
            "device_id": "test_device",
            "status": "confirmed",
        }

        # Process the mock transaction through the complete DCA flow
        await transaction_processor.process_transaction(mock_transaction)

        # Calculate commission for response
        if commission_percentage > 0:
            effective_commission = commission_percentage * (100 - discount) / 100
            base_crypto_atoms = int(crypto_atoms / (1 + effective_commission))
            commission_amount_sats = crypto_atoms - base_crypto_atoms
        else:
            base_crypto_atoms = crypto_atoms
            commission_amount_sats = 0

        return {
            "success": True,
            "message": "Test transaction processed successfully",
            "transaction_details": {
                "transaction_id": mock_transaction["transaction_id"],
                "total_amount_sats": crypto_atoms,
                "base_amount_sats": base_crypto_atoms,
                "commission_amount_sats": commission_amount_sats,
                "commission_percentage": commission_percentage
                * 100,  # Show as percentage
                "effective_commission": effective_commission * 100
                if commission_percentage > 0
                else 0,
                "discount": discount,
            },
        }

    except Exception as e:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail=f"Error processing test transaction: {str(e)}",
        )


# Lamassu Transaction Endpoints


@satmachineadmin_api_router.get("/api/v1/dca/transactions")
async def api_get_lamassu_transactions(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[StoredLamassuTransaction]:
    """Get all processed Lamassu transactions"""
    return await get_all_lamassu_transactions()


@satmachineadmin_api_router.get("/api/v1/dca/transactions/{transaction_id}")
async def api_get_lamassu_transaction(
    transaction_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> StoredLamassuTransaction:
    """Get a specific Lamassu transaction with details"""
    transaction = await get_lamassu_transaction(transaction_id)
    if not transaction:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Lamassu transaction not found."
        )
    return transaction


@satmachineadmin_api_router.get(
    "/api/v1/dca/transactions/{transaction_id}/distributions"
)
async def api_get_transaction_distributions(
    transaction_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> list[dict]:
    """Get distribution details for a specific Lamassu transaction"""
    # Get the stored transaction
    transaction = await get_lamassu_transaction(transaction_id)
    if not transaction:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Lamassu transaction not found."
        )

    # Get all DCA payments for this Lamassu transaction
    from .crud import get_payments_by_lamassu_transaction, get_dca_client

    payments = await get_payments_by_lamassu_transaction(
        transaction.lamassu_transaction_id
    )

    # Enhance payments with client information
    distributions = []
    for payment in payments:
        client = await get_dca_client(payment.client_id)
        distributions.append(
            {
                "payment_id": payment.id,
                "client_id": payment.client_id,
                "client_username": client.username if client else None,
                "client_user_id": client.user_id if client else None,
                "amount_sats": payment.amount_sats,
                "amount_fiat": payment.amount_fiat,
                "exchange_rate": payment.exchange_rate,
                "status": payment.status,
                "created_at": payment.created_at,
            }
        )

    return distributions


# Lamassu Configuration Endpoints


@satmachineadmin_api_router.get("/api/v1/dca/config")
async def api_get_lamassu_config(
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> Optional[LamassuConfig]:
    """Get active Lamassu database configuration"""
    return await get_active_lamassu_config()


@satmachineadmin_api_router.post("/api/v1/dca/config", status_code=HTTPStatus.CREATED)
async def api_create_lamassu_config(
    data: CreateLamassuConfigData,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> LamassuConfig:
    """Create/update Lamassu database configuration"""
    return await create_lamassu_config(data)


@satmachineadmin_api_router.put("/api/v1/dca/config/{config_id}")
async def api_update_lamassu_config(
    config_id: str,
    data: UpdateLamassuConfigData,
    wallet: WalletTypeInfo = Depends(require_admin_key),
) -> LamassuConfig:
    """Update Lamassu database configuration"""
    config = await get_lamassu_config(config_id)
    if not config:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Configuration not found."
        )

    updated_config = await update_lamassu_config(config_id, data)
    if not updated_config:
        raise HTTPException(
            status_code=HTTPStatus.INTERNAL_SERVER_ERROR,
            detail="Failed to update configuration.",
        )
    return updated_config


@satmachineadmin_api_router.delete("/api/v1/dca/config/{config_id}")
async def api_delete_lamassu_config(
    config_id: str,
    wallet: WalletTypeInfo = Depends(require_admin_key),
):
    """Delete Lamassu database configuration"""
    config = await get_lamassu_config(config_id)
    if not config:
        raise HTTPException(
            status_code=HTTPStatus.NOT_FOUND, detail="Configuration not found."
        )

    await delete_lamassu_config(config_id)
    return {"message": "Configuration deleted successfully"}
