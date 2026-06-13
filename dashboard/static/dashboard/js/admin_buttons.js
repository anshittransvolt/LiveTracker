// Custom Admin Button Enhancements with Lucide Icons
// This script makes admin buttons compact and adds Lucide icons

(function() {
    'use strict';

    // Load Lucide Icons library
    function loadLucide() {
        if (typeof lucide === 'undefined') {
            const script = document.createElement('script');
            script.src = 'https://unpkg.com/lucide@latest';
            script.onload = function() {
                initializeButtons();
            };
            document.head.appendChild(script);
        } else {
            initializeButtons();
        }
    }

    // Initialize buttons with icons
    function initializeButtons() {
        // Save button (primary submit)
        const saveButtons = document.querySelectorAll('.submit-row input[type="submit"][name="_save"]');
        saveButtons.forEach(btn => {
            enhanceButton(btn, 'save', 'Save', 'compact-save-btn');
        });

        // Save and add another
        const saveAddButtons = document.querySelectorAll('.submit-row input[name="_addanother"]');
        saveAddButtons.forEach(btn => {
            enhanceButton(btn, 'plus-circle', 'Save and add another', 'compact-save-add-btn');
        });

        // Save and continue editing
        const saveContinueButtons = document.querySelectorAll('.submit-row input[name="_continue"]');
        saveContinueButtons.forEach(btn => {
            enhanceButton(btn, 'pencil', 'Save and continue', 'compact-save-continue-btn');
        });

        // Delete buttons
        const deleteLinks = document.querySelectorAll('a.deletelink, .delete-confirmation input[type="submit"]');
        deleteLinks.forEach(btn => {
            enhanceButton(btn, 'trash-2', 'Delete', 'compact-delete-btn');
        });

        // Cancel/Back buttons
        const cancelLinks = document.querySelectorAll('a.cancel-link, a.button.cancel-link');
        cancelLinks.forEach(btn => {
            enhanceButton(btn, 'x-circle', 'Cancel', 'compact-cancel-btn');
        });

        // Add buttons
        const addLinks = document.querySelectorAll('a.addlink');
        addLinks.forEach(btn => {
            enhanceButton(btn, 'plus', null, 'compact-add-btn');
        });

        // Inline add row buttons
        const inlineAddButtons = document.querySelectorAll('.add-row a');
        inlineAddButtons.forEach(btn => {
            enhanceButton(btn, 'plus', 'Add another', 'compact-inline-add-btn');
        });

        // Inline delete buttons
        const inlineDeleteLinks = document.querySelectorAll('.inline-deletelink');
        inlineDeleteLinks.forEach(btn => {
            enhanceButton(btn, 'trash-2', '', 'compact-inline-delete-btn', true);
        });

        // Action buttons (bulk actions)
        const actionButtons = document.querySelectorAll('.actions button, .actions input[type="submit"]');
        actionButtons.forEach(btn => {
            enhanceButton(btn, 'zap', 'Go', 'compact-action-btn');
        });

        // Initialize Lucide icons
        if (typeof lucide !== 'undefined') {
            lucide.createIcons();
        }
    }

    // Enhance individual button with icon
    function enhanceButton(button, iconName, newText, className, iconOnly = false) {
        if (!button || button.dataset.enhanced) return;
        
        button.dataset.enhanced = 'true';
        button.classList.add(className);

        // Get original text if not specified
        const originalText = button.value || button.textContent || button.innerText || '';
        const displayText = newText !== null ? newText : originalText;

        // Create icon element
        const icon = document.createElement('i');
        icon.setAttribute('data-lucide', iconName);
        icon.style.width = '16px';
        icon.style.height = '16px';
        icon.style.marginRight = iconOnly ? '0' : '6px';

        if (button.tagName === 'INPUT') {
            // For input buttons, wrap in a container
            const wrapper = document.createElement('button');
            wrapper.type = 'submit';
            wrapper.name = button.name;
            wrapper.value = button.value;
            wrapper.className = button.className;
            wrapper.style.cssText = button.style.cssText;
            
            // Copy all data attributes
            Array.from(button.attributes).forEach(attr => {
                if (attr.name.startsWith('data-')) {
                    wrapper.setAttribute(attr.name, attr.value);
                }
            });

            wrapper.appendChild(icon);
            if (!iconOnly) {
                const span = document.createElement('span');
                span.textContent = displayText;
                wrapper.appendChild(span);
            }

            button.parentNode.replaceChild(wrapper, button);
        } else {
            // For links and buttons
            const originalHTML = button.innerHTML;
            button.innerHTML = '';
            button.appendChild(icon);
            
            if (!iconOnly) {
                const span = document.createElement('span');
                span.textContent = displayText || originalHTML.replace(/<[^>]*>/g, '').trim();
                button.appendChild(span);
            }
        }
    }

    // Run when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', loadLucide);
    } else {
        loadLucide();
    }

    // Re-run for dynamically loaded content (inlines)
    const observer = new MutationObserver(function(mutations) {
        mutations.forEach(function(mutation) {
            if (mutation.addedNodes.length) {
                setTimeout(initializeButtons, 100);
            }
        });
    });

    if (document.body) {
        observer.observe(document.body, {
            childList: true,
            subtree: true
        });
    }
})();
