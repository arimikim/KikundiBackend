from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mpesa-simulator", tags=["M-Pesa Simulator"])

# HTML template for the simulator
SIMULATOR_HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Fake M-Pesa Simulator</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            max-width: 500px;
            width: 100%;
            box-shadow: 0 20px 60px rgba(0, 0, 0, 0.3);
        }
        
        h1 {
            color: #2d3748;
            margin-bottom: 10px;
            font-size: 28px;
        }
        
        .subtitle {
            color: #718096;
            margin-bottom: 30px;
            font-size: 14px;
        }
        
        .info-box {
            background: #f7fafc;
            border-left: 4px solid #4299e1;
            padding: 15px;
            margin-bottom: 30px;
            border-radius: 8px;
        }
        
        .info-box h3 {
            color: #2d3748;
            font-size: 16px;
            margin-bottom: 10px;
        }
        
        .info-box p {
            color: #4a5568;
            font-size: 14px;
            line-height: 1.6;
        }
        
        .control-group {
            margin-bottom: 25px;
        }
        
        label {
            display: block;
            color: #2d3748;
            font-weight: 600;
            margin-bottom: 8px;
            font-size: 14px;
        }
        
        .slider-container {
            display: flex;
            align-items: center;
            gap: 15px;
        }
        
        input[type="range"] {
            flex: 1;
            height: 8px;
            border-radius: 5px;
            background: #e2e8f0;
            outline: none;
            -webkit-appearance: none;
        }
        
        input[type="range"]::-webkit-slider-thumb {
            -webkit-appearance: none;
            appearance: none;
            width: 20px;
            height: 20px;
            border-radius: 50%;
            background: #667eea;
            cursor: pointer;
            transition: all 0.3s;
        }
        
        input[type="range"]::-webkit-slider-thumb:hover {
            background: #5a67d8;
            transform: scale(1.2);
        }
        
        .rate-value {
            font-weight: 700;
            color: #667eea;
            font-size: 18px;
            min-width: 60px;
            text-align: center;
        }
        
        .btn {
            width: 100%;
            padding: 15px;
            border: none;
            border-radius: 10px;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.3s;
            margin-bottom: 10px;
        }
        
        .btn-primary {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
        }
        
        .btn-primary:hover {
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.4);
        }
        
        .btn-secondary {
            background: #f7fafc;
            color: #4a5568;
            border: 2px solid #e2e8f0;
        }
        
        .btn-secondary:hover {
            background: #edf2f7;
        }
        
        .transactions-list {
            margin-top: 30px;
            max-height: 300px;
            overflow-y: auto;
        }
        
        .transaction-item {
            background: #f7fafc;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 4px solid #48bb78;
        }
        
        .transaction-item.pending {
            border-left-color: #ed8936;
        }
        
        .transaction-item small {
            color: #718096;
            display: block;
            margin-top: 5px;
        }
        
        .status-badge {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
            margin-top: 5px;
        }
        
        .status-success {
            background: #c6f6d5;
            color: #22543d;
        }
        
        .status-pending {
            background: #feebc8;
            color: #7c2d12;
        }
        
        @keyframes fadeIn {
            from {
                opacity: 0;
                transform: translateY(-10px);
            }
            to {
                opacity: 1;
                transform: translateY(0);
            }
        }
        
        .fade-in {
            animation: fadeIn 0.3s ease-in;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🏦 M-Pesa Simulator</h1>
        <p class="subtitle">Control fake M-Pesa transaction outcomes for testing</p>
        
        <div class="info-box">
            <h3>ℹ️ How it works</h3>
            <p>
                Adjust the success rate to control how many transactions succeed or fail.
                This helps you test different payment scenarios without using real money.
            </p>
        </div>
        
        <div class="control-group">
            <label for="successRate">Success Rate</label>
            <div class="slider-container">
                <input 
                    type="range" 
                    id="successRate" 
                    min="0" 
                    max="100" 
                    value="80"
                    oninput="updateRate(this.value)"
                >
                <span class="rate-value" id="rateValue">80%</span>
            </div>
        </div>
        
        <button class="btn btn-primary" onclick="applyRate()">
            Apply Success Rate
        </button>
        
        <button class="btn btn-secondary" onclick="loadTransactions()">
            Refresh Transactions
        </button>
        
        <button class="btn btn-secondary" onclick="clearTransactions()">
            Clear All Transactions
        </button>
        
        <div id="transactions" class="transactions-list"></div>
    </div>
    
    <script>
        let currentRate = 80;
        
        function updateRate(value) {
            currentRate = value;
            document.getElementById('rateValue').textContent = value + '%';
        }
        
        async function applyRate() {
            try {
                const response = await fetch('/fake-mpesa-admin/set-success-rate', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                        'Authorization': 'Bearer YOUR_TOKEN_HERE' // Update with actual token
                    },
                    body: JSON.stringify({
                        success_rate: currentRate / 100
                    })
                });
                
                const data = await response.json();
                alert(`✅ Success rate set to ${currentRate}%`);
            } catch (error) {
                console.error('Error:', error);
                alert('❌ Failed to update success rate');
            }
        }
        
        async function loadTransactions() {
            try {
                const response = await fetch('/fake-mpesa-admin/pending-transactions', {
                    headers: {
                        'Authorization': 'Bearer YOUR_TOKEN_HERE' // Update with actual token
                    }
                });
                
                const data = await response.json();
                displayTransactions(data.pending_transactions);
            } catch (error) {
                console.error('Error:', error);
            }
        }
        
        function displayTransactions(transactions) {
            const container = document.getElementById('transactions');
            
            if (Object.keys(transactions).length === 0) {
                container.innerHTML = '<p style="text-align: center; color: #718096; padding: 20px;">No pending transactions</p>';
                return;
            }
            
            let html = '<h3 style="margin-bottom: 15px; color: #2d3748;">Pending Transactions</h3>';
            
            for (const [id, tx] of Object.entries(transactions)) {
                const willSucceed = tx.will_succeed ? 'Will Succeed' : 'Will Fail';
                const statusClass = tx.will_succeed ? 'status-success' : 'status-pending';
                
                html += `
                    <div class="transaction-item fade-in">
                        <strong>KSh ${tx.amount}</strong> - ${tx.phone_number}
                        <span class="status-badge ${statusClass}">${willSucceed}</span>
                        <small>${tx.account_reference}</small>
                    </div>
                `;
            }
            
            container.innerHTML = html;
        }
        
        async function clearTransactions() {
            if (!confirm('Clear all pending transactions?')) return;
            
            try {
                const response = await fetch('/fake-mpesa-admin/clear-transactions', {
                    method: 'DELETE',
                    headers: {
                        'Authorization': 'Bearer YOUR_TOKEN_HERE' // Update with actual token
                    }
                });
                
                const data = await response.json();
                alert(`✅ Cleared ${data.cleared_count} transactions`);
                loadTransactions();
            } catch (error) {
                console.error('Error:', error);
                alert('❌ Failed to clear transactions');
            }
        }
        
        // Load transactions on page load
        loadTransactions();
        
        // Auto-refresh every 5 seconds
        setInterval(loadTransactions, 5000);
    </script>
</body>
</html>
"""

@router.get("/", response_class=HTMLResponse)
async def mpesa_simulator_ui():
    """
    M-Pesa Simulator UI
    Access this in your browser to control fake M-Pesa behavior
    """
    return SIMULATOR_HTML