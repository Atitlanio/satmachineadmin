# Transaction processing and polling service for Lamassu ATM integration

import asyncio
import asyncpg
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict, Any
from loguru import logger
import socket
import threading
import time

try:
    import asyncssh
    SSH_AVAILABLE = True
except ImportError:
    try:
        # Fallback to subprocess-based SSH tunnel
        import subprocess
        SSH_AVAILABLE = True
    except ImportError:
        SSH_AVAILABLE = False
        logger.warning("SSH tunnel support not available")

from lnbits.core.services import create_invoice, pay_invoice
from lnbits.core.crud.wallets import get_wallet
from lnbits.core.services import update_wallet_balance
from lnbits.settings import settings

from .crud import (
    get_flow_mode_clients,
    get_payments_by_lamassu_transaction,
    create_dca_payment,
    get_client_balance_summary,
    get_active_lamassu_config,
    update_config_test_result,
    update_poll_start_time,
    update_poll_success_time,
    update_dca_payment_status,
    create_lamassu_transaction,
    update_lamassu_transaction_distribution_stats
)
from .models import CreateDcaPaymentData, LamassuTransaction, DcaClient, CreateLamassuTransactionData


class LamassuTransactionProcessor:
    """Handles polling Lamassu database and processing transactions for DCA distribution"""
    
    def __init__(self):
        self.last_check_time = None
        self.processed_transaction_ids = set()
        self.ssh_process = None
        self.ssh_key_path = None
        self.ssh_config_path = None
    
    async def get_db_config(self) -> Optional[Dict[str, Any]]:
        """Get database configuration from the database"""
        try:
            config = await get_active_lamassu_config()
            if not config:
                logger.error("No active Lamassu database configuration found")
                return None
            
            return {
                "host": config.host,
                "port": config.port,
                "database": config.database_name,
                "user": config.username,
                "password": config.password,
                "config_id": config.id,
                "use_ssh_tunnel": config.use_ssh_tunnel,
                "ssh_host": config.ssh_host,
                "ssh_port": config.ssh_port,
                "ssh_username": config.ssh_username,
                "ssh_password": config.ssh_password,
                "ssh_private_key": config.ssh_private_key
            }
        except Exception as e:
            logger.error(f"Error getting database configuration: {e}")
            return None
    
    def setup_ssh_tunnel(self, db_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Setup SSH tunnel if required and return modified connection config"""
        if not db_config.get("use_ssh_tunnel"):
            return db_config
            
        if not SSH_AVAILABLE:
            logger.error("SSH tunnel requested but SSH libraries not available")
            return None
            
        try:
            # Close existing tunnel if any
            self.close_ssh_tunnel()
            
            # Use subprocess-based SSH tunnel as fallback
            return self._setup_subprocess_ssh_tunnel(db_config)
            
        except Exception as e:
            logger.error(f"Failed to setup SSH tunnel: {e}")
            self.close_ssh_tunnel()
            return None
    
    def _setup_subprocess_ssh_tunnel(self, db_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Setup SSH tunnel using subprocess (compatible with all environments)"""
        import subprocess
        import socket
        
        # Find an available local port
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('', 0))
            local_port = s.getsockname()[1]
        
        # Build SSH command
        ssh_cmd = [
            "ssh",
            "-N",  # Don't execute remote command
            "-L", f"{local_port}:{db_config['host']}:{db_config['port']}",
            f"{db_config['ssh_username']}@{db_config['ssh_host']}",
            "-p", str(db_config['ssh_port']),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR",
            "-o", "ConnectTimeout=10",
            "-o", "ServerAliveInterval=60"
        ]
        
        # Add authentication method
        if db_config.get("ssh_password"):
            # Check if sshpass is available for password authentication
            try:
                import subprocess
                subprocess.run(["which", "sshpass"], check=True, capture_output=True)
                ssh_cmd = ["sshpass", "-p", db_config["ssh_password"]] + ssh_cmd
            except subprocess.CalledProcessError:
                logger.error("Password authentication requires 'sshpass' tool which is not installed. Please use SSH key authentication instead.")
                return None
        elif db_config.get("ssh_private_key"):
            # Write private key and SSH config to temporary files
            import tempfile
            import os
            key_fd, key_path = tempfile.mkstemp(suffix='.pem')
            config_fd, config_path = tempfile.mkstemp(suffix='.ssh_config')
            try:
                # Prepare key content with proper line endings and final newline
                key_data = db_config["ssh_private_key"]
                key_data = key_data.replace('\r\n', '\n').replace('\r', '\n')  # Normalize line endings
                if not key_data.endswith('\n'):
                    key_data += '\n'  # Ensure newline at end of file

                with os.fdopen(key_fd, 'w', encoding='utf-8') as f:
                    f.write(key_data)

                os.chmod(key_path, 0o600)

                # Create temporary SSH config file with strict settings
                ssh_config = f"""Host {db_config['ssh_host']}
    HostName {db_config['ssh_host']}
    Port {db_config['ssh_port']}
    User {db_config['ssh_username']}
    IdentityFile {key_path}
    IdentitiesOnly yes
    PasswordAuthentication no
    PubkeyAuthentication yes
    PreferredAuthentications publickey
    NumberOfPasswordPrompts 0
    IdentityAgent none
    ControlMaster no
    ControlPath none
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ConnectTimeout 10
    ServerAliveInterval 60
"""
                
                with os.fdopen(config_fd, 'w', encoding='utf-8') as f:
                    f.write(ssh_config)
                
                os.chmod(config_path, 0o600)

                # Use the custom config file
                ssh_cmd.extend([
                    "-F", config_path,
                    db_config['ssh_host']
                ])
                print(ssh_cmd)

                self.ssh_key_path = key_path  # Store for cleanup
                self.ssh_config_path = config_path  # Store for cleanup
            except Exception as e:
                os.unlink(key_path)
                if 'config_path' in locals():
                    os.unlink(config_path)
                raise e
        else:
            logger.error("SSH tunnel requires either private key or password")
            return None
        
        # Start SSH tunnel process
        try:
            self.ssh_process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                stdin=subprocess.DEVNULL
            )
            
            # Wait a moment for tunnel to establish
            import time
            time.sleep(2)
            
            # Check if process is still running
            if self.ssh_process.poll() is not None:
                raise Exception("SSH tunnel process terminated immediately")
            
            logger.info(f"SSH tunnel established: localhost:{local_port} -> {db_config['ssh_host']}:{db_config['ssh_port']} -> {db_config['host']}:{db_config['port']}")
            
            # Return modified config to connect through tunnel
            tunnel_config = db_config.copy()
            tunnel_config["host"] = "127.0.0.1"
            tunnel_config["port"] = local_port
            
            return tunnel_config
            
        except FileNotFoundError:
            logger.error("SSH command not found. SSH tunneling requires ssh (and sshpass for password auth) to be installed on the system.")
            return None
        except Exception as e:
            logger.error(f"Failed to establish SSH tunnel: {e}")
            return None
    
    def close_ssh_tunnel(self):
        """Close SSH tunnel if active"""
        # Close subprocess-based tunnel
        if hasattr(self, 'ssh_process') and self.ssh_process:
            try:
                self.ssh_process.terminate()
                self.ssh_process.wait(timeout=5)
                logger.info("SSH tunnel process closed")
            except Exception as e:
                logger.warning(f"Error closing SSH tunnel process: {e}")
                try:
                    self.ssh_process.kill()
                except:
                    pass
            finally:
                self.ssh_process = None
        
        # Clean up temporary key file if exists
        if hasattr(self, 'ssh_key_path') and self.ssh_key_path:
            try:
                import os
                os.unlink(self.ssh_key_path)
                logger.info("SSH key file cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up SSH key file: {e}")
            finally:
                self.ssh_key_path = None
        
        # Clean up temporary SSH config file if exists
        if hasattr(self, 'ssh_config_path') and self.ssh_config_path:
            try:
                import os
                os.unlink(self.ssh_config_path)
                logger.info("SSH config file cleaned up")
            except Exception as e:
                logger.warning(f"Error cleaning up SSH config file: {e}")
            finally:
                self.ssh_config_path = None
    
    async def test_connection_detailed(self) -> Dict[str, Any]:
        """Test connection with detailed step-by-step reporting"""
        result = {
            "success": False,
            "message": "",
            "steps": [],
            "ssh_tunnel_used": False,
            "ssh_tunnel_success": False,
            "database_connection_success": False,
            "config_id": None
        }
        
        try:
            # Step 1: Get configuration
            result["steps"].append("Retrieving database configuration...")
            db_config = await self.get_db_config()
            if not db_config:
                result["message"] = "No active Lamassu database configuration found"
                result["steps"].append("❌ No configuration found")
                return result
                
            result["config_id"] = db_config["config_id"]
            result["steps"].append("✅ Configuration retrieved")
            
            # Step 2: SSH Tunnel setup (if required)
            if db_config.get("use_ssh_tunnel"):
                result["ssh_tunnel_used"] = True
                result["steps"].append("Setting up SSH tunnel...")
                
                if not SSH_AVAILABLE:
                    result["message"] = "SSH tunnel required but SSH support not available"
                    result["steps"].append("❌ SSH support missing (requires ssh command line tool)")
                    return result
                
                connection_config = self.setup_ssh_tunnel(db_config)
                if not connection_config:
                    result["message"] = "Failed to establish SSH tunnel"
                    result["steps"].append("❌ SSH tunnel failed - check SSH credentials and server accessibility")
                    return result
                    
                result["ssh_tunnel_success"] = True
                result["steps"].append(f"✅ SSH tunnel established to {db_config['ssh_host']}:{db_config['ssh_port']}")
            else:
                connection_config = db_config
                result["steps"].append("ℹ️  Direct database connection (no SSH tunnel)")
            
            # Step 3: Test SSH-based database query
            result["steps"].append("Testing database query via SSH...")
            test_query = "SELECT 1 as test"
            test_results = await self.execute_ssh_query(db_config, test_query)
            
            if not test_results:
                result["message"] = "SSH connection succeeded but database query failed"
                result["steps"].append("❌ Database query test failed")
                return result
            
            result["database_connection_success"] = True
            result["steps"].append("✅ Database query test successful")
            
            # Step 4: Test actual table access and check timezone
            result["steps"].append("Testing access to cash_out_txs table...")
            table_query = "SELECT COUNT(*) FROM cash_out_txs"
            table_results = await self.execute_ssh_query(db_config, table_query)
            
            if not table_results:
                result["message"] = "Connected but cash_out_txs table not accessible"
                result["steps"].append("❌ Table access failed")
                return result
                
            count = table_results[0].get('count', 0)
            result["steps"].append(f"✅ Table access successful (found {count} transactions)")
            
            # Step 5: Check database timezone
            result["steps"].append("Checking database timezone...")
            timezone_query = "SELECT NOW() as db_time, EXTRACT(timezone FROM NOW()) as timezone_offset"
            timezone_results = await self.execute_ssh_query(db_config, timezone_query)
            
            if timezone_results:
                db_time = timezone_results[0].get('db_time', 'unknown')
                timezone_offset = timezone_results[0].get('timezone_offset', 'unknown')
                result["steps"].append(f"✅ Database time: {db_time} (offset: {timezone_offset})")
            else:
                result["steps"].append("⚠️ Could not determine database timezone")
            
            result["success"] = True
            result["message"] = "All connection tests passed successfully"
            
        except Exception as e:
            error_msg = str(e)
            if "cash_out_txs" in error_msg:
                result["message"] = "Connected to database but cash_out_txs table not found"
                result["steps"].append("❌ Lamassu transaction table missing")
            elif "ssh" in error_msg.lower() or "connection" in error_msg.lower():
                result["message"] = f"SSH connection error: {error_msg}"
                result["steps"].append(f"❌ SSH error: {error_msg}")
            elif "permission denied" in error_msg.lower() or "authentication" in error_msg.lower():
                result["message"] = f"SSH authentication failed: {error_msg}"
                result["steps"].append(f"❌ SSH authentication error: {error_msg}")
            else:
                result["message"] = f"Connection test failed: {error_msg}"
                result["steps"].append(f"❌ Unexpected error: {error_msg}")
            
        # Update test result in database
        if result["config_id"]:
            try:
                await update_config_test_result(result["config_id"], result["success"])
            except Exception as e:
                logger.warning(f"Could not update config test result: {e}")
        
        return result
    
    async def connect_to_lamassu_db(self) -> Optional[Dict[str, Any]]:
        """Get database configuration (returns config dict instead of connection)"""
        try:
            db_config = await self.get_db_config()
            if not db_config:
                return None
                
            # Update test result on successful config retrieval
            try:
                await update_config_test_result(db_config["config_id"], True)
            except Exception as e:
                logger.warning(f"Could not update config test result: {e}")
            
            return db_config
        except Exception as e:
            logger.error(f"Failed to get database configuration: {e}")
            return None
    
    async def execute_ssh_query(self, db_config: Dict[str, Any], query: str) -> List[Dict[str, Any]]:
        """Execute a query via SSH connection"""
        import subprocess
        import json
        import asyncio
        
        try:
            # Build SSH command to execute the query
            ssh_cmd = [
                "ssh",
                f"{db_config['ssh_username']}@{db_config['ssh_host']}",
                "-p", str(db_config['ssh_port']),
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                "-o", "LogLevel=ERROR"
            ]
            
            # Add key authentication if provided
            if db_config.get("ssh_private_key"):
                import tempfile
                import os
                key_fd, key_path = tempfile.mkstemp(suffix='.pem')
                config_fd, config_path = tempfile.mkstemp(suffix='.ssh_config')
                try:
                    # Prepare key content with proper line endings and final newline
                    key_data = db_config["ssh_private_key"]
                    key_data = key_data.replace('\r\n', '\n').replace('\r', '\n')  # Normalize line endings
                    if not key_data.endswith('\n'):
                        key_data += '\n'  # Ensure newline at end of file

                    with os.fdopen(key_fd, 'w', encoding='utf-8') as f:
                        f.write(key_data)
                    os.chmod(key_path, 0o600)

                    # Create temporary SSH config file with strict settings
                    ssh_config = f"""Host {db_config['ssh_host']}
    HostName {db_config['ssh_host']}
    Port {db_config['ssh_port']}
    User {db_config['ssh_username']}
    IdentityFile {key_path}
    IdentitiesOnly yes
    PasswordAuthentication no
    PubkeyAuthentication yes
    PreferredAuthentications publickey
    NumberOfPasswordPrompts 0
    IdentityAgent none
    ControlMaster no
    ControlPath none
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    LogLevel ERROR
    ConnectTimeout 10
    ServerAliveInterval 60
"""
                    
                    with os.fdopen(config_fd, 'w', encoding='utf-8') as f:
                        f.write(ssh_config)
                    os.chmod(config_path, 0o600)

                    # Use the custom config file
                    ssh_cmd = [
                        "ssh",
                        "-F", config_path,
                        db_config['ssh_host']
                    ]
                    
                    # Build the psql command to return JSON
                    psql_cmd = f"psql {db_config['database']} -t -c \"COPY ({query}) TO STDOUT WITH CSV HEADER\""
                    ssh_cmd.append(psql_cmd)
                    
                    # Execute the command
                    process = await asyncio.create_subprocess_exec(
                        *ssh_cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE
                    )
                    
                    stdout, stderr = await process.communicate()
                    
                    if process.returncode != 0:
                        logger.error(f"SSH query failed: {stderr.decode()}")
                        return []
                    
                    # Parse CSV output
                    import csv
                    import io
                    
                    csv_data = stdout.decode()
                    if not csv_data.strip():
                        return []
                    
                    reader = csv.DictReader(io.StringIO(csv_data))
                    results = []
                    for row in reader:
                        # Convert string values to appropriate types
                        processed_row = {}
                        for key, value in row.items():
                            if value == '':
                                processed_row[key] = None
                            elif key in ['transaction_id', 'device_id', 'crypto_code', 'fiat_code']:
                                processed_row[key] = str(value)
                            elif key in ['fiat_amount', 'crypto_amount']:
                                processed_row[key] = int(float(value)) if value else 0
                            elif key in ['commission_percentage', 'discount']:
                                processed_row[key] = float(value) if value else 0.0
                            elif key == 'transaction_time':
                                from datetime import datetime
                                processed_row[key] = datetime.fromisoformat(value.replace('Z', '+00:00'))
                            else:
                                processed_row[key] = value
                        results.append(processed_row)
                    
                    return results
                    
                finally:
                    os.unlink(key_path)
                    if 'config_path' in locals():
                        os.unlink(config_path)
                    
            else:
                logger.error("SSH private key required for database queries")
                return []
                
        except Exception as e:
            logger.error(f"Error executing SSH query: {e}")
            return []
    
    async def fetch_new_transactions(self, db_config: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Fetch new successful transactions from Lamassu database since last poll"""
        try:
            # Determine the time threshold based on last successful poll
            config = await get_active_lamassu_config()
            if config and config.last_successful_poll:
                # Use last successful poll time
                time_threshold = config.last_successful_poll
                logger.info(f"Checking for transactions since last successful poll: {time_threshold}")
            else:
                # Fallback to last 24 hours for first run or if no previous poll
                time_threshold = datetime.now(timezone.utc) - timedelta(hours=24)
                logger.info(f"No previous poll found, checking last 24 hours since: {time_threshold}")
            
            # Convert to UTC if not already timezone-aware
            if time_threshold.tzinfo is None:
                time_threshold = time_threshold.replace(tzinfo=timezone.utc)
            elif time_threshold.tzinfo != timezone.utc:
                time_threshold = time_threshold.astimezone(timezone.utc)
            
            # Format as UTC for database query
            time_threshold_str = time_threshold.strftime('%Y-%m-%d %H:%M:%S UTC')
            
            # First, get all transactions since the threshold from Lamassu database
            # Filter out unconfirmed dispenses
            # TODO: review
            lamassu_query = f"""
            SELECT 
                co.id as transaction_id,
                co.fiat as fiat_amount,
                co.crypto_atoms as crypto_amount,
                co.confirmed_at as transaction_time,
                co.device_id,
                co.status,
                co.commission_percentage,
                co.discount,
                co.crypto_code,
                co.fiat_code
            FROM cash_out_txs co
            WHERE co.confirmed_at > '{time_threshold_str}'
                AND co.status IN ('confirmed', 'authorized')
                AND co.dispense = 't'
                AND co.dispense_confirmed = 't'
            ORDER BY co.confirmed_at DESC
            """
            
            all_transactions = await self.execute_ssh_query(db_config, lamassu_query)
            
            # Then filter out already processed transactions using our local database
            from .crud import get_all_payments
            processed_payments = await get_all_payments()
            processed_transaction_ids = {
                payment.lamassu_transaction_id 
                for payment in processed_payments 
                if payment.lamassu_transaction_id
            }
            
            # Filter out already processed transactions
            new_transactions = [
                tx for tx in all_transactions 
                if tx['transaction_id'] not in processed_transaction_ids
            ]
            
            logger.info(f"Found {len(all_transactions)} total transactions since {time_threshold}, {len(new_transactions)} are new")
            return new_transactions
            
        except Exception as e:
            logger.error(f"Error fetching transactions from Lamassu database: {e}")
            return []
    
    async def calculate_distribution_amounts(self, transaction: Dict[str, Any]) -> Dict[str, int]:
        """Calculate how much each Flow Mode client should receive"""
        try:
            # Get all active Flow Mode clients
            flow_clients = await get_flow_mode_clients()
            
            if not flow_clients:
                logger.info("No Flow Mode clients found - skipping distribution")
                return {}
            
            # Extract transaction details with None-safe defaults
            crypto_atoms = transaction.get("crypto_amount")  # Total sats with commission baked in
            fiat_amount = transaction.get("fiat_amount")     # Actual fiat dispensed (principal only)
            commission_percentage = transaction.get("commission_percentage")  # Already stored as decimal (e.g., 0.045)
            discount = transaction.get("discount")  # Discount percentage
            
            # Validate required fields
            if crypto_atoms is None:
                logger.error(f"Missing crypto_amount in transaction: {transaction}")
                return {}
            if fiat_amount is None:
                logger.error(f"Missing fiat_amount in transaction: {transaction}")
                return {}
            if commission_percentage is None:
                logger.warning(f"Missing commission_percentage in transaction: {transaction}, defaulting to 0")
                commission_percentage = 0.0
            if discount is None:
                logger.info(f"Missing discount in transaction: {transaction}, defaulting to 0")
                discount = 0.0
            
            # Calculate effective commission percentage after discount (following the reference logic)
            if commission_percentage > 0:
                effective_commission = commission_percentage * (100 - discount) / 100
                # Since crypto_atoms already includes commission, we need to extract the base amount
                # Formula: crypto_atoms = base_amount * (1 + effective_commission)
                # Therefore: base_amount = crypto_atoms / (1 + effective_commission)
                base_crypto_atoms = int(crypto_atoms / (1 + effective_commission))
                commission_amount_sats = crypto_atoms - base_crypto_atoms
            else:
                effective_commission = 0.0
                base_crypto_atoms = crypto_atoms
                commission_amount_sats = 0
            
            # Calculate exchange rate based on base amounts
            exchange_rate = base_crypto_atoms / fiat_amount if fiat_amount > 0 else 0  # sats per fiat unit
            
            logger.info(f"Transaction - Total crypto: {crypto_atoms} sats")
            logger.info(f"Commission: {commission_percentage*100:.1f}% - {discount:.1f}% discount = {effective_commission*100:.1f}% effective ({commission_amount_sats} sats)")
            logger.info(f"Base for DCA: {base_crypto_atoms} sats, Fiat dispensed: {fiat_amount}, Exchange rate: {exchange_rate:.2f} sats/fiat_unit")
            
            # Get balance summaries for all clients to calculate proportions
            client_balances = {}
            total_confirmed_deposits = 0
            
            for client in flow_clients:
                balance = await get_client_balance_summary(client.id)
                if balance.remaining_balance > 0:  # Only include clients with remaining balance
                    client_balances[client.id] = balance.remaining_balance
                    total_confirmed_deposits += balance.remaining_balance
            
            if total_confirmed_deposits == 0:
                logger.info("No clients with remaining DCA balance - skipping distribution")
                return {}
            
            # Calculate proportional distribution
            distributions = {}
            
            for client_id, client_balance in client_balances.items():
                # Calculate this client's proportion of the total DCA pool
                proportion = client_balance / total_confirmed_deposits
                
                # Calculate client's share of the base crypto (after commission)
                client_sats_amount = int(base_crypto_atoms * proportion)
                
                # Calculate equivalent fiat value for tracking purposes
                # TODO: make client_fiat_amount float with 2 decimal presicion
                client_fiat_amount = int(client_sats_amount / exchange_rate) if exchange_rate > 0 else 0
                
                distributions[client_id] = {
                    "fiat_amount": client_fiat_amount,
                    "sats_amount": client_sats_amount,
                    "exchange_rate": exchange_rate
                }
                
                logger.info(f"Client {client_id[:8]}... gets {client_sats_amount} sats (≈{client_fiat_amount} fiat units, {proportion:.2%} share)")
            
            return distributions
            
        except Exception as e:
            logger.error(f"Error calculating distribution amounts: {e}")
            return {}
    
    async def distribute_to_clients(self, transaction: Dict[str, Any], distributions: Dict[str, Dict[str, int]]) -> None:
        """Send Bitcoin payments to DCA clients"""
        try:
            transaction_id = transaction["transaction_id"]
            
            for client_id, distribution in distributions.items():
                try:
                    # Get client info
                    flow_clients = await get_flow_mode_clients()
                    client = next((c for c in flow_clients if c.id == client_id), None)
                    
                    if not client:
                        logger.error(f"Client {client_id} not found")
                        continue
                    
                    # Create DCA payment record
                    payment_data = CreateDcaPaymentData(
                        client_id=client_id,
                        amount_sats=distribution["sats_amount"],
                        amount_fiat=distribution["fiat_amount"],
                        exchange_rate=distribution["exchange_rate"],
                        transaction_type="flow",
                        lamassu_transaction_id=transaction_id,
                        transaction_time=transaction.get("transaction_time")  # Original ATM transaction time
                    )
                    
                    # Record the payment in our database
                    dca_payment = await create_dca_payment(payment_data)
                    
                    # Send Bitcoin to client's wallet
                    success = await self.send_dca_payment(client, distribution, transaction_id)
                    if success:
                        # Update payment status to confirmed after successful payment
                        await self.update_payment_status(dca_payment.id, "confirmed")
                        logger.info(f"DCA payment sent to client {client_id[:8]}...: {distribution['sats_amount']} sats")
                    else:
                        # Update payment status to failed if payment failed
                        await self.update_payment_status(dca_payment.id, "failed")
                        logger.error(f"Failed to send DCA payment to client {client_id[:8]}...")
                    
                except Exception as e:
                    logger.error(f"Error processing distribution for client {client_id}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error distributing to clients: {e}")
    
    async def send_dca_payment(self, client: DcaClient, distribution: Dict[str, Any], lamassu_transaction_id: str) -> bool:
        """Send Bitcoin payment to a DCA client's wallet"""
        try:
            # For now, we only support wallet_id payments (internal LNBits transfers)
            target_wallet_id = client.wallet_id
            amount_sats = distribution["sats_amount"]
            amount_msat = amount_sats * 1000  # Convert sats to millisats
            
            # Validate the target wallet exists
            target_wallet = await get_wallet(target_wallet_id)
            if not target_wallet:
                logger.error(f"Target wallet {target_wallet_id} not found for client {client.username or client.user_id}")
                return False
            
            # Create descriptive memo with DCA metrics
            fiat_amount = distribution.get("fiat_amount", 0)
            exchange_rate = distribution.get("exchange_rate", 0)
            
            # Calculate cost basis (fiat per BTC)
            if exchange_rate > 0:
                # exchange_rate is sats per fiat unit, so convert to fiat per BTC
                cost_basis_per_btc = 100_000_000 / exchange_rate  # 100M sats = 1 BTC
                memo = f"DCA: {amount_sats:,} sats • {fiat_amount:,} GTQ • Cost basis: {cost_basis_per_btc:,.2f} GTQ/BTC"
            else:
                memo = f"DCA: {amount_sats:,} sats • {fiat_amount:,} GTQ"
            
            # Create invoice in target wallet
            extra={
                "tag": "dca_distribution",
                "client_id": client.id,
                "lamassu_transaction_id": lamassu_transaction_id,
                "distribution_amount": amount_sats
            }
            new_payment = await create_invoice(
                wallet_id=target_wallet.id,
                amount=amount_sats,  # LNBits create_invoice expects sats
                internal=True,  # Internal transfer within LNBits
                memo=memo,
                extra=extra
            )
            
            if not new_payment:
                logger.error(f"Failed to create invoice for client {client.username or client.user_id}")
                return False
            
            # Pay the invoice from the DCA admin wallet (this extension's wallet)
            # Get the admin wallet that manages DCA funds
            admin_config = await get_active_lamassu_config()
            if not admin_config:
                logger.error("No active Lamassu config found - cannot determine source wallet")
                return False
            
            if not admin_config.source_wallet_id:
                logger.warning("DCA source wallet not configured - payment creation successful but not sent")
                logger.info(f"Created invoice for {amount_sats} sats to client {client.username or client.user_id}")
                logger.info(f"Invoice: {new_payment.bolt11}")
                return True
            
            # Pay the invoice from the configured source wallet
            try:
                await pay_invoice(
                    payment_request=new_payment.bolt11,
                    wallet_id=admin_config.source_wallet_id,
                    description=memo,
                    extra=extra
                )
                logger.info(f"DCA payment completed: {amount_sats} sats sent to {client.username or client.user_id}")
                return True
            except Exception as e:
                logger.error(f"Failed to pay invoice for client {client.username or client.user_id}: {e}")
                return False
            
        except Exception as e:
            logger.error(f"Error sending DCA payment to client {client.username or client.user_id}: {e}")
            return False
    
    async def credit_source_wallet(self, transaction: Dict[str, Any]) -> bool:
        """Credit the source wallet with the full crypto_atoms amount from Lamassu transaction"""
        try:
            # Get the configuration to find source wallet
            admin_config = await get_active_lamassu_config()
            if not admin_config or not admin_config.source_wallet_id:
                logger.error("No source wallet configured - cannot credit wallet")
                return False
            
            crypto_atoms = transaction["crypto_amount"]  # Full amount including commission
            transaction_id = transaction["transaction_id"]
            
            # Get the source wallet object
            source_wallet = await get_wallet(admin_config.source_wallet_id)
            if not source_wallet:
                logger.error(f"Source wallet {admin_config.source_wallet_id} not found")
                return False
            
            # Credit the source wallet with the full crypto_atoms amount
            await update_wallet_balance(
                wallet=source_wallet,
                amount=crypto_atoms  # Function expects sats, not millisats
            )
            
            logger.info(f"Credited source wallet with {crypto_atoms} sats from transaction {transaction_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error crediting source wallet for transaction {transaction.get('transaction_id', 'unknown')}: {e}")
            return False

    async def update_payment_status(self, payment_id: str, status: str) -> None:
        """Update the status of a DCA payment"""
        try:
            await update_dca_payment_status(payment_id, status)
            logger.info(f"Updated payment {payment_id[:8]}... status to {status}")
        except Exception as e:
            logger.error(f"Error updating payment status for {payment_id}: {e}")

    async def store_lamassu_transaction(self, transaction: Dict[str, Any]) -> Optional[str]:
        """Store the Lamassu transaction in our database for audit and UI"""
        try:
            # Extract and validate transaction data
            crypto_atoms = transaction.get("crypto_amount", 0)
            fiat_amount = transaction.get("fiat_amount", 0)
            commission_percentage = transaction.get("commission_percentage") or 0.0
            discount = transaction.get("discount") or 0.0
            
            # Calculate commission metrics
            if commission_percentage > 0:
                effective_commission = commission_percentage * (100 - discount) / 100
                base_crypto_atoms = int(crypto_atoms / (1 + effective_commission))
                commission_amount_sats = crypto_atoms - base_crypto_atoms
            else:
                effective_commission = 0.0
                base_crypto_atoms = crypto_atoms
                commission_amount_sats = 0
            
            # Calculate exchange rate
            exchange_rate = base_crypto_atoms / fiat_amount if fiat_amount > 0 else 0
            
            # Create transaction data
            transaction_data = CreateLamassuTransactionData(
                lamassu_transaction_id=transaction["transaction_id"],
                fiat_amount=fiat_amount,
                crypto_amount=crypto_atoms,
                commission_percentage=commission_percentage,
                discount=discount,
                effective_commission=effective_commission,
                commission_amount_sats=commission_amount_sats,
                base_amount_sats=base_crypto_atoms,
                exchange_rate=exchange_rate,
                crypto_code=transaction.get("crypto_code", "BTC"),
                fiat_code=transaction.get("fiat_code", "GTQ"),
                device_id=transaction.get("device_id"),
                transaction_time=transaction.get("transaction_time")
            )
            
            # Store in database
            stored_transaction = await create_lamassu_transaction(transaction_data)
            logger.info(f"Stored Lamassu transaction {transaction['transaction_id']} in database")
            return stored_transaction.id
            
        except Exception as e:
            logger.error(f"Error storing Lamassu transaction {transaction.get('transaction_id', 'unknown')}: {e}")
            return None

    async def send_commission_payment(self, transaction: Dict[str, Any], commission_amount_sats: int) -> bool:
        """Send commission to the configured commission wallet"""
        try:
            # Get the configuration to find commission wallet
            admin_config = await get_active_lamassu_config()
            if not admin_config or not admin_config.commission_wallet_id:
                logger.info("No commission wallet configured - commission remains in source wallet")
                return True  # Not an error, just no transfer needed
            
            if not admin_config.source_wallet_id:
                logger.error("No source wallet configured - cannot send commission")
                return False
            
            transaction_id = transaction["transaction_id"]
            
            # Create invoice in commission wallet with DCA metrics
            fiat_amount = transaction.get("fiat_amount", 0)
            commission_percentage = transaction.get("commission_percentage", 0) * 100  # Convert to percentage
            commission_memo = f"DCA Commission: {commission_amount_sats:,} sats • {commission_percentage:.1f}% • {fiat_amount:,} GTQ transaction"
            
            commission_payment = await create_invoice(
                wallet_id=admin_config.commission_wallet_id,
                amount=commission_amount_sats,
                internal=True,
                memo=commission_memo,
                extra={
                    "tag": "dca_commission",
                    "lamassu_transaction_id": transaction_id,
                    "commission_amount": commission_amount_sats
                }
            )
            
            if not commission_payment:
                logger.error(f"Failed to create commission invoice for transaction {transaction_id}")
                return False
            
            # Pay the commission invoice from source wallet
            await pay_invoice(
                payment_request=commission_payment.bolt11,
                wallet_id=admin_config.source_wallet_id,
                description=commission_memo,
                extra={
                    "tag": "dca_commission_payment",
                    "lamassu_transaction_id": transaction_id
                }
            )
            
            logger.info(f"Commission payment completed: {commission_amount_sats} sats sent to commission wallet for transaction {transaction_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending commission payment for transaction {transaction.get('transaction_id', 'unknown')}: {e}")
            return False

    async def process_transaction(self, transaction: Dict[str, Any]) -> None:
        """Process a single transaction - calculate and distribute DCA payments"""
        try:
            transaction_id = transaction["transaction_id"]
            
            # Check if transaction already processed
            existing_payments = await get_payments_by_lamassu_transaction(transaction_id)
            if existing_payments:
                logger.info(f"Transaction {transaction_id} already processed - skipping")
                return
            
            logger.info(f"Processing new transaction: {transaction_id}")
            
            # First, credit the source wallet with the full transaction amount
            credit_success = await self.credit_source_wallet(transaction)
            if not credit_success:
                logger.error(f"Failed to credit source wallet for transaction {transaction_id} - skipping distribution")
                return
            
            # Store the transaction in our database for audit and UI
            stored_transaction = await self.store_lamassu_transaction(transaction)
            
            # Calculate distribution amounts
            distributions = await self.calculate_distribution_amounts(transaction)
            
            if not distributions:
                logger.info(f"No distributions calculated for transaction {transaction_id}")
                return
            
            # Calculate commission amount for sending to commission wallet
            crypto_atoms = transaction.get("crypto_amount", 0)
            commission_percentage = transaction.get("commission_percentage") or 0.0
            discount = transaction.get("discount") or 0.0
            
            if commission_percentage and commission_percentage > 0:
                effective_commission = commission_percentage * (100 - discount) / 100
                base_crypto_atoms = int(crypto_atoms / (1 + effective_commission))
                commission_amount_sats = crypto_atoms - base_crypto_atoms
            else:
                commission_amount_sats = 0
            
            # Distribute to clients
            await self.distribute_to_clients(transaction, distributions)
            
            # Send commission to commission wallet (if configured)
            if commission_amount_sats > 0:
                await self.send_commission_payment(transaction, commission_amount_sats)
            
            # Update distribution statistics in stored transaction
            if stored_transaction:
                clients_count = len(distributions)
                distributions_total_sats = sum(dist["sats_amount"] for dist in distributions.values())
                await update_lamassu_transaction_distribution_stats(
                    stored_transaction, 
                    clients_count, 
                    distributions_total_sats
                )
            
            logger.info(f"Successfully processed transaction {transaction_id}")
            
        except Exception as e:
            logger.error(f"Error processing transaction {transaction.get('transaction_id', 'unknown')}: {e}")
    
    async def poll_and_process(self) -> None:
        """Main polling function - checks for new transactions and processes them"""
        config_id = None
        try:
            logger.info("Starting Lamassu transaction polling...")
            
            # Get database configuration
            db_config = await self.connect_to_lamassu_db()
            if not db_config:
                logger.error("Could not get Lamassu database configuration - skipping this poll")
                return
            
            config_id = db_config["config_id"]
            
            # Record poll start time
            await update_poll_start_time(config_id)
            logger.info("Poll start time recorded")
            
            # Fetch new transactions via SSH
            new_transactions = await self.fetch_new_transactions(db_config)
            
            # Process each transaction
            transactions_processed = 0
            for transaction in new_transactions:
                await self.process_transaction(transaction)
                transactions_processed += 1
            
            # Record successful poll completion
            await update_poll_success_time(config_id)
            logger.info(f"Completed processing {transactions_processed} transactions. Poll success time recorded.")
                
        except Exception as e:
            logger.error(f"Error in polling cycle: {e}")
            # Don't update success time on error, but poll start time remains as attempted


# Global processor instance
transaction_processor = LamassuTransactionProcessor()


async def poll_lamassu_transactions() -> None:
    """Entry point for the polling task"""
    await transaction_processor.poll_and_process()
