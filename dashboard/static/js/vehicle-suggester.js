/**
 * Vehicle Number Suggestor - Simple utility for registration number autocomplete
 * 
 * Usage:
 * 1. Add data-vehicle-suggester to any input field for registration numbers
 * 2. Optionally add data-project attribute to specify project (uses active project if not specified)
 * 3. Initialize with: new VehicleSuggester()
 * 
 * Example HTML:
 * <input type="text" id="vehicle-reg" data-vehicle-suggester placeholder="Enter vehicle number">
 * 
 * Or with project:
 * <input type="text" data-vehicle-suggester data-project="MBMT" placeholder="Enter vehicle number">
 */

class VehicleSuggester {
    constructor(options = {}) {
        this.options = {
            apiEndpoint: '/api/vehicle-suggestions/',
            validationEndpoint: '/api/validate-vehicle-number/',
            minChars: 1,
            debounceMs: 300,
            maxSuggestions: 10,
            dropdownClass: 'vehicle-suggester-dropdown',
            highlightClass: 'vehicle-suggester-highlight',
            ...options
        };
        
        this.debounceTimers = new Map();
        this.activeSuggesters = [];
        
        this.init();
    }
    
    init() {
        // Find all inputs with data-vehicle-suggester attribute
        const inputs = document.querySelectorAll('[data-vehicle-suggester]');
        
        inputs.forEach(input => {
            this.attachSuggester(input);
        });
    }
    
    attachSuggester(input) {
        // Store suggester instance
        input.suggester = this;
        
        // Create dropdown container
        const dropdown = document.createElement('div');
        dropdown.className = this.options.dropdownClass;
        dropdown.style.display = 'none';
        dropdown.style.position = 'absolute';
        dropdown.style.top = '100%';
        dropdown.style.left = '0';
        dropdown.style.right = '0';
        dropdown.style.maxHeight = '200px';
        dropdown.style.overflowY = 'auto';
        dropdown.style.backgroundColor = '#fff';
        dropdown.style.border = '1px solid #ddd';
        dropdown.style.borderRadius = '4px';
        dropdown.style.zIndex = '1000';
        dropdown.style.marginTop = '2px';
        
        // Position input container as relative
        if (input.parentElement.style.position !== 'relative' && input.parentElement.style.position !== 'absolute') {
            input.parentElement.style.position = 'relative';
        }
        
        input.parentElement.appendChild(dropdown);
        input.dropdown = dropdown;
        
        // Add event listeners
        input.addEventListener('input', (e) => this.handleInput(e));
        input.addEventListener('blur', (e) => this.handleBlur(e));
        input.addEventListener('focus', (e) => this.handleFocus(e));
        input.addEventListener('keydown', (e) => this.handleKeydown(e));
        
        this.activeSuggesters.push(input);
    }
    
    handleInput(e) {
        const input = e.target;
        const query = input.value.trim();
        
        // Clear existing debounce timer
        if (this.debounceTimers.has(input)) {
            clearTimeout(this.debounceTimers.get(input));
        }
        
        if (query.length < this.options.minChars) {
            input.dropdown.style.display = 'none';
            return;
        }
        
        // Debounce API call
        const timer = setTimeout(() => {
            this.fetchSuggestions(input, query);
        }, this.options.debounceMs);
        
        this.debounceTimers.set(input, timer);
    }
    
    handleFocus(e) {
        const input = e.target;
        if (input.value.trim().length >= this.options.minChars) {
            input.dropdown.style.display = 'block';
        }
    }
    
    handleBlur(e) {
        const input = e.target;
        // Delay hiding to allow click on suggestion
        setTimeout(() => {
            input.dropdown.style.display = 'none';
        }, 200);
    }
    
    handleKeydown(e) {
        const input = e.target;
        const dropdown = input.dropdown;
        const items = dropdown.querySelectorAll('.suggestion-item');
        
        if (items.length === 0) return;
        
        const active = dropdown.querySelector('.suggestion-item.active');
        
        switch(e.key) {
            case 'ArrowDown':
                e.preventDefault();
                if (!active) {
                    items[0].classList.add('active');
                } else {
                    const nextItem = active.nextElementSibling;
                    if (nextItem) {
                        active.classList.remove('active');
                        nextItem.classList.add('active');
                    }
                }
                break;
                
            case 'ArrowUp':
                e.preventDefault();
                if (active) {
                    const prevItem = active.previousElementSibling;
                    if (prevItem) {
                        active.classList.remove('active');
                        prevItem.classList.add('active');
                    } else {
                        active.classList.remove('active');
                    }
                }
                break;
                
            case 'Enter':
                e.preventDefault();
                if (active) {
                    active.click();
                }
                break;
                
            case 'Escape':
                dropdown.style.display = 'none';
                break;
        }
    }
    
    async fetchSuggestions(input, query) {
        try {
            const project = input.getAttribute('data-project') || '';
            const limit = this.options.maxSuggestions;
            
            const params = new URLSearchParams({
                q: query,
                limit: limit,
                ...(project && { project })
            });
            
            const response = await fetch(`${this.options.apiEndpoint}?${params}`);
            const data = await response.json();
            
            if (data.success && data.suggestions.length > 0) {
                this.displaySuggestions(input, data.suggestions, query);
            } else {
                input.dropdown.style.display = 'none';
            }
        } catch (error) {
            console.error('Error fetching suggestions:', error);
        }
    }
    
    displaySuggestions(input, suggestions, query) {
    const dropdown = input.dropdown;
    dropdown.innerHTML = '';
    
    suggestions.forEach((suggestion, index) => {
        const item = document.createElement('div');
        item.className = 'suggestion-item';
        item.style.padding = '8px 12px';
        item.style.cursor = 'pointer';
        item.style.borderBottom = '1px solid #f0f0f0';
        item.style.fontSize = '14px';
        
        // Highlight matching part
        const highlighted = this.highlightMatch(suggestion, query);
        item.innerHTML = highlighted;
        
        item.addEventListener('mouseenter', () => {
            document.querySelectorAll('.suggestion-item.active').forEach(el => {
                el.classList.remove('active');
            });
            item.classList.add('active');
        });

        // ✅ FIX: use pointerdown instead of click
        item.addEventListener('pointerdown', (e) => {
            e.preventDefault(); // prevents input blur
            input.value = suggestion;
            dropdown.style.display = 'none';

            input.dispatchEvent(new Event('change', { bubbles: true }));
        });

        item.addEventListener('mouseover', () => {
            item.style.backgroundColor = '#f5f5f5';
        });
        
        item.addEventListener('mouseout', () => {
            if (!item.classList.contains('active')) {
                item.style.backgroundColor = 'transparent';
            }
        });
        
        dropdown.appendChild(item);
    });
    
    dropdown.style.display = 'block';
}
    
    highlightMatch(text, query) {
        const regex = new RegExp(`(${query})`, 'gi');
        return text.replace(regex, `<span class="${this.options.highlightClass}" style="font-weight: bold; color: #2563eb;">$1</span>`);
    }
    
    /**
     * Validate if a vehicle exists in the active project
     */
    async validateVehicleNumber(registrationNumber, project = '') {
        try {
            const params = new URLSearchParams({
                registration_number: registrationNumber,
                ...(project && { project })
            });
            
            const response = await fetch(`${this.options.validationEndpoint}?${params}`);
            const data = await response.json();
            
            return data.valid;
        } catch (error) {
            console.error('Error validating vehicle:', error);
            return false;
        }
    }
}

// Auto-initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    if (document.querySelectorAll('[data-vehicle-suggester]').length > 0) {
        new VehicleSuggester();
    }
});
