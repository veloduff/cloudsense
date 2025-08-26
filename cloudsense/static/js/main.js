// CloudSense Main JavaScript

let costChart;
let currentData = null;
let selectedService = null;
const serviceColors = ['#3b82f6', '#8b5cf6', '#06b6d4', '#f59e0b', '#10b981', '#f97316', '#6366f1', '#14b8a6', '#a855f7', '#0ea5e9'];
const CACHE_DURATION = 60 * 60 * 1000; // 1 hour

// Cache management functions
function getCacheKey(url) {
    return 'aws_cost_' + btoa(url).replace(/[^a-zA-Z0-9]/g, '');
}

function getCachedData(url) {
    try {
        const key = getCacheKey(url);
        const cached = localStorage.getItem(key);
        if (cached) {
            const data = JSON.parse(cached);
            if (Date.now() - data.timestamp < CACHE_DURATION) {
                return data.response;
            }
            localStorage.removeItem(key);
        }
    } catch (e) {
        console.error('Error accessing cache:', e);
    }
    return null;
}

function setCachedData(url, response) {
    try {
        const key = getCacheKey(url);
        localStorage.setItem(key, JSON.stringify({
            timestamp: Date.now(),
            response: response
        }));
    } catch (e) {
        console.error('Error setting cache:', e);
    }
}

async function fetchWithCache(url) {
    const cached = getCachedData(url);
    if (cached) {
        updateCacheStatus(url, true);
        return cached;
    }
    
    const response = await fetch(url);
    if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
    }
    const data = await response.json();
    setCachedData(url, data);
    updateCacheStatus(url, false);
    return data;
}

function updateCacheStatus(url, fromCache) {
    const statusDiv = document.getElementById('cacheStatus');
    
    if (fromCache) {
        const key = getCacheKey(url);
        const cached = localStorage.getItem(key);
        if (cached) {
            const data = JSON.parse(cached);
            const cacheTime = new Date(data.timestamp);
            const dateStr = cacheTime.toLocaleDateString();
            const timeStr = cacheTime.toLocaleTimeString();
            const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
            statusDiv.textContent = `Cost data updated: ${dateStr} ${timeStr} (${timezone})`;
            statusDiv.style.color = '#28a745';
        }
    } else {
        const now = new Date();
        const dateStr = now.toLocaleDateString();
        const timeStr = now.toLocaleTimeString();
        const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
        statusDiv.textContent = `Cost data updated: ${dateStr} ${timeStr} (${timezone})`;
        statusDiv.style.color = '#007bff';
    }
}

function clearCache() {
    const keys = Object.keys(localStorage);
    keys.forEach(key => {
        if (key.startsWith('aws_cost_')) {
            localStorage.removeItem(key);
        }
    });
}

async function forceRefresh() {
    // Clear both client and server cache for complete refresh
    clearCache();
    
    try {
        // Clear server-side cache
        await fetch('/api/cache/clear', { method: 'POST' });
        showSuccess('Cache cleared - refreshing data...');
    } catch (error) {
        console.warn('Could not clear server cache:', error);
    }
    
    await refreshData();
}

async function showCacheStats() {
    try {
        const response = await fetch('/api/cache/stats');
        const stats = await response.json();
        
        const message = `
Server Cache Statistics:
• Total entries: ${stats.total_entries}
• Hit rate: ${stats.hit_rate_percent}%
• Cache hits: ${stats.hits}
• Cache misses: ${stats.misses}
• Total requests: ${stats.total_requests}
• Evictions: ${stats.evictions}
        `;
        
        alert(message);
    } catch (error) {
        console.error('Error fetching cache stats:', error);
        
        // Check if it's a network/connection error
        if (error.message.includes('Failed to fetch') || error.message.includes('fetch')) {
            showError('Unable to connect to CloudSense server. Is the CloudSense GUI running?');
        } else {
            showError('Failed to fetch cache statistics');
        }
    }
}

