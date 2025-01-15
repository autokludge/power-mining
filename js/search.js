import formStorage from './storage.js';

class MiningSearch {
    constructor() {
        this.form = document.getElementById('searchForm');
        this.loadingIndicator = document.querySelector('.loading');
        this.loadingOverlay = document.querySelector('.loading-overlay');
        this.resultsTable = document.getElementById('resultsTable');
        this.resultsBody = this.resultsTable.querySelector('tbody');
        this.useMaxPrice = false;
        this.selectedMaterials = new Set(['Default']);
        this.selectedMiningTypes = new Set(['All']);
        this.formStorage = formStorage;
        
        // Create and add spinner
        const spinnerContainer = document.getElementById('spinner-container');
        spinnerContainer.appendChild(createSpinner());
        
        // Load spinner CSS
        const link = document.createElement('link');
        link.rel = 'stylesheet';
        link.type = 'text/css';
        link.href = '/img/loading/spinner.css';
        document.head.appendChild(link);
        
        // Bind methods to this instance
        this.toggleAllSignals = this.toggleAllSignals.bind(this);
        this.setupMaterialsAutocomplete = this.setupMaterialsAutocomplete.bind(this);
        this.setupMiningTypeAutocomplete = this.setupMiningTypeAutocomplete.bind(this);
        
        this.setupEventListeners();
        this.setupMaterialsAutocomplete();
        this.setupMiningTypeAutocomplete();
    }

    setupEventListeners() {
        this.form.addEventListener('submit', (e) => {
            e.preventDefault();
            this.handleSearch();
        });
    }

    async handleSearch() {
        this.formStorage.saveFormValues(this); // Pass the MiningSearch instance
        this.showLoading();
        
        // Reset table class and headers for normal search
        const table = document.getElementById('resultsTable');
        table.className = 'results-table';
        
        // Reset headers for normal search
        const thead = table.querySelector('thead tr');
        thead.innerHTML = `
            <th>System</th>
            <th>DST</th>
            <th>Ring Details</th>
            <th>Stations</th>
            <th>State</th>
            <th>Power</th>
        `;
        
        // Get form data
        const signal_type = document.getElementById('signal_type').value;
        if (!signal_type) {
            alert('Please select a commodity');
            this.hideLoading();
            return;
        }
        
        // Build search parameters
        const formData = new FormData(this.form);
        const params = new URLSearchParams();
        
        // Add all form fields to params
        formData.forEach((value, key) => {
            if (key === 'power_state[]') {
                // Handle multiple power states
                const states = formData.getAll('power_state[]');
                states.forEach(state => params.append('power_state[]', state));
            } else {
                params.append(key, value);
            }
        });

        // Add selected materials to params
        if (this.selectedMaterials.size > 0) {
            Array.from(this.selectedMaterials).forEach(material => {
                params.append('selected_materials[]', material);
            });
        }

        // Add selected mining types to params
        if (this.selectedMiningTypes.size > 0) {
            Array.from(this.selectedMiningTypes).forEach(type => {
                params.append('mining_types[]', type);
            });
        }
        
        try {
            const response = await fetch(`/search?${params.toString()}`);
            const results = await response.json();
            
            if (results.error) {
                this.showError(results.error);
            } else {
                this.displayResults(results);
            }
        } catch (error) {
            this.showError('Error performing search. Please try again.');
            console.error('Search error:', error);
        } finally {
            this.hideLoading();
        }
    }

    getStationIcon(stationType) {
        const iconMap = {
            'Coriolis Starport': 'Coriolis_sm.svg',
            'Orbis Starport': 'Orbis_sm.svg',
            'Ocellus Starport': 'Ocellus_sm.svg',
            'Asteroid base': 'Asteroid_Station.svg',
            'Outpost': 'Outpost_sm.svg',
            'Surface Port': 'surface_port_sm.svg',
            'Planetary Outpost': 'surface_port_sm.svg',
            'Settlement': 'settlement_sm.svg'
        };
        const icon = iconMap[stationType] || 'Outpost_sm.svg';
        return `<img src="/img/icons/${icon}" alt="${stationType}" class="station-icon">`;
    }

