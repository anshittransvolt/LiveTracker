# Vehicle Registration Number Suggester

A simple and effective autocomplete suggester for vehicle registration numbers, filtered by active project.

## Features

- **Project-based filtering**: Only suggests vehicles from the active project
- **Real-time suggestions**: As-you-type autocomplete
- **Keyboard navigation**: Arrow keys to navigate, Enter to select, Escape to close
- **Simple integration**: Just add an attribute to your input field
- **Debounced API calls**: Optimized for performance
- **Lightweight**: Minimal dependencies, pure JavaScript

## Installation

1. Include the JavaScript file in your template:
```html
<script src="{% static 'js/vehicle-suggester.js' %}"></script>
```

2. The suggester will automatically initialize on DOM ready for any inputs with `data-vehicle-suggester` attribute.

## Usage

### Basic Usage (Uses Active Project)

```html
<input 
    type="text" 
    name="registration_number"
    data-vehicle-suggester 
    placeholder="Enter vehicle number"
    class="form-control"
>
```

### Specify Project Explicitly

```html
<input 
    type="text" 
    name="registration_number"
    data-vehicle-suggester 
    data-project="MBMT"
    placeholder="Enter vehicle number (MBMT only)"
    class="form-control"
>
```

### With Form Validation

```html
<form id="myForm">
    <input 
        type="text" 
        name="vehicle_number"
        data-vehicle-suggester 
        data-project="MBMT"
        required
        placeholder="Enter vehicle number"
        id="vehicleInput"
    >
    <button type="submit">Submit</button>
</form>

<script>
document.getElementById('myForm').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const vehicleNumber = document.getElementById('vehicleInput').value;
    const project = document.getElementById('vehicleInput').getAttribute('data-project') || '';
    
    const suggester = new VehicleSuggester();
    const isValid = await suggester.validateVehicleNumber(vehicleNumber, project);
    
    if (!isValid) {
        alert('Vehicle not found in ' + project);
        return;
    }
    
    e.target.submit();
});
</script>
```

## API Endpoints

### 1. Get Suggestions

**Endpoint:** `/dashboard/api/vehicle-suggestions/`

**Method:** GET

**Query Parameters:**
- `q` (required): Search query (partial registration number)
- `project` (optional): Project name. Uses active project if not provided
- `limit` (optional): Maximum suggestions to return (default: 10, max: 50)

**Response:**
```json
{
    "success": true,
    "suggestions": ["MH01AB1234", "MH01AB1235", "MH01AB1236"],
    "count": 3,
    "query": "MH01AB",
    "project": "MBMT"
}
```

### 2. Validate Vehicle Number

**Endpoint:** `/dashboard/api/validate-vehicle-number/`

**Method:** GET

**Query Parameters:**
- `registration_number` (required): Vehicle registration number to validate
- `project` (optional): Project name. Uses active project if not provided

**Response:**
```json
{
    "valid": true,
    "registration_number": "MH01AB1234",
    "project": "MBMT"
}
```

## JavaScript API

### Manual Usage

```javascript
const suggester = new VehicleSuggester();

// Get suggestions programmatically
suggester.fetchSuggestions(inputElement, 'MH01AB');

// Validate a vehicle number
const isValid = await suggester.validateVehicleNumber('MH01AB1234', 'MBMT');
```

### Custom Options

```javascript
const suggester = new VehicleSuggester({
    apiEndpoint: '/custom/suggestions/endpoint/',
    minChars: 2,           // Minimum characters to trigger search
    debounceMs: 500,       // Debounce delay in milliseconds
    maxSuggestions: 15,    // Maximum suggestions to show
});
```

## Django Service Usage

You can also use the service directly in your views:

```python
from dashboard.services.vehicle_number_suggestion_service import VehicleNumberSuggestionService

# Get suggestions
suggestions = VehicleNumberSuggestionService.get_suggestions(
    search_query='MH01AB',
    project_name='MBMT',
    limit=10
)

# Validate a vehicle
is_valid = VehicleNumberSuggestionService.validate_vehicle_exists(
    registration_number='MH01AB1234',
    project_name='MBMT'
)

# Get all vehicles for a project
all_vehicles = VehicleNumberSuggestionService.get_all_project_vehicles('MBMT')
```

## Keyboard Shortcuts

When the dropdown is open:
- **↓** - Move down in suggestions
- **↑** - Move up in suggestions
- **Enter** - Select highlighted suggestion
- **Escape** - Close dropdown

## Example Integration in Django Form

```html
<form method="POST">
    {% csrf_token %}
    
    <div class="form-group">
        <label for="registration_number">Vehicle Number:</label>
        <input 
            type="text" 
            id="registration_number"
            name="registration_number"
            data-vehicle-suggester 
            class="form-control"
            required
        >
        <small class="form-text text-muted">Start typing to see suggestions</small>
    </div>
    
    <button type="submit" class="btn btn-primary">Submit</button>
</form>

<script src="{% static 'js/vehicle-suggester.js' %}"></script>
```

## Styling

The suggester can be customized with CSS. Default classes used:
- `.vehicle-suggester-dropdown` - Dropdown container
- `.suggestion-item` - Individual suggestion item
- `.suggestion-item.active` - Currently highlighted item
- `.vehicle-suggester-highlight` - Highlighted matching text

Example custom styling:
```css
.vehicle-suggester-dropdown {
    box-shadow: 0 4px 6px rgba(0, 0, 0, 0.1);
    border-color: #3b82f6;
}

.suggestion-item.active {
    background-color: #eff6ff;
    border-left: 3px solid #3b82f6;
    padding-left: 9px;
}

.vehicle-suggester-highlight {
    color: #2563eb;
    font-weight: 600;
}
```

## Error Handling

The API will return error responses in the following cases:

```json
{
    "success": false,
    "error": "Search query (q) is required",
    "suggestions": []
}
```

Possible errors:
- "Search query (q) is required" - Missing search query
- "Project name is required" - Missing project information
- Any database or server errors will be logged

## Notes

- Suggestions are case-insensitive
- Search performs "startswith" matching (e.g., "MH01" will match "MH01AB1234")
- Results are limited to prevent excessive database queries
- The service respects Django's authentication - only logged-in users can access the API
- Project-based filtering ensures data isolation between projects