// Data fetching functions
async function fetchBillingData() {
    const timeRange = document.getElementById('timeRange').value;
    const region = document.getElementById('regionFilter').value;
    const specificDate = document.getElementById('specificDate').value;
    
    let url;
    if (specificDate) {
        url = `/api/billing?region=${encodeURIComponent(region)}&date=${encodeURIComponent(specificDate)}`;
    } else if (isMonthlyView()) {
        let month;
        if (timeRange === 'current-month') {
            month = 'current';
        } else if (timeRange === 'previous-month') {
            month = 'previous';
        } else if (timeRange === 'custom-month') {
            month = document.getElementById('customMonth').value || 'current';
        }
        url = `/api/billing?month=${encodeURIComponent(month)}&region=${encodeURIComponent(region)}`;
    } else {
        url = `/api/billing?days=${encodeURIComponent(timeRange)}&region=${encodeURIComponent(region)}`;
    }
    
    try {
        return await fetchWithCache(url);
    } catch (error) {
        console.error('Error fetching billing data:', error);
        
        // Check if it's a network/connection error
        if (error.message.includes('Failed to fetch') || error.message.includes('fetch')) {
            return { 
                error: 'Unable to connect to CloudSense server. Is the CloudSense GUI running?' 
            };
        }
        
        return { error: 'Failed to fetch billing data: ' + error.message };
    }
}

function isMonthlyView() {
    const timeRange = document.getElementById('timeRange').value;
    return ['current-month', 'previous-month', 'custom-month'].includes(timeRange);
}

async function loadRegions() {
    try {
        const response = await fetch('/api/regions');
        const regions = await response.json();
        const select = document.getElementById('regionFilter');
        
        // Sort regions to put 'global' at the top (after 'all')
        const sortedRegions = regions.sort((a, b) => {
            if (a === 'all') return -1;
            if (b === 'all') return 1;
            if (a === 'global') return -1;
            if (b === 'global') return 1;
            return a.localeCompare(b);
        });
        
        sortedRegions.forEach(region => {
            const option = document.createElement('option');
            option.value = region;
            // Change display name for global
            option.textContent = region === 'global' ? 'Global Services' : region;
            select.appendChild(option);
        });
    } catch (error) {
        console.error('Error loading regions:', error);
        
        // Check if it's a network/connection error
        if (error.message.includes('Failed to fetch') || error.message.includes('fetch')) {
            showError('Unable to connect to CloudSense server. Is the CloudSense GUI running?');
        } else {
            showError('Failed to load AWS regions');
        }
    }
}

// Removed trend tracking for simplicity

// UI update functions
function updateMetrics(data) {
    const totalCost = data.totalCost || 0;
    const timeRange = document.getElementById('timeRange').value;
    const specificDate = document.getElementById('specificDate').value;
    
    let days, dailyAvg, projectedCost, totalCostLabel, periodLabel;
    
    if (isMonthlyView()) {
        totalCostLabel = 'Total Cost';
        periodLabel = 'Month to date';
        days = new Date().getDate();
        dailyAvg = totalCost / days;
        projectedCost = dailyAvg * 30;
    } else if (specificDate) {
        totalCostLabel = 'Total Cost';
        periodLabel = 'Single day';
        days = 1;
        dailyAvg = totalCost;
        projectedCost = totalCost * 30;
    } else {
        totalCostLabel = 'Total Cost';
        periodLabel = `Last ${timeRange} days`;
        days = parseInt(timeRange) || 30;
        dailyAvg = totalCost / days;
        projectedCost = dailyAvg * 30;
    }
    
    const budgetLimit = parseFloat(document.getElementById('budgetLimit').value) || 0;
    const budgetUsed = budgetLimit > 0 ? (totalCost / budgetLimit * 100) : 0;
    const budgetRemaining = budgetLimit > 0 ? (budgetLimit - totalCost) : 0;

    // Update metric values with enhanced formatting
    document.getElementById('totalCost').textContent = formatCurrencyEnhanced(totalCost);
    document.getElementById('totalCostLabel').textContent = totalCostLabel;
    document.getElementById('totalCostPeriod').textContent = periodLabel;
    
    document.getElementById('dailyAvg').textContent = formatCurrencyEnhanced(dailyAvg);
    
    document.getElementById('projectedCost').textContent = formatCurrencyEnhanced(projectedCost);
    
    document.getElementById('budgetUsed').textContent = `${budgetUsed.toFixed(1)}%`;
    if (budgetLimit > 0) {
        document.getElementById('budgetRemaining').textContent = `${formatCurrencyEnhanced(budgetRemaining)} remaining`;
    } else {
        document.getElementById('budgetRemaining').textContent = 'No budget set';
    }

    // Update budget progress bar
    updateBudgetProgress(budgetUsed);

    // Update budget status indicator
    updateBudgetStatus(budgetUsed, budgetLimit);

    updateAlerts(budgetUsed, projectedCost, budgetLimit);
}

