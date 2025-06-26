window.app = Vue.createApp({
  el: '#vue',
  mixins: [windowMixin],
  delimiters: ['${', '}'],
  data: function () {
    return {
      // DCA Admin Data
      dcaClients: [],
      deposits: [],
      lamassuTransactions: [],

      // Table configurations
      clientsTable: {
        columns: [
          { name: 'username', align: 'left', label: 'Username', field: 'username' },
          { name: 'user_id', align: 'left', label: 'User ID', field: 'user_id' },
          { name: 'wallet_id', align: 'left', label: 'Wallet ID', field: 'wallet_id' },
          { name: 'dca_mode', align: 'left', label: 'DCA Mode', field: 'dca_mode' },
          { name: 'remaining_balance', align: 'right', label: 'Remaining Balance', field: 'remaining_balance' },
          { name: 'fixed_mode_daily_limit', align: 'left', label: 'Daily Limit', field: 'fixed_mode_daily_limit' },
          { name: 'status', align: 'left', label: 'Status', field: 'status' }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      depositsTable: {
        columns: [
          { name: 'client_id', align: 'left', label: 'Client', field: 'client_id' },
          { name: 'amount', align: 'left', label: 'Amount', field: 'amount' },
          { name: 'currency', align: 'left', label: 'Currency', field: 'currency' },
          { name: 'status', align: 'left', label: 'Status', field: 'status' },
          { name: 'created_at', align: 'left', label: 'Created', field: 'created_at' },
          { name: 'notes', align: 'left', label: 'Notes', field: 'notes' }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      lamassuTransactionsTable: {
        columns: [
          { name: 'lamassu_transaction_id', align: 'left', label: 'Transaction ID', field: 'lamassu_transaction_id' },
          { name: 'transaction_time', align: 'left', label: 'Time', field: 'transaction_time' },
          { name: 'fiat_amount', align: 'right', label: 'Fiat Amount', field: 'fiat_amount' },
          { name: 'crypto_amount', align: 'right', label: 'Total Sats', field: 'crypto_amount' },
          { name: 'commission_amount_sats', align: 'right', label: 'Commission', field: 'commission_amount_sats' },
          { name: 'base_amount_sats', align: 'right', label: 'Base Amount', field: 'base_amount_sats' },
          { name: 'distributions_total_sats', align: 'right', label: 'Distributed', field: 'distributions_total_sats' },
          { name: 'clients_count', align: 'center', label: 'Clients', field: 'clients_count' }
        ],
        pagination: {
          rowsPerPage: 10
        }
      },
      distributionDetailsTable: {
        columns: [
          { name: 'client_username', align: 'left', label: 'Client', field: 'client_username' },
          { name: 'amount_sats', align: 'right', label: 'Amount (sats)', field: 'amount_sats' },
          { name: 'amount_fiat', align: 'right', label: 'Amount (fiat)', field: 'amount_fiat' },
          { name: 'status', align: 'center', label: 'Status', field: 'status' },
          { name: 'created_at', align: 'left', label: 'Created', field: 'created_at' }
        ]
      },

      // Dialog states  
      depositFormDialog: {
        show: false,
        data: {
          currency: 'GTQ'
        }
      },
      clientDetailsDialog: {
        show: false,
        data: null,
        balance: null
      },
      distributionDialog: {
        show: false,
        transaction: null,
        distributions: []
      },

      // Quick deposit form
      quickDepositForm: {
        selectedClient: null,
        amount: null,
        notes: ''
      },
      
      // Polling status
      lastPollTime: null,
      testingConnection: false,
      runningManualPoll: false,
      runningTestTransaction: false,
      lamassuConfig: null,
      
      // Config dialog
      configDialog: {
        show: false,
        data: {
          host: '',
          port: 5432,
          database_name: '',
          username: '',
          password: '',
          selectedWallet: null,
          selectedCommissionWallet: null,
          // SSH Tunnel settings
          use_ssh_tunnel: false,
          ssh_host: '',
          ssh_port: 22,
          ssh_username: '',
          ssh_password: '',
          ssh_private_key: ''
        }
      },

      // Options
      currencyOptions: [
        { label: 'GTQ', value: 'GTQ' },
        { label: 'USD', value: 'USD' }
      ]
    }
  },

  ///////////////////////////////////////////////////
  ////////////////METHODS FUNCTIONS//////////////////
  ///////////////////////////////////////////////////

  methods: {
    // Utility Methods
    formatCurrency(amount) {
      if (!amount) return 'Q 0.00';

      return new Intl.NumberFormat('es-GT', {
        style: 'currency',
        currency: 'GTQ',
      }).format(amount);
    },

    formatDate(dateString) {
      if (!dateString) return ''
      return new Date(dateString).toLocaleDateString()
    },

    formatDateTime(dateString) {
      if (!dateString) return ''
      const date = new Date(dateString)
      return date.toLocaleDateString() + ' ' + date.toLocaleTimeString('en-US', { hour12: false })
    },

    formatSats(amount) {
      if (!amount) return '0 sats'
      return new Intl.NumberFormat('en-US').format(amount) + ' sats'
    },

    getClientUsername(clientId) {
      const client = this.dcaClients.find(c => c.id === clientId)
      return client ? (client.username || client.user_id.substring(0, 8) + '...') : clientId
    },


    // Configuration Methods
    async getLamassuConfig() {
      try {
        const {data} = await LNbits.api.request(
          'GET',
          '/satmachineadmin/api/v1/dca/config',
          this.g.user.wallets[0].adminkey
        )
        this.lamassuConfig = data
        
        // When opening config dialog, populate the selected wallets if they exist
        if (data && data.source_wallet_id) {
          const wallet = this.g.user.wallets.find(w => w.id === data.source_wallet_id)
          if (wallet) {
            this.configDialog.data.selectedWallet = wallet
          }
        }
        if (data && data.commission_wallet_id) {
          const commissionWallet = this.g.user.wallets.find(w => w.id === data.commission_wallet_id)
          if (commissionWallet) {
            this.configDialog.data.selectedCommissionWallet = commissionWallet
          }
        }
      } catch (error) {
        // It's OK if no config exists yet
        this.lamassuConfig = null
      }
    },
    
    async saveConfiguration() {
      try {
        const data = {
          host: this.configDialog.data.host,
          port: this.configDialog.data.port,
          database_name: this.configDialog.data.database_name,
          username: this.configDialog.data.username,
          password: this.configDialog.data.password,
          source_wallet_id: this.configDialog.data.selectedWallet?.id,
          commission_wallet_id: this.configDialog.data.selectedCommissionWallet?.id,
          // SSH Tunnel settings
          use_ssh_tunnel: this.configDialog.data.use_ssh_tunnel,
          ssh_host: this.configDialog.data.ssh_host,
          ssh_port: this.configDialog.data.ssh_port,
          ssh_username: this.configDialog.data.ssh_username,
          ssh_password: this.configDialog.data.ssh_password,
          ssh_private_key: this.configDialog.data.ssh_private_key
        }
        
        const {data: config} = await LNbits.api.request(
          'POST',
          '/satmachineadmin/api/v1/dca/config',
          this.g.user.wallets[0].adminkey,
          data
        )
        
        this.lamassuConfig = config
        this.closeConfigDialog()
        
        this.$q.notify({
          type: 'positive',
          message: 'Database configuration saved successfully',
          timeout: 5000
        })
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },
    
    closeConfigDialog() {
      this.configDialog.show = false
      this.configDialog.data = {
        host: '',
        port: 5432,
        database_name: '',
        username: '',
        password: '',
        selectedWallet: null,
        selectedCommissionWallet: null,
        // SSH Tunnel settings
        use_ssh_tunnel: false,
        ssh_host: '',
        ssh_port: 22,
        ssh_username: '',
        ssh_password: '',
        ssh_private_key: ''
      }
    },

    // DCA Client Methods
    async getDcaClients() {
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/satmachineadmin/api/v1/dca/clients',
          this.g.user.wallets[0].adminkey
        )
        
        // Fetch balance data for each client
        const clientsWithBalances = await Promise.all(
          data.map(async (client) => {
            try {
              const { data: balance } = await LNbits.api.request(
                'GET',
                `/satmachineadmin/api/v1/dca/clients/${client.id}/balance`,
                this.g.user.wallets[0].adminkey
              )
              return {
                ...client,
                remaining_balance: balance.remaining_balance
              }
            } catch (error) {
              console.error(`Error fetching balance for client ${client.id}:`, error)
              return {
                ...client,
                remaining_balance: 0
              }
            }
          })
        )
        
        this.dcaClients = clientsWithBalances
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },


    // Quick Deposit Methods
    async sendQuickDeposit() {
      try {
        const data = {
          client_id: this.quickDepositForm.selectedClient?.value,
          amount: this.quickDepositForm.amount,
          currency: 'GTQ',
          notes: this.quickDepositForm.notes
        }

        const { data: newDeposit } = await LNbits.api.request(
          'POST',
          '/satmachineadmin/api/v1/dca/deposits',
          this.g.user.wallets[0].adminkey,
          data
        )

        this.deposits.unshift(newDeposit)

        // Reset form
        this.quickDepositForm = {
          selectedClient: null,
          amount: null,
          notes: ''
        }

        this.$q.notify({
          type: 'positive',
          message: 'Deposit created successfully',
          timeout: 5000
        })
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    async viewClientDetails(client) {
      try {
        const { data: balance } = await LNbits.api.request(
          'GET',
          `/satmachineadmin/api/v1/dca/clients/${client.id}/balance`,
          this.g.user.wallets[0].adminkey
        )
        this.clientDetailsDialog.data = client
        this.clientDetailsDialog.balance = balance
        this.clientDetailsDialog.show = true
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    // Deposit Methods
    async getDeposits() {
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/satmachineadmin/api/v1/dca/deposits',
          this.g.user.wallets[0].adminkey
        )
        this.deposits = data
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    addDepositDialog(client) {
      this.depositFormDialog.data = {
        client_id: client.id,
        client_name: client.username || `${client.user_id.substring(0, 8)}...`,
        currency: 'GTQ'
      }
      this.depositFormDialog.show = true
    },

    async sendDepositData() {
      try {
        const data = {
          client_id: this.depositFormDialog.data.client_id,
          amount: this.depositFormDialog.data.amount,
          currency: this.depositFormDialog.data.currency,
          notes: this.depositFormDialog.data.notes
        }

        if (this.depositFormDialog.data.id) {
          // Update existing deposit (mainly for notes/status)
          const { data: updatedDeposit } = await LNbits.api.request(
            'PUT',
            `/satmachineadmin/api/v1/dca/deposits/${this.depositFormDialog.data.id}`,
            this.g.user.wallets[0].adminkey,
            { status: this.depositFormDialog.data.status, notes: data.notes }
          )
          const index = this.deposits.findIndex(d => d.id === updatedDeposit.id)
          if (index !== -1) {
            this.deposits.splice(index, 1, updatedDeposit)
          }
        } else {
          // Create new deposit
          const { data: newDeposit } = await LNbits.api.request(
            'POST',
            '/satmachineadmin/api/v1/dca/deposits',
            this.g.user.wallets[0].adminkey,
            data
          )
          this.deposits.unshift(newDeposit)
        }

        this.closeDepositFormDialog()
        this.$q.notify({
          type: 'positive',
          message: this.depositFormDialog.data.id ? 'Deposit updated successfully' : 'Deposit created successfully',
          timeout: 5000
        })
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    closeDepositFormDialog() {
      this.depositFormDialog.show = false
      this.depositFormDialog.data = {
        currency: 'GTQ'
      }
    },

    async confirmDeposit(deposit) {
      try {
        await LNbits.utils
          .confirmDialog('Confirm that this deposit has been physically placed in the ATM machine?')
          .onOk(async () => {
            const { data: updatedDeposit } = await LNbits.api.request(
              'PUT',
              `/satmachineadmin/api/v1/dca/deposits/${deposit.id}/status`,
              this.g.user.wallets[0].adminkey,
              { status: 'confirmed', notes: 'Confirmed by admin - money placed in machine' }
            )
            const index = this.deposits.findIndex(d => d.id === deposit.id)
            if (index !== -1) {
              this.deposits.splice(index, 1, updatedDeposit)
            }
            this.$q.notify({
              type: 'positive',
              message: 'Deposit confirmed! DCA is now active for this client.',
              timeout: 5000
            })
          })
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    editDeposit(deposit) {
      this.depositFormDialog.data = { ...deposit }
      this.depositFormDialog.show = true
    },

    // Export Methods
    async exportClientsCSV() {
      await LNbits.utils.exportCSV(this.clientsTable.columns, this.dcaClients)
    },

    async exportDepositsCSV() {
      await LNbits.utils.exportCSV(this.depositsTable.columns, this.deposits)
    },

    async exportLamassuTransactionsCSV() {
      await LNbits.utils.exportCSV(this.lamassuTransactionsTable.columns, this.lamassuTransactions)
    },
    
    // Polling Methods
    async testDatabaseConnection() {
      this.testingConnection = true
      try {
        const {data} = await LNbits.api.request(
          'POST',
          '/satmachineadmin/api/v1/dca/test-connection',
          this.g.user.wallets[0].adminkey
        )
        
        // Show detailed results in a dialog
        const stepsList = data.steps ? data.steps.join('\n') : 'No detailed steps available'
        
        let dialogContent = `<strong>Connection Test Results</strong><br/><br/>`
        
        if (data.ssh_tunnel_used) {
          dialogContent += `<strong>SSH Tunnel:</strong> ${data.ssh_tunnel_success ? '✅ Success' : '❌ Failed'}<br/>`
        }
        
        dialogContent += `<strong>Database:</strong> ${data.database_connection_success ? '✅ Success' : '❌ Failed'}<br/><br/>`
        dialogContent += `<strong>Detailed Steps:</strong><br/>`
        dialogContent += stepsList.replace(/\n/g, '<br/>')
        
        this.$q.dialog({
          title: data.success ? 'Connection Test Passed' : 'Connection Test Failed',
          message: dialogContent,
          html: true,
          ok: {
            color: data.success ? 'positive' : 'negative',
            label: 'Close'
          }
        })
        
        // Also show a brief notification
        this.$q.notify({
          type: data.success ? 'positive' : 'negative',
          message: data.message,
          timeout: 3000
        })
        
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      } finally {
        this.testingConnection = false
      }
    },
    
    async manualPoll() {
      this.runningManualPoll = true
      try {
        const {data} = await LNbits.api.request(
          'POST',
          '/satmachineadmin/api/v1/dca/manual-poll',
          this.g.user.wallets[0].adminkey
        )
        
        this.lastPollTime = new Date().toLocaleString()
        this.$q.notify({
          type: 'positive',
          message: `Manual poll completed. Found ${data.transactions_processed} new transactions.`,
          timeout: 5000
        })
        
        // Refresh data
        await this.getDcaClients() // Refresh to show updated balances
        await this.getDeposits()
        await this.getLamassuTransactions()
        await this.getLamassuConfig()
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      } finally {
        this.runningManualPoll = false
      }
    },
    
    async testTransaction() {
      this.runningTestTransaction = true
      try {
        const {data} = await LNbits.api.request(
          'POST',
          '/satmachineadmin/api/v1/dca/test-transaction',
          this.g.user.wallets[0].adminkey
        )
        
        // Show detailed results in a dialog
        const details = data.transaction_details
        
        let dialogContent = `<strong>Test Transaction Results</strong><br/><br/>`
        dialogContent += `<strong>Transaction ID:</strong> ${details.transaction_id}<br/>`
        dialogContent += `<strong>Total Amount:</strong> ${details.total_amount_sats} sats<br/>`
        dialogContent += `<strong>Base Amount:</strong> ${details.base_amount_sats} sats<br/>`
        dialogContent += `<strong>Commission:</strong> ${details.commission_amount_sats} sats (${details.commission_percentage}%)<br/>`
        if (details.discount > 0) {
          dialogContent += `<strong>Discount:</strong> ${details.discount}%<br/>`
          dialogContent += `<strong>Effective Commission:</strong> ${details.effective_commission}%<br/>`
        }
        dialogContent += `<br/><strong>Check your wallets to see the distributions!</strong>`
        
        this.$q.dialog({
          title: 'Test Transaction Completed',
          message: dialogContent,
          html: true,
          ok: {
            color: 'positive',
            label: 'Great!'
          }
        })
        
        // Also show a brief notification
        this.$q.notify({
          type: 'positive',
          message: `Test transaction processed: ${details.total_amount_sats} sats distributed`,
          timeout: 5000
        })
        
        // Refresh data
        await this.getDcaClients() // Refresh to show updated balances
        await this.getDeposits()
        await this.getLamassuTransactions()
        await this.getLamassuConfig()
        
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      } finally {
        this.runningTestTransaction = false
      }
    },

    // Lamassu Transaction Methods
    async getLamassuTransactions() {
      try {
        const { data } = await LNbits.api.request(
          'GET',
          '/satmachineadmin/api/v1/dca/transactions',
          this.g.user.wallets[0].adminkey
        )
        this.lamassuTransactions = data
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

    async viewTransactionDistributions(transaction) {
      try {
        const { data: distributions } = await LNbits.api.request(
          'GET',
          `/satmachineadmin/api/v1/dca/transactions/${transaction.id}/distributions`,
          this.g.user.wallets[0].adminkey
        )
        
        this.distributionDialog.transaction = transaction
        this.distributionDialog.distributions = distributions
        this.distributionDialog.show = true
      } catch (error) {
        LNbits.utils.notifyApiError(error)
      }
    },

  },
  ///////////////////////////////////////////////////
  //////LIFECYCLE FUNCTIONS RUNNING ON PAGE LOAD/////
  ///////////////////////////////////////////////////
  async created() {
    // Load DCA admin data
    await Promise.all([
      this.getLamassuConfig(),
      this.getDcaClients(),
      this.getDeposits(),
      this.getLamassuTransactions()
    ])
  },

  computed: {
    isConfigFormValid() {
      const data = this.configDialog.data
      
      // Basic database fields are required
      const basicValid = data.host && data.database_name && data.username && data.selectedWallet
      
      // If SSH tunnel is enabled, validate SSH fields
      if (data.use_ssh_tunnel) {
        const sshValid = data.ssh_host && data.ssh_username && 
                        (data.ssh_password || data.ssh_private_key)
        return basicValid && sshValid
      }
      
      return basicValid
    },
    
    clientOptions() {
      return this.dcaClients.map(client => ({
        label: `${client.username || client.user_id.substring(0, 8) + '...'} (${client.dca_mode})`,
        value: client.id
      }))
    },

    totalDcaBalance() {
      return this.deposits
        .filter(d => d.status === 'confirmed')
        .reduce((total, deposit) => total + deposit.amount, 0)
    }
  }
})