    async formatPrices(items) {
        try {
            const response = await fetch('/get_price_comparison', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    items: items.map(item => ({
                        price: item.price,
                        commodity: item.commodity
                    })),
                    use_max: this.useMaxPrice
                })
            });
            const data = await response.json();
            return Array.isArray(data) ? data : data.results;
        } catch (error) {
            console.error('Error getting price comparisons:', error);
            return null;
        }
    }

    formatPriceSpan(price, data) {
        const formattedPrice = price.toLocaleString();
        const priceSpan = document.createElement('span');
        if (data && typeof data === 'object') {
            if (data.color) {
                priceSpan.style.color = data.color;
            }
            priceSpan.textContent = formattedPrice + ' CR' + (data.indicator || '');
        } else {
            priceSpan.textContent = formattedPrice + ' CR';
        }
        return priceSpan;
    }

    async displayResults(results) {
        this.resultsBody.innerHTML = '';
        
        // Filter out systems with no stations
        results = results.filter(system => system.stations && system.stations.length > 0);
        
        if (results.length === 0) {
            const tr = document.createElement('tr');
            const td = document.createElement('td');
            td.setAttribute('colspan', '6');  // Span all columns
            td.textContent = 'No systems found matching your criteria';
            tr.appendChild(td);
            this.resultsBody.appendChild(tr);
            this.resultsTable.style.display = 'table';
            return;
        }

        // Get the current search type
        const searchType = document.getElementById('signal_type').value;

        // Prepare all price comparison items
        const priceItems = results.flatMap(system => 
            system.stations.map(station => ({
                price: station.sell_price,
                commodity: searchType
            }))
        );

        // Get all price comparisons in one request
        const priceData = await this.formatPrices(priceItems);
        let priceIndex = 0;

        // Get all other commodity price comparisons in one request
        const allOtherCommodityPrices = [];
        results.forEach(system => {
            system.stations.forEach(station => {
                station.other_commodities.forEach(commodity => {
                    allOtherCommodityPrices.push({
                        price: commodity.sell_price,
                        commodity: this.getCommodityCode(commodity.name),
                        systemId: system.system_id64,
                        stationName: station.name,
                        commodityName: commodity.name
                    });
                });
            });
        });
        const allOtherPriceData = await this.formatPrices(allOtherCommodityPrices);

        // Create a map to look up price data
        const priceDataMap = new Map();
        if (Array.isArray(allOtherPriceData)) {
            allOtherCommodityPrices.forEach((item, index) => {
                const key = `${item.systemId}_${item.stationName}_${item.commodityName}`;
                priceDataMap.set(key, allOtherPriceData[index]);
            });
        }

        for (const system of results) {
            const row = document.createElement('tr');
            
            // Create station list HTML
            const stationListItems = system.stations.map(station => {
                const priceComparison = Array.isArray(priceData) && priceData[priceIndex] ? priceData[priceIndex++] : null;
                const priceSpan = this.formatPriceSpan(station.sell_price, priceComparison);
                
                return `
                <li>
                    <div class="station-entry">
                        <div class="station-main">
                            ${this.getStationIcon(station.station_type)}${station.name} (${station.pad_size})
                            <div class="station-details">
                                <div>Price: ${priceSpan.outerHTML}</div>
                                <div>Demand: ${this.getDemandIcon(station.demand)} ${station.demand.toLocaleString()}</div>
                                <div>Distance: ${Math.floor(station.distance).toLocaleString()} Ls</div>
                                <div class="update-time">${this.formatUpdateTime(station.update_time)}</div>
                            </div>
                        </div>
                        ${station.other_commodities.length > 0 ? `
                            <div class="other-commodities">
                                <div class="other-commodities-title">Other Commodities:</div>
                                <div class="other-commodities-list">
                                    ${station.other_commodities
                                        .filter(commodity => {
                                            if (this.selectedMaterials.has('Default')) {
                                                return true;  // Show all in default mode
                                            }
                                            const code = this.getCommodityCode(commodity.name);
                                            return this.selectedMaterials.has(code);  // Only show explicitly selected materials
                                        })
                                        .sort((a, b) => {
                                            if (this.selectedMaterials.has('Default')) {
                                                // Default sorting by price
                                                return b.sell_price - a.sell_price;
                                            }
                                            // Sort by order in selected materials
                                            const selectedArray = Array.from(this.selectedMaterials);
                                            const aCode = this.getCommodityCode(a.name);
                                            const bCode = this.getCommodityCode(b.name);
                                            return selectedArray.indexOf(aCode) - selectedArray.indexOf(bCode);
                                        })
                                        .map(commodity => {
                                            const key = `${system.system_id64}_${station.name}_${commodity.name}`;
                                            const priceData = priceDataMap.get(key);
                                            const priceSpan = this.formatPriceSpan(commodity.sell_price, priceData);
                                            const commodityCode = this.getCommodityCode(commodity.name);
                                            return `<div class="commodity-item"><span class="commodity-code">${commodityCode}</span>${priceSpan.outerHTML} ${this.getDemandIcon(commodity.demand, true)} ${commodity.demand.toLocaleString()} Demand</div>`;
                                        }).join('')}
                                </div>
                            </div>` : ''}
                    </div>
                </li>`;
            });
            
            // Format system info
            /*console.log('System:', system.name);
            console.log('All signals:', system.all_signals);
            console.log('Rings:', system.rings);
            console.log('Search type:', searchType);*/

            // Group rings by body_name
            const ringsByPlanet = {};
            system.rings.forEach(ring => {
                const bodyName = ring.body_name;
                if (!ringsByPlanet[bodyName]) {
                    ringsByPlanet[bodyName] = [];
                }
                ringsByPlanet[bodyName].push(ring);
            });

            // Create the signal list HTML
            const signalListHtml = Object.entries(ringsByPlanet).map(([bodyName, rings]) => {
                return rings.map((ring, index) => {
                    const isFirstInPlanet = index === 0;
                    const planetIcon = isFirstInPlanet ? '<img src="/img/icons/ringed-planet-2.svg" class="planet-icon" alt="Planet">' : '<span class="planet-icon-space"></span>';
                    return `<li>${planetIcon}${ring.name}: ${ring.signals}</li>`;
                }).join('');
            }).join('');

            // Check if there are any signals not currently shown
            const hasAdditionalSignals = system.all_signals.length > system.rings.length;

            row.innerHTML = `
                <td>
                    ${system.name}
                    <img src="/img/icons/copy.svg" 
                         class="copy-icon" 
                         width="12" 
                         height="12" 
                         alt="Copy" 
                         onclick="navigator.clipboard.writeText('${system.name}').then(() => this.classList.add('copied'))"
                         onanimationend="this.classList.remove('copied')"
                         title="Copy system name">
                </td>
                <td>${this.formatNumber(system.distance)} Ly</td>
                <td>
                    <ul class="signal-list">
                        ${signalListHtml}
                    </ul>
                    ${hasAdditionalSignals ? `
                        <button class="btn btn-small show-all-signals">
                            Show all signals
                        </button>
                    ` : ''}
                </td>
                <td>
                    <ul class="station-list">
                        ${stationListItems.join('')}
                    </ul>
                </td>
                <td>${system.power_state || 'None'}</td>
                <td>${system.controlling_power || 'None'}</td>
            `;
            
            // Add click handler after the row is added to DOM
            if (hasAdditionalSignals) {
                const button = row.querySelector('.show-all-signals');
                button.addEventListener('click', () => {
                    const signalList = button.previousElementSibling;
                    const isShowingAll = button.textContent === 'Show less';
                    
                    if (!isShowingAll) {
                        // Store the original HTML before showing all signals
                        button.dataset.originalHtml = signalList.innerHTML;
                        
                        // Group signals by body_name
                        const signalsByPlanet = {};
                        system.all_signals.forEach(signal => {
                            // Format ring name - remove system name if it appears at the start
                            let displayRingName = signal.ring_name;
                            if (displayRingName.startsWith(system.name)) {
                                displayRingName = displayRingName.slice(system.name.length).trim();
                            }
                            
                            const bodyName = displayRingName.split(' Ring')[0];
                            if (!signalsByPlanet[bodyName]) {
                                signalsByPlanet[bodyName] = [];
                            }
                            signalsByPlanet[bodyName].push({...signal, ring_name: displayRingName});
                        });

                        // Create HTML for all signals, grouped by planet
                        const allSignalsHtml = Object.entries(signalsByPlanet)
                            .sort(([a], [b]) => a.localeCompare(b))  // Sort by planet name
                            .map(([bodyName, signals]) => {
                                return signals.map((signal, index) => {
                                    const isFirstInPlanet = index === 0;
                                    const planetIcon = isFirstInPlanet ? '<img src="/img/icons/ringed-planet-2.svg" class="planet-icon" alt="Planet">' : '<span class="planet-icon-space"></span>';
                                    
                                    // If signal_text is undefined, construct it from the individual fields
                                    let signalText = signal.signal_text;
                                    if (!signalText) {
                                        if (signal.mineral_type) {
                                            const hotspotText = signal.signal_count === 1 ? "Hotspot " : signal.signal_count ? "Hotspots " : "";
                                            signalText = `<img src='img/icons/hotspot-2.svg' width='11' height='11' class='hotspot-icon'> ${signal.mineral_type}: ${signal.signal_count || ''} ${hotspotText}(${signal.reserve_level})`;
                                        } else {
                                            signalText = `${signal.ring_type}, ${signal.reserve_level}`;
                                        }
                                    }
                                    
                                    return `<li>${planetIcon}${signal.ring_name}: ${signalText}</li>`;
                                }).join('');
                            }).join('');
                        
                        signalList.innerHTML = allSignalsHtml;
                        button.textContent = 'Show less';
                    } else {
                        // Restore original HTML
                        signalList.innerHTML = button.dataset.originalHtml;
                        button.textContent = 'Show all signals';
                    }
                });
            }

            this.resultsBody.appendChild(row);
        }

        this.resultsTable.style.display = 'table';
    }

    showNoResults() {
        this.resultsBody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center;">
                    No systems found matching your criteria
                </td>
            </tr>
        `;
        this.resultsTable.style.display = 'table';
    }

    showError(message) {
        this.resultsBody.innerHTML = `
            <tr>
                <td colspan="10" style="text-align: center; color: #ff4444;">
                    ${message}
                </td>
            </tr>
        `;
        this.resultsTable.style.display = 'table';
    }

    showLoading() {
        this.loadingOverlay.style.display = 'block';
        this.loadingOverlay.classList.add('visible');
        this.loadingIndicator.style.display = 'block';
        this.resultsTable.style.display = 'none';
    }

    hideLoading() {
        this.loadingOverlay.style.display = 'none';
        this.loadingOverlay.classList.remove('visible');
        this.loadingIndicator.style.display = 'none';
    }

    clearResults() {
        this.resultsBody.innerHTML = '';
        this.resultsTable.style.display = 'none';
        this.hideLoading(); // Ensure loading is hidden when clearing results
    }

    formatNumber(number) {
        return Math.floor(number).toLocaleString();
    }

    formatUpdateTime(updateTimeStr) {
        if (!updateTimeStr) return '';

        // Parse the input time string
        let dateTime;
        if (updateTimeStr.includes('T')) {
            // Handle ISO format with optional timezone
            dateTime = new Date(updateTimeStr);
        } else {
            // Handle "YYYY-MM-DD HH:mm:ss" format
            dateTime = new Date(updateTimeStr.replace(' ', 'T'));
        }

        // Add 1 hour to the time as per requirement
        dateTime.setHours(dateTime.getHours() + 1);

        // Calculate time difference in minutes
        const now = new Date();
        const diffMinutes = Math.floor((now - dateTime) / (1000 * 60));

        // Format based on time difference
        if (diffMinutes < 60) {
            return `Updated: ${diffMinutes} min ago`;
        } else if (diffMinutes < 24 * 60) {
            const hours = Math.floor(diffMinutes / 60);
            const mins = diffMinutes % 60;
            return `Updated: ${hours}h ${mins}m ago`;
        } else if (diffMinutes < 48 * 60) {
            const hours = Math.floor(diffMinutes / 60);
            return `Updated: ${hours} hours ago`;
        } else {
            const days = Math.floor(diffMinutes / (24 * 60));
            return `Updated: ${days} days ago`;
        }
    }

    getCommodityCode(name) {
        const codeMap = {
            'Aluminium': 'ALU',
            'Beryllium': 'BER',
            'Bismuth': 'BIS',
            'Bauxite': 'BAU',
            'Bertrandite': 'BRT',
            'Cobalt': 'COB',
            'Coltan': 'CLT',
            'Cryolite': 'CRY',
            'Copper': 'COP',
            'Gallite': 'GAL',
            'Gallium': 'GLM',
            'Gold': 'GLD',
            'Goslarite': 'GOS',
            'Hafnium 178': 'HAF',
            'Indium': 'IND',
            'Indite': 'IDT',
            'Jadeite': 'JAD',
            'Lanthanum': 'LAN',
            'Lepidolite': 'LEP',
            'Lithium': 'LIT',
            'Lithium Hydroxide': 'LHY',
            'Methanol Monohydrate Crystals': 'MNL',
            'Methane Clathrate': 'MCL',
            'Moissanite': 'MOI',
            'Osmium': 'OSM',
            'Palladium': 'PAL',
            'Praseodymium': 'PRA',
            'Pyrophyllite': 'PYR',
            'Rutile': 'RUT',
            'Samarium': 'SAM',
            'Silver': 'SIL',
            'Taaffeite': 'TAF',
            'Tantalum': 'TAN',
            'Thallium': 'THL',
            'Thorium': 'THR',
            'Titanium': 'TIT',
            'Uranium': 'URN',
            'Uraninite': 'URT',
            'Void Opal': 'VOP',
            'Low Temperature Diamonds': 'LTD',
            'LowTemperatureDiamond': 'LTD'
        };
        return codeMap[name] || name.substring(0, 3).toUpperCase();
    }

    toggleAllSignals(button, allSignals) {
        const signalList = button.previousElementSibling;
        const isShowingAll = button.textContent === 'Show less';
        
        if (!isShowingAll) {
            // Store the original HTML before showing all signals
            button.dataset.originalHtml = signalList.innerHTML;
            
            // Group signals by body_name
            const signalsByPlanet = {};
            allSignals.forEach(signal => {
                if (!signal.mineral_type) return;  // Skip null mineral types
                const bodyName = signal.ring_name.split(' Ring')[0];
                if (!signalsByPlanet[bodyName]) {
                    signalsByPlanet[bodyName] = [];
                }
                signalsByPlanet[bodyName].push(signal);
            });

            // Create HTML for all signals, grouped by planet
            const allSignalsHtml = Object.entries(signalsByPlanet)
                .sort(([a], [b]) => a.localeCompare(b))  // Sort by planet name
                .map(([bodyName, signals]) => {
                    return signals.map((signal, index) => {
                        const isFirstInPlanet = index === 0;
                        const planetIcon = isFirstInPlanet ? '<img src="/img/icons/ringed-planet-2.svg" class="planet-icon" alt="Planet">' : '<span class="planet-icon-space"></span>';
                        return `<li>${planetIcon}${signal.ring_name}: ${signal.signal_text}</li>`;
                    }).join('');
                }).join('');
            
            signalList.innerHTML = allSignalsHtml;
            button.textContent = 'Show less';
        } else {
            // Restore original HTML
            signalList.innerHTML = button.dataset.originalHtml;
            button.textContent = 'Show all signals';
        }
    }

    setupMaterialsAutocomplete() {
        const input = document.getElementById('materialsInput');
        const autocompleteDiv = document.getElementById('materialsAutocomplete');
        const selectedDiv = document.querySelector('.selected-materials');
        
        // Initialize with Default tag
        this.updateSelectedMaterials();

        input.addEventListener('input', () => {
            const value = input.value.toLowerCase();
            if (value.length < 2) {
                autocompleteDiv.style.display = 'none';
                return;
            }

            // Get all commodity names from the select options
            const commoditySelect = document.getElementById('signal_type');
            const commodities = ['Default'].concat(Array.from(commoditySelect.options).map(opt => opt.value));
            
            const matches = commodities
                .filter(name => name.toLowerCase().includes(value))
                .slice(0, 10);

            if (matches.length > 0) {
                autocompleteDiv.innerHTML = matches
                    .map(name => {
                        const code = name === 'Default' ? 'Default' : this.getCommodityCode(name);
                        return `<div class="autocomplete-item" data-name="${name}" data-code="${code}">${name}</div>`;
                    })
                    .join('');
                autocompleteDiv.style.display = 'block';
            } else {
                autocompleteDiv.style.display = 'none';
            }
        });

        autocompleteDiv.addEventListener('click', (e) => {
            const item = e.target.closest('.autocomplete-item');
            if (!item) return;

            const name = item.dataset.name;
            const code = item.dataset.code;

            if (name === 'Default') {
                this.selectedMaterials.clear();
                this.selectedMaterials.add('Default');
            } else {
                this.selectedMaterials.delete('Default');
                this.selectedMaterials.add(code);
            }

            this.updateSelectedMaterials();
            input.value = '';
            autocompleteDiv.style.display = 'none';
            
            // If we have results displayed, update them
            if (this.resultsTable.style.display === 'table') {
                this.handleSearch();
            }
        });

        // Close autocomplete when clicking outside
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !autocompleteDiv.contains(e.target)) {
                autocompleteDiv.style.display = 'none';
            }
        });
    }

    updateSelectedMaterials() {
        const selectedDiv = document.querySelector('.selected-materials');
        selectedDiv.innerHTML = Array.from(this.selectedMaterials)
            .map(code => `
                <span class="material-tag">
                    ${code}
                    <span class="remove" data-code="${code}">×</span>
                </span>
            `)
            .join('');

        // Add click handlers for remove buttons
        selectedDiv.querySelectorAll('.remove').forEach(btn => {
            btn.addEventListener('click', () => {
                const code = btn.dataset.code;
                this.selectedMaterials.delete(code);
                if (this.selectedMaterials.size === 0) {
                    this.selectedMaterials.add('Default');
                }
                this.updateSelectedMaterials();
                
                // If we have results displayed, update them
                if (this.resultsTable.style.display === 'table') {
                    this.handleSearch();
                }
            });
        });
    }

    setupMiningTypeAutocomplete() {
        const input = document.getElementById('miningTypeInput');
        const autocompleteDiv = document.getElementById('miningTypeAutocomplete');
        const selectedDiv = document.querySelector('.selected-mining-types');
        
        // Available mining types
        const miningTypes = ['All', 'Core', 'Laser Surface', 'Surface Deposit', 'Sub Surface Deposit'];
        
        // Set initial value
        this.selectedMiningTypes = new Set(['All']);
        this.updateSelectedMiningTypes();
        
        // Show dropdown when clicking in the input field
        input.addEventListener('click', () => {
            const matches = miningTypes.filter(type => !this.selectedMiningTypes.has(type));
            
            if (matches.length > 0) {
                autocompleteDiv.innerHTML = matches
                    .map(type => `<div class="autocomplete-item">${type}</div>`)
                    .join('');
                autocompleteDiv.style.display = 'block';
            }
        });
        
        input.addEventListener('input', () => {
            const value = input.value.toLowerCase();
            if (!value) {
                const matches = miningTypes.filter(type => !this.selectedMiningTypes.has(type));
                if (matches.length > 0) {
                    autocompleteDiv.innerHTML = matches
                        .map(type => `<div class="autocomplete-item">${type}</div>`)
                        .join('');
                    autocompleteDiv.style.display = 'block';
                } else {
                    autocompleteDiv.style.display = 'none';
                }
                return;
            }
            
            const matches = miningTypes.filter(type => 
                type.toLowerCase().includes(value) && 
                !this.selectedMiningTypes.has(type)
            );
            
            if (matches.length > 0) {
                autocompleteDiv.innerHTML = matches
                    .map(type => `<div class="autocomplete-item">${type}</div>`)
                    .join('');
                autocompleteDiv.style.display = 'block';
            } else {
                autocompleteDiv.style.display = 'none';
            }
        });

        autocompleteDiv.addEventListener('click', (e) => {
            if (e.target.classList.contains('autocomplete-item')) {
                const type = e.target.textContent;
                
                // If "All" is selected, clear other selections
                if (type === 'All') {
                    this.selectedMiningTypes.clear();
                } else {
                    // If adding a specific type, remove "All"
                    this.selectedMiningTypes.delete('All');
                }
                
                this.selectedMiningTypes.add(type);
                this.updateSelectedMiningTypes();
                
                input.value = '';
                autocompleteDiv.style.display = 'none';
                
                // If we have results displayed, update them
                if (this.resultsTable.style.display === 'table') {
                    this.handleSearch();
                }
            }
        });

        // Close autocomplete when clicking outside
        document.addEventListener('click', (e) => {
            if (!input.contains(e.target) && !autocompleteDiv.contains(e.target)) {
                autocompleteDiv.style.display = 'none';
            }
        });
    }

    updateSelectedMiningTypes() {
        const selectedDiv = document.querySelector('.selected-mining-types');
        selectedDiv.innerHTML = Array.from(this.selectedMiningTypes)
            .map(type => `
                <span class="selected-item">
                    ${type}
                    <span class="remove-item" data-value="${type}">&times;</span>
                </span>
            `)
            .join('');
        
        // Add click handlers for remove buttons
        selectedDiv.querySelectorAll('.remove-item').forEach(button => {
            button.addEventListener('click', (e) => {
                const type = e.target.dataset.value;
                this.selectedMiningTypes.delete(type);
                
                // If no types are selected, default to "All"
                if (this.selectedMiningTypes.size === 0) {
                    this.selectedMiningTypes.add('All');
                }
                
                this.updateSelectedMiningTypes();
            });
        });
    }

    async search() {
        this.showLoading();
        try {
            const table = document.getElementById('resultsTable');
            table.className = 'results-table';  // Reset to default table class
            
            // Get form data
            const formData = new FormData(document.getElementById('searchForm'));
        } catch (error) {
            console.error('Error searching:', error);
            this.hideLoading();
        }
    }

    getDemandIcon(demand, isOtherCommodity = false) {
        let iconId = 'demand-none';
        if (demand > 2000) iconId = 'demand-veryhigh';
        else if (demand > 1000) iconId = 'demand-high';
        else if (demand > 300) iconId = 'demand-medium';
        else if (demand > 100) iconId = 'demand-low';
        
        const height = isOtherCommodity ? '8' : '12';
        return `<svg class="demand-icon" width="13" height="${height}" style="margin-right: 2px;"><use href="img/icons/demand.svg#${iconId}"></use></svg>`;
    }

    showAllSignals(system) {
        const signalList = document.createElement('ul');
        signalList.className = 'signal-list';
        
        system.all_signals.forEach(signal => {
            const li = document.createElement('li');
            li.innerHTML = `<img src="/img/icons/planet.svg" width="11" height="11"> ${signal.ring_name}: ${signal.signal_text}`;
            signalList.appendChild(li);
        });
        
        const title = `All signals in ${system.name}`;
        this.showPopup(title, signalList);
    }
}

// Initialize search when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    window.miningSearch = new MiningSearch();
    // Load saved values after initialization
    formStorage.loadSavedFormValues(window.miningSearch);
});

async function searchHighest() {
    const search = window.miningSearch;
    search.clearResults();
    search.showLoading();
    
    // Get power filters
    const controllingPower = document.getElementById('controlling_power').value;
    const powerStates = Array.from(document.querySelectorAll('input[name="power_state[]"]:checked')).map(cb => cb.value);
    const limit = parseInt(document.getElementById('limit').value) || 30;
    
    // Build query parameters
    const params = new URLSearchParams();
    if (controllingPower) {
        params.append('controlling_power', controllingPower);
    }
    powerStates.forEach(state => params.append('power_state[]', state));
    params.append('limit', limit.toString());
    
    try {
        const response = await fetch('/search_highest?' + params.toString());
        const data = await response.json();
        
        if (data.error) {
            search.showError(data.error);
            return;
        }
        
        const table = document.getElementById('resultsTable');
        table.className = 'results-table highest-price-table';
        
        // Add table header
        const thead = table.querySelector('thead tr');
        thead.innerHTML = `
            <th>Material</th>
            <th>Price</th>
            <th>Demand</th>
            <th>System</th>
            <th>Station</th>
            <th>Pad Size</th>
            <th>Station Distance</th>
            <th>Reserve Level</th>
            <th>Power</th>
            <th>Power State</th>
            <th>Last Update</th>
        `;
        
        // Prepare price comparison data
        const priceItems = data.map(item => ({
            price: item.max_price,
            commodity: item.commodity_name
        }));
        
        // Get all price comparisons in one request
        const priceData = await search.formatPrices(priceItems);
        
        // Add table body
        data.forEach((item, index) => {
            const row = search.resultsBody.insertRow();
            row.insertCell().textContent = item.commodity_name;
            const priceCell = row.insertCell();
            const priceComparison = Array.isArray(priceData) ? priceData[index] : null;
            const priceSpan = search.formatPriceSpan(item.max_price, priceComparison);
            priceCell.appendChild(priceSpan);
            const demandCell = row.insertCell();
            demandCell.innerHTML = `${search.getDemandIcon(item.demand)} ${search.formatNumber(item.demand)}`;
            row.insertCell().textContent = item.system_name;
            const stationCell = row.insertCell();
            stationCell.innerHTML = search.getStationIcon(item.station_type) + item.station_name;
            row.insertCell().textContent = item.landing_pad_size;
            row.insertCell().textContent = Math.floor(item.distance_to_arrival).toLocaleString() + ' Ls';
            row.insertCell().textContent = item.reserve_level;
            row.insertCell().textContent = item.controlling_power || '-';
            row.insertCell().textContent = item.power_state || '-';
            const updateCell = row.insertCell();
            updateCell.innerHTML = item.update_time ? this.formatUpdateTime(item.update_time) : '-';
        });
        
        table.style.display = 'table';
        search.hideLoading();
    } catch (error) {
        search.showError('Error fetching results: ' + error);
        search.hideLoading();
    }
}

function togglePriceReference() {
    const search = window.miningSearch;
    search.useMaxPrice = !search.useMaxPrice;
    
    // Update toggle appearance
    const toggleSwitch = document.querySelector('.toggle-switch');
    const avgToggle = document.getElementById('avgPriceToggle');
    const maxToggle = document.getElementById('maxPriceToggle');
    
    if (search.useMaxPrice) {
        toggleSwitch.classList.add('max');
        avgToggle.classList.remove('active');
        maxToggle.classList.add('active');
    } else {
        toggleSwitch.classList.remove('max');
        maxToggle.classList.remove('active');
        avgToggle.classList.add('active');
    }
    
    // Refresh results if they exist
    if (search.resultsTable.style.display === 'table') {
        if (search.resultsTable.querySelector('thead tr').cells.length === 10) {
            searchHighest();
        } else {
            search.handleSearch();
        }
    }
}

function updateDatabasePath(input) {
    if (input.files && input.files[0]) {
        const file = input.files[0];
        document.getElementById('database').value = file.name;
        
        // Add the file path to all subsequent requests
        window.miningSearch.form.querySelector('input[name="database"]').value = file.name;
    }
}

// Make functions globally available
window.searchHighest = searchHighest;
window.togglePriceReference = togglePriceReference;
window.showLoading = showLoading;
window.hideLoading = hideLoading;

// Loading indicator functions
export function showLoading() {
    document.getElementById('loading').style.display = 'block';
}

export function hideLoading() {
    document.getElementById('loading').style.display = 'none';
} 