function formatCurrencyEnhanced(amount) {
    if (amount === 0) return '$0.00';
    if (amount < 0.01) return '<$0.01';
    if (amount >= 1000000) return `$${(amount / 1000000).toFixed(1)}M`;
    if (amount >= 1000) return `$${(amount / 1000).toFixed(1)}K`;
    return `$${amount.toFixed(2)}`;
}

// Trend indicators removed for simplicity

function updateBudgetProgress(budgetUsed) {
    const progressFill = document.getElementById('budgetProgress');
    if (!progressFill) return;
    
    const clampedUsage = Math.min(budgetUsed, 100);
    progressFill.style.width = `${clampedUsage}%`;
    
    // Remove existing progress classes
    progressFill.classList.remove('progress-warning', 'progress-danger');
    
    // Add appropriate class based on usage
    if (budgetUsed >= 100) {
        progressFill.classList.add('progress-danger');
    } else if (budgetUsed >= 80) {
        progressFill.classList.add('progress-warning');
    }
}

function updateBudgetStatus(budgetUsed, budgetLimit) {
    const statusElement = document.getElementById('budgetStatus');
    if (!statusElement) return;
    
    const indicator = statusElement.querySelector('.status-indicator');
    if (!indicator) return;
    
    // Remove existing status classes
    indicator.classList.remove('status-good', 'status-warning', 'status-danger');
    
    if (budgetLimit === 0) {
        indicator.textContent = 'No Budget';
        indicator.classList.add('status-neutral');
    } else if (budgetUsed >= 100) {
        indicator.textContent = 'Over Budget';
        indicator.classList.add('status-danger');
    } else if (budgetUsed >= 80) {
        indicator.textContent = 'High Usage';
        indicator.classList.add('status-warning');
    } else {
        indicator.textContent = 'On Track';
        indicator.classList.add('status-good');
    }
}

function formatCurrency(amount) {
    if (amount < 0.01) {
        return `$${amount.toFixed(4)}`;
    } else if (amount < 1) {
        return `$${amount.toFixed(3)}`;
    } else {
        return `$${amount.toFixed(2)}`;
    }
}

function updateAlerts(budgetUsed, projectedCost, budgetLimit) {
    // Budget alerts removed - budget card shows all necessary information
    const alertsDiv = document.getElementById('alerts');
    alertsDiv.innerHTML = '';
}

function showError(message) {
    const alertsDiv = document.getElementById('alerts');
    alertsDiv.innerHTML = `<div class="alert alert-danger">Error: ${message}</div>`;
}

function showSuccess(message) {
    const alertsDiv = document.getElementById('alerts');
    alertsDiv.innerHTML = `<div class="alert alert-success">${message}</div>`;
}

