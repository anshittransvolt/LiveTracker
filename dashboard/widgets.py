from django import forms
from django.utils.safestring import mark_safe
import json


class KeyValueWidget(forms.Widget):
    """Custom widget for editing JSON as dynamic key-value pairs"""

    template_name = "admin/widgets/key_value_widget.html"

    class Media:
        css = {
            "all": (
                "https://cdn.jsdelivr.net/npm/lucide-static@latest/font/lucide.min.css",
            )
        }

    def render(self, name, value, attrs=None, renderer=None):
        """Render the widget with dynamic key-value input fields"""
        if attrs is None:
            attrs = {}

        # Parse the JSON value
        pairs = []
        if value:
            try:
                if isinstance(value, str):
                    data = json.loads(value)
                else:
                    data = value

                if isinstance(data, dict):
                    pairs = [{"key": k, "value": v} for k, v in data.items()]
            except (json.JSONDecodeError, TypeError):
                pass

        # Build the HTML with unique ID to avoid conflicts in inlines
        widget_id = attrs.get("id", name)
        # Make widget_id safe for JavaScript function names
        safe_widget_id = widget_id.replace("-", "_").replace(".", "_")

        html = f"""
        <div id="{widget_id}_container" class="key-value-widget" style="max-width: 800px;">
            <div style="margin-bottom: 15px; display: flex; align-items: center; gap: 10px;">
                <button type="button" onclick="addKeyValuePair_{safe_widget_id}(event)" 
                        style="padding: 8px 16px; background: #417690; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 13px; display: inline-flex; align-items: center; gap: 6px; font-weight: 500;">
                    <i data-lucide="plus" style="width: 16px; height: 16px;"></i>
                    Add New Field
                </button>
                <span style="color: #666; font-size: 12px; font-style: italic;">Add technical specifications as key-value pairs</span>
            </div>
            <div id="{widget_id}_pairs" class="key-value-pairs">
        """

        # Add existing pairs
        for i, pair in enumerate(pairs):
            html += self._render_pair(
                widget_id, safe_widget_id, i, pair["key"], pair["value"]
            )

        # If no pairs, add one empty pair
        if not pairs:
            html += self._render_pair(widget_id, safe_widget_id, 0, "", "")

        html += f"""
            </div>
            <input type="hidden" name="{name}" id="{widget_id}_hidden" value="">
        </div>
        
        <script>
        (function() {{
            let pairCount_{safe_widget_id} = {len(pairs) if pairs else 1};
            
            function updateHiddenField_{safe_widget_id}() {{
                const container = document.getElementById('{widget_id}_pairs');
                if (!container) return;
                
                const pairs = container.querySelectorAll('.key-value-pair');
                const data = {{}};
                
                pairs.forEach(pair => {{
                    const keyInput = pair.querySelector('.key-input');
                    const valueInput = pair.querySelector('.value-input');
                    if (keyInput && valueInput) {{
                        const key = keyInput.value.trim();
                        const value = valueInput.value.trim();
                        if (key) {{
                            data[key] = value;
                        }}
                    }}
                }});
                
                const hiddenField = document.getElementById('{widget_id}_hidden');
                if (hiddenField) {{
                    hiddenField.value = JSON.stringify(data);
                }}
            }}
            
            window.addKeyValuePair_{safe_widget_id} = function(event) {{
                if (event) event.preventDefault();
                const container = document.getElementById('{widget_id}_pairs');
                if (!container) return;
                
                const index = pairCount_{safe_widget_id}++;
                const html = `{self._get_pair_template(widget_id, safe_widget_id)}`.replace(/INDEX/g, index);
                container.insertAdjacentHTML('afterbegin', html);  // Add at top instead of bottom
                
                // Reinitialize Lucide icons
                if (typeof lucide !== 'undefined') {{
                    lucide.createIcons();
                }}
                
                updateHiddenField_{safe_widget_id}();
            }};
            
            window.removeKeyValuePair_{safe_widget_id} = function(index, event) {{
                if (event) event.preventDefault();
                const pair = document.getElementById('{widget_id}_pair_' + index);
                if (pair) {{
                    pair.remove();
                    updateHiddenField_{safe_widget_id}();
                }}
            }};
            
            // Initialize on DOM ready and when dynamically loaded
            function initialize_{safe_widget_id}() {{
                updateHiddenField_{safe_widget_id}();
                
                // Add event listeners to existing inputs
                const container = document.getElementById('{widget_id}_container');
                if (container) {{
                    const inputs = container.querySelectorAll('input.key-input, input.value-input');
                    inputs.forEach(input => {{
                        input.removeEventListener('input', updateHiddenField_{safe_widget_id});
                        input.addEventListener('input', updateHiddenField_{safe_widget_id});
                    }});
                }}
                
                // Initialize Lucide icons
                if (typeof lucide !== 'undefined') {{
                    lucide.createIcons();
                }}
            }}
            
            // Run on DOM ready
            if (document.readyState === 'loading') {{
                document.addEventListener('DOMContentLoaded', initialize_{safe_widget_id});
            }} else {{
                initialize_{safe_widget_id}();
            }}
            
            // Also run immediately (for inline forms)
            setTimeout(initialize_{safe_widget_id}, 100);
            
            // Add event delegation for dynamically added inputs
            const pairsContainer = document.getElementById('{widget_id}_pairs');
            if (pairsContainer) {{
                pairsContainer.addEventListener('input', function(e) {{
                    if (e.target.classList.contains('key-input') || e.target.classList.contains('value-input')) {{
                        updateHiddenField_{safe_widget_id}();
                    }}
                }});
            }}
        }})();
        </script>
        
        <script src="https://unpkg.com/lucide@latest"></script>
        """

        return mark_safe(html)

    def _render_pair(self, widget_id, safe_widget_id, index, key="", value=""):
        """Render a single key-value pair"""
        return f"""
        <div id="{widget_id}_pair_{index}" class="key-value-pair" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center; background: #f9fafb; padding: 8px; border-radius: 6px; border: 1px solid #e5e7eb;">
            <div style="flex: 1;">
                <input type="text" 
                       class="key-input vTextField" 
                       placeholder="Field name (e.g., max_speed)" 
                       value="{self._escape_html(key)}"
                       style="width: 100%; padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px; background: white;">
            </div>
            <div style="flex: 2;">
                <input type="text" 
                       class="value-input vTextField" 
                       placeholder="Value (e.g., 120 km/h)" 
                       value="{self._escape_html(value)}"
                       style="width: 100%; padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px; background: white;">
            </div>
            <button type="button" 
                    onclick="removeKeyValuePair_{safe_widget_id}({index}, event)"
                    style="padding: 8px; background: #ef4444; color: white; border: none; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: background 0.2s;"
                    onmouseover="this.style.background='#dc2626'"
                    onmouseout="this.style.background='#ef4444'"
                    title="Delete this field">
                <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i>
            </button>
        </div>
        """

    def _get_pair_template(self, widget_id, safe_widget_id):
        """Get template for dynamically added pairs"""
        template = """
        <div id="{widget_id}_pair_INDEX" class="key-value-pair" style="display: flex; gap: 8px; margin-bottom: 8px; align-items: center; background: #f9fafb; padding: 8px; border-radius: 6px; border: 1px solid #e5e7eb;">
            <div style="flex: 1;">
                <input type="text" 
                       class="key-input vTextField" 
                       placeholder="Field name (e.g., max_speed)" 
                       value=""
                       style="width: 100%; padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px; background: white;">
            </div>
            <div style="flex: 2;">
                <input type="text" 
                       class="value-input vTextField" 
                       placeholder="Value (e.g., 120 km/h)" 
                       value=""
                       style="width: 100%; padding: 7px 10px; border: 1px solid #d1d5db; border-radius: 4px; font-size: 13px; background: white;">
            </div>
            <button type="button" 
                    onclick="removeKeyValuePair_{safe_widget_id}(INDEX, event)"
                    style="padding: 8px; background: #ef4444; color: white; border: none; border-radius: 4px; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; transition: background 0.2s;"
                    onmouseover="this.style.background=\'#dc2626\'"
                    onmouseout="this.style.background=\'#ef4444\'"
                    title="Delete this field">
                <i data-lucide="trash-2" style="width: 16px; height: 16px;"></i>
            </button>
        </div>
        """
        return (
            template.replace("{widget_id}", widget_id)
            .replace("{safe_widget_id}", safe_widget_id)
            .replace("{safe_widget_id}", safe_widget_id)
        )

    def _escape_html(self, value):
        """Escape HTML special characters"""
        if value is None:
            return ""
        return (
            str(value)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&#39;")
        )

    def value_from_datadict(self, data, files, name):
        """Extract value from form data"""
        value = data.get(name, "{}")
        try:
            # Validate it's proper JSON
            json.loads(value)
            return value
        except (json.JSONDecodeError, TypeError):
            return "{}"


class KeyValueField(forms.JSONField):
    """Custom form field for JSON stored as key-value pairs"""

    widget = KeyValueWidget

    def __init__(self, *args, **kwargs):
        kwargs.setdefault("widget", self.widget)
        super().__init__(*args, **kwargs)

    def prepare_value(self, value):
        """Prepare value for display in widget"""
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}
        return value or {}
