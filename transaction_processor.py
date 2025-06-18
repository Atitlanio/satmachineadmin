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
from lnbits.settings import settings

from .crud import (
    get_flow_mode_clients,
    get_payments_by_lamassu_transaction,
    create_dca_payment,
    get_client_balance_summary,
    get_active_lamassu_config,
    update_config_test_result,
    update_poll_start_time,
    update_poll_success_time
)
from .models import CreateDcaPaymentData, LamassuTransaction


class LamassuTransactionProcessor:
    """Handles polling Lamassu database and processing transactions for DCA distribution"""
    
    def __init__(self):
        self.last_check_time = None
        self.processed_transaction_ids = set()
        self.ssh_process = None
        self.ssh_key_path = None
    
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
            "-o", "LogLevel=ERROR"
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
            # Write private key to temporary file
            import tempfile
            import os
            key_fd, key_path = tempfile.mkstemp(suffix='.pem')
            try:
                with os.fdopen(key_fd, 'w') as f:
                    f.write(db_config["ssh_private_key"])
                os.chmod(key_path, 0o600)
                ssh_cmd.extend(["-i", key_path])
                self.ssh_key_path = key_path  # Store for cleanup
            except Exception as e:
                os.unlink(key_path)
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
                try:
                    with os.fdopen(key_fd, 'w') as f:
                        f.write(db_config["ssh_private_key"])
                    os.chmod(key_path, 0o600)
                    ssh_cmd.extend(["-i", key_path])
                    
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
                                processed_row[key] = int(value) if value else 0
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
            lamassu_query = f"""
            SELECT 
                co.id as transaction_id,
                co.fiat as fiat_amount,
                co.crypto_atoms as crypto_amount,
                co.created as transaction_time,
                co.device_id,
                co.status,
                co.commission_percentage,
                co.discount,
                co.crypto_code,
                co.fiat_code
            FROM cash_out_txs co
            WHERE co.created > '{time_threshold_str}'
                AND co.status = 'confirmed'
            ORDER BY co.created DESC
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
            
            # Extract transaction details
            crypto_atoms = transaction["crypto_amount"]  # Total sats with commission baked in
            fiat_amount = transaction["fiat_amount"]     # Actual fiat dispensed (principal only)
            commission_percentage = transaction["commission_percentage"]  # Already stored as decimal (e.g., 0.045)
            discount = transaction.get("discount", 0.0)  # Discount percentage
            
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
                        lamassu_transaction_id=transaction_id
                    )
                    
                    # Record the payment in our database
                    dca_payment = await create_dca_payment(payment_data)
                    
                    # TODO: Actually send Bitcoin to client's wallet
                    # This will be implemented when we integrate with LNBits payment system
                    logger.info(f"DCA payment recorded for client {client_id[:8]}...: {distribution['sats_amount']} sats")
                    
                except Exception as e:
                    logger.error(f"Error processing distribution for client {client_id}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error distributing to clients: {e}")
    
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
            
            # Calculate distribution amounts
            distributions = await self.calculate_distribution_amounts(transaction)
            
            if not distributions:
                logger.info(f"No distributions calculated for transaction {transaction_id}")
                return
            
            # Distribute to clients
            await self.distribute_to_clients(transaction, distributions)
            
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