// Chart functions
async function updateChart(data) {
    const ctx = document.getElementById('costChart').getContext('2d');
    
    if (costChart) {
        costChart.destroy();
    }

    let chartData, chartLabel, dailyServiceBreakdown;
    if (selectedService) {
        const serviceData = await fetchServiceData(selectedService);
        chartData = serviceData.dailyCosts || [];
        chartLabel = `${selectedService} Daily Cost`;
    } else {
        chartData = data.dailyCosts || [];
        chartLabel = isMonthlyView() ? 'Daily Cost Breakdown' : 'Total Daily Cost';
    }
    dailyServiceBreakdown = data.dailyServiceBreakdown;

    const chartType = document.getElementById('chartType').value;
    let chartConfig;

    if (chartType === 'pie' && !selectedService) {
        const services = isMonthlyView() ? (data.services || []) : (data.serviceBreakdown || []);
        chartConfig = {
            type: 'pie',
            data: {
                labels: services.map(s => s.service),
                datasets: [{
                    data: services.map(s => s.cost),
                    backgroundColor: services.map((s, i) => serviceColors[i % serviceColors.length])
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                return context.label + ': ' + formatCurrency(context.parsed);
                            }
                        }
                    }
                }
            }
        };
    } else if (chartType === 'bar' && !selectedService && dailyServiceBreakdown) {
        const services = isMonthlyView() ? (data.services || []) : (data.serviceBreakdown || []);
        const allServices = services.map(s => s.service);
        
        chartConfig = {
            type: 'bar',
            data: {
                labels: chartData.map(d => d.date),
                datasets: allServices.map((service, index) => ({
                    label: service,
                    data: dailyServiceBreakdown[service] || [],
                    backgroundColor: serviceColors[index % serviceColors.length]
                }))
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    x: { stacked: true },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return formatCurrency(value);
                            }
                        }
                    }
                }
            }
        };
    } else {
        chartConfig = {
            type: chartType === 'pie' ? 'line' : chartType,
            data: {
                labels: chartData.map(d => d.date),
                datasets: [{
                    label: chartLabel,
                    data: chartData.map(d => d.cost),
                    borderColor: selectedService ? getServiceColor(selectedService) : '#3b82f6',
                    backgroundColor: chartType === 'bar' ? 
                        (selectedService ? getServiceColor(selectedService) : '#3b82f6') : 
                        (selectedService ? getServiceColor(selectedService) + '20' : 'rgba(59, 130, 246, 0.1)'),
                    tension: chartType === 'line' ? 0.1 : 0
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                scales: {
                    y: {
                        beginAtZero: true,
                        ticks: {
                            callback: function(value) {
                                return formatCurrency(value);
                            }
                        }
                    }
                }
            }
        };
    }

    costChart = new Chart(ctx, chartConfig);
}

async function fetchServiceData(serviceName) {
    try {
        const timeRange = document.getElementById('timeRange').value;
        const specificDate = document.getElementById('specificDate').value;
        
        let url;
        if (specificDate) {
            url = `/api/service/${encodeURIComponent(serviceName)}?date=${encodeURIComponent(specificDate)}`;
        } else if (isMonthlyView()) {
            let month;
            if (timeRange === 'current-month') {
                month = 'current';
            } else if (timeRange === 'previous-month') {
                month = 'previous';
            } else if (timeRange === 'custom-month') {
                month = document.getElementById('customMonth').value || 'current';
            }
            url = `/api/service/${encodeURIComponent(serviceName)}?month=${encodeURIComponent(month)}`;
        } else {
            url = `/api/service/${encodeURIComponent(serviceName)}?days=${encodeURIComponent(timeRange)}`;
        }
        
        return await fetchWithCache(url);
    } catch (error) {
        console.error('Error fetching service data:', error);
        return { dailyCosts: [] };
    }
}

// Service functions
function updateServicesList(data) {
    const servicesDiv = document.getElementById('servicesList');
    const services = isMonthlyView() ? (data.services || []) : (data.serviceBreakdown || []);
    
    servicesDiv.innerHTML = services.map((service, index) => {
        const color = serviceColors[index % serviceColors.length];
        return `
            <div class="service-item" onclick="showServiceChart('${escapeHtml(service.service)}')" style="border-left-color: ${color};">
                <div style="font-size: 14px; font-weight: 600; margin-bottom: 4px;">${escapeHtml(service.service)}</div>
                <div style="font-size: 16px; color: #1d4ed8; font-weight: 700;">${formatCurrency(service.cost)}</div>
                <div style="font-size: 11px; color: #666; margin-top: 2px;">${((service.cost / data.totalCost) * 100).toFixed(1)}% of total</div>
            </div>
        `;
    }).join('');
}

function showServiceChart(serviceName) {
    selectedService = serviceName;
    if (currentData) {
        updateChart(currentData);
    }
}

function getServiceColor(serviceName) {
    if (!currentData) return serviceColors[0];
    const services = isMonthlyView() ? (currentData.services || []) : (currentData.serviceBreakdown || []);
    const index = services.findIndex(s => s.service === serviceName);
    return index >= 0 ? serviceColors[index % serviceColors.length] : serviceColors[0];
}

function showAllCosts() {
    selectedService = null;
    if (currentData) {
        updateChart(currentData);
    }
}

function updateHeaderInfo(data) {
    if (data && data.accountId) {
        document.getElementById('accountInfo').textContent = `Account: ${data.accountId}`;
    } else {
        document.getElementById('accountInfo').textContent = 'Account: Unknown';
    }
    if (data && data.dateRange) {
        document.getElementById('dateRange').textContent = `Date Range: ${data.dateRange}`;
    } else {
        document.getElementById('dateRange').textContent = 'Date Range: Unknown';
    }
}

// Main refresh function
async function refreshData() {
    document.getElementById('loading').style.display = 'block';
    
    try {
        const region = document.getElementById('regionFilter').value;
        
        // For global region, skip EBS/EC2 breakdowns as they are regional services
        if (region === 'global') {
            const billingData = await fetchBillingData();
            const data = billingData;
            
            if (isMonthlyView()) {
                data.services = data.serviceBreakdown || [];
            }
            
            // Hide regional breakdowns for global view
            document.getElementById('breakdowns').style.display = 'none';
            
            if (data.error) {
                showError(data.error);
                document.getElementById('accountInfo').textContent = 'Account: Error';
                document.getElementById('dateRange').textContent = 'Date Range: Error';
                return;
            }

            currentData = data;
            updateMetrics(data);
            updateChart(data);
            updateServicesList(data);
            updateHeaderInfo(data);
        } else {
            // Normal flow for all other regions
            const [billingData, ec2Data] = await Promise.all([
                fetchBillingData(),
                fetchEbsBreakdown()
            ]);
            
            const data = billingData;
            
            if (isMonthlyView()) {
                data.services = data.serviceBreakdown || [];
            }
            
            document.getElementById('breakdowns').style.display = 'block';
            updateEc2List(ec2Data);
            
            if (data.error) {
                showError(data.error);
                document.getElementById('accountInfo').textContent = 'Account: Error';
                document.getElementById('dateRange').textContent = 'Date Range: Error';
                return;
            }

            currentData = data;
            updateMetrics(data);
            updateChart(data);
            updateServicesList(data);
            updateHeaderInfo(data);
        }
        
    } catch (error) {
        console.error('Error refreshing data:', error);
        showError('Failed to refresh data: ' + error.message);
    } finally {
        document.getElementById('loading').style.display = 'none';
    }
}

// EBS/EC2 breakdown functions
async function fetchEbsBreakdown() {
    try {
        const specificDate = document.getElementById('specificDate').value;
        const region = document.getElementById('regionFilter').value;
        let url;
        if (specificDate) {
            url = `/api/daily-ebs?date=${encodeURIComponent(specificDate)}&region=${encodeURIComponent(region)}`;
        } else if (isMonthlyView()) {
            const timeRange = document.getElementById('timeRange').value;
            let month;
            if (timeRange === 'current-month') {
                month = 'current';
            } else if (timeRange === 'previous-month') {
                month = 'previous';
            } else if (timeRange === 'custom-month') {
                month = document.getElementById('customMonth').value || 'current';
            }
            url = `/api/daily-ebs?month=${encodeURIComponent(month)}&region=${encodeURIComponent(region)}`;
        } else {
            const timeRange = document.getElementById('timeRange').value;
            url = `/api/daily-ebs?days=${encodeURIComponent(timeRange)}&region=${encodeURIComponent(region)}`;
        }
        return await fetchWithCache(url);
    } catch (error) {
        console.error('Error fetching EBS breakdown:', error);
        return { breakdown: [] };
    }
}

async function fetchEc2Breakdown() {
    try {
        const specificDate = document.getElementById('specificDate').value;
        const region = document.getElementById('regionFilter').value;
        let url;
        if (specificDate) {
            url = `/api/daily-ec2?date=${encodeURIComponent(specificDate)}&region=${encodeURIComponent(region)}`;
        } else if (isMonthlyView()) {
            const timeRange = document.getElementById('timeRange').value;
            let month;
            if (timeRange === 'current-month') {
                month = 'current';
            } else if (timeRange === 'previous-month') {
                month = 'previous';
            } else if (timeRange === 'custom-month') {
                month = document.getElementById('customMonth').value || 'current';
            }
            url = `/api/daily-ec2?month=${encodeURIComponent(month)}&region=${encodeURIComponent(region)}`;
        } else {
            const timeRange = document.getElementById('timeRange').value;
            url = `/api/daily-ec2?days=${encodeURIComponent(timeRange)}&region=${encodeURIComponent(region)}`;
        }
        return await fetchWithCache(url);
    } catch (error) {
        console.error('Error fetching EC2 breakdown:', error);
        return { breakdown: [] };
    }
}

function updateEbsList(data) {
    const ebsDiv = document.getElementById('ebsList');
    const ebsHeader = document.getElementById('ebsHeader');
    const breakdown = data.breakdown || [];
    
    const totalEbs = breakdown.reduce((sum, item) => sum + item.cost, 0);
    ebsHeader.textContent = `EBS Costs: ${formatCurrency(totalEbs)}`;
    
    if (breakdown.length === 0) {
        ebsDiv.innerHTML = '<div style="text-align: center; color: #666; padding: 20px;">No EBS costs found</div>';
        return;
    }
    
    ebsDiv.innerHTML = breakdown.map((item, index) => {
        const color = serviceColors[index % serviceColors.length];
        return `
            <div class="service-item" style="border-left-color: ${color};">
                <div style="font-size: 14px; font-weight: 600; margin-bottom: 4px;">${escapeHtml(item.category)}</div>
                <div style="font-size: 16px; color: #1d4ed8; font-weight: 700;">${formatCurrency(item.cost)}</div>
            </div>
        `;
    }).join('');
}

function updateEc2List(data) {
    const ec2Div = document.getElementById('ec2List');
    const ec2Header = document.getElementById('ec2Header');
    const breakdown = data.breakdown || [];
    
    const totalEc2 = breakdown.reduce((sum, item) => sum + item.cost, 0);
    ec2Header.textContent = `EC2 Other Charges: ${formatCurrency(totalEc2)}`;
    
    if (breakdown.length === 0) {
        ec2Div.innerHTML = '<div style="text-align: center; color: #666; padding: 20px;">No EC2 other costs found</div>';
        return;
    }
    
    ec2Div.innerHTML = breakdown.map((item, index) => {
        const color = serviceColors[index % serviceColors.length];
        return `
            <div class="service-item service-item-flex" style="border-left-color: ${color};">
                <div style="font-size: 14px; font-weight: 600; flex-grow: 1;">${escapeHtml(item.category)}</div>
                <div style="font-size: 16px; color: #1d4ed8; font-weight: 700; margin-top: auto;">${formatCurrency(item.cost)}</div>
            </div>
        `;
    }).join('');
}

// Utility functions
function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// Chart type icon management
function updateChartTypeIcon() {
    const chartType = document.getElementById('chartType');
    const selectedValue = chartType.value;
    
    // Remove all chart type classes
    chartType.classList.remove('chart-line', 'chart-bar', 'chart-pie');
    
    // Add the appropriate class for the selected chart type
    chartType.classList.add(`chart-${selectedValue}`);
}

// Metric cards are now static - no interactions needed

// Event listeners
document.addEventListener('DOMContentLoaded', function() {
    // Server-side caching now handles data freshness
    // Only clear client cache if explicitly requested by user
    
    // Metric cards are now static - no initialization needed
    
    // Initialize event listeners
    document.getElementById('timeRange').addEventListener('change', () => {
        const timeRange = document.getElementById('timeRange').value;
        const customMonth = document.getElementById('customMonth');
        
        if (timeRange === 'custom-month') {
            customMonth.disabled = false;
            const now = new Date();
            customMonth.value = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
        } else {
            customMonth.disabled = true;
        }
        
        document.getElementById('specificDate').value = '';
        selectedService = null;
        refreshData();
    });
    
    document.getElementById('budgetLimit').addEventListener('input', () => {
        if (currentData) updateMetrics(currentData);
    });
    
    document.getElementById('chartType').addEventListener('change', () => {
        updateChartTypeIcon();
        if (currentData) updateChart(currentData);
    });

    document.getElementById('specificDate').addEventListener('change', () => {
        if (document.getElementById('specificDate').value) {
            document.getElementById('timeRange').value = '';
        }
        refreshData();
    });
    
    document.getElementById('customMonth').addEventListener('change', () => {
        if (document.getElementById('timeRange').value === 'custom-month') {
            refreshData();
        }
    });
    
    document.getElementById('regionFilter').addEventListener('change', () => {
        selectedService = null;
        refreshData();
    });

    // Initialize chart type icon
    updateChartTypeIcon();
    
    // Load initial data
    loadRegions();
    refreshData();
});
