/**
 * ========================================
 * VEHICLE NUMBER MAPPING UTILITY (JavaScript)
 * ========================================
 * Maps trolley numbers to truck numbers for display purposes.
 * 
 * IMPORTANT:
 * - Some vehicles report their trolley number instead of truck number
 * - This module provides bidirectional mapping (trolley <-> truck)
 * - All display logic should use getDisplayVehicleNumber() to show truck numbers
 * - All API calls should use the actual number from the API response
 * 
 * Usage:
 *   import { getDisplayVehicleNumber, normalizeVehicleNumber } from './vehicle_mapping.js';
 *   
 *   const displayNumber = getDisplayVehicleNumber("MH18BZ2653"); // Returns "MH18BZ2647"
 */

// Mapping: Truck Number -> Trolley Number
const TRUCK_TO_TROLLEY_MAPPING = {
    "MH18BZ2647": "MH18BZ2653",
    "MH18BZ2648": "MH18BZ2654",
    "MH18BZ2649": "MH18BZ2652",
    "MH18BZ2689": "MH18BZ2694",
    "MH18BZ2690": "MH18BZ2693",
    "MH18BZ2958": "MH18BZ2974",
    "MH18BZ2960": "MH18BZ2971",
    "MH18BZ2961": "MH18BZ2972",
    "MH18BZ2962": "MH18BZ2970",
    "MH18BZ2963": "MH18BZ2975",
    "MH18BZ2968": "MH18BZ2973",
    "MH18BZ2872": "MH18BZ3015",
    "MH18BZ2869": "MH18BZ3095",
    "MH18BZ2871": "MH18BZ3014",
    "MH18BZ3028": "MH18BZ3027",
    "MH18BZ3038": "MH18BZ3094",
    "MH18BZ3036": "MH18BZ3096",
    "MH18BZ3034": "MH18BZ3098",
    "MH18BZ3032": "MH18BZ3097",
    "MH18BZ2874": "MH18BZ2874",  // Same
    "MH18BZ2873": "MH18BZ2873",  // Same
    "MH18BZ3029": "MH18BZ3029",  // Same
    "MH18BZ3024": "MH18BZ3024",  // Same
    "MH18BZ3110": "MH18BZ3110",  // Same
    "MH18BZ3108": "MH18BZ3108",  // Same
    "MH18BZ3039": "MH18BZ3039",  // Same
    "MH18BZ3109": "MH18BZ3109",  // Same
    "MH18BZ3112": "MH18BZ3112",  // Same
    "MH18BZ3162": "MH18BZ3179",
    "MH18BZ3160": "MH18BZ3178",
    "MH18BZ3163": "MH18BZ3176",
    "MH18BZ3164": "MH18BZ3177",
    "MH18BZ3113": "MH18BZ3172",
    "MH18BZ3161": "MH18BZ3174",
    "MH18BZ3165": "MH18BZ3173",
    "MH18BZ3194": "MH18BZ3328",
    "MH18BZ3198": "MH18BZ3332",
    "MH18BZ3201": "MH18BZ3356",
    "MH18BZ3195": "MH18BZ3338",
    "MH18BZ3196": "MH18BZ3329",
    "MH18BZ3341": "MH18BZ3351",
    "MH18BZ3344": "MH18BZ3350",
    "MH18BZ3345": "MH18BZ3324",
    "MH18BZ3342": "MH18BZ3352",
    "MH18BZ3346": "MH18BZ3354",
    "MH18BZ3343": "MH18BZ3325",
    "MH18BZ3347": "MH18BZ3327",
    "MH18BZ3387": "MH18BZ3385",
    "MH18BZ3390": "MH18BZ3484",
    "MH18BZ3381": "MH18BZ3478",
    "MH18BZ3383": "MH18BZ3475",
    "MH18BZ3380": "MH18BZ3480",
    "MH18BZ3375": "MH18BZ3483",
    "MH18BZ3386": "MH18BZ3486",
    "MH18BZ3389": "MH18BZ3490",
    "MH18BZ3376": "MH18BZ3497",
    "MH18BZ3501": "MH18BZ3496",
    "MH18BZ3476": "MH18BZ3482",
    "MH18BZ3426": "MH18BZ3485",
    "MH18BZ3372": "MH18BZ3513",
    "MH18BZ3392": "MH18BZ3514",
    "MH18BZ3378": "MH18BZ3517",
    "MH18BZ3391": "MH18BZ3519",
    "MH18BZ3384": "MH18BZ3518",
    "MH18BZ3370": "MH18BZ3511",
    "HR55AY9178": "HR55AY9178",  // Same
    "MH18BZ3374": "MH18BZ3512",
    "MH18BZ3382": "MH18BZ3547",
    "MH18BZ3368": "MH18BZ3544",
    "MH18BZ3379": "MH18BZ3379",  // Same
    "MH18BZ3369": "MH18BZ3369",  // Same
};

// Reverse mapping: Trolley Number -> Truck Number (auto-generated)
const TROLLEY_TO_TRUCK_MAPPING = {};
for (const [truck, trolley] of Object.entries(TRUCK_TO_TROLLEY_MAPPING)) {
    TROLLEY_TO_TRUCK_MAPPING[trolley] = truck;
}

/**
 * Normalize vehicle number by removing spaces and converting to uppercase.
 * 
 * @param {string} vehicleNo - Vehicle number (may contain spaces)
 * @returns {string} Normalized vehicle number
 */
export function normalizeVehicleNumber(vehicleNo) {
    if (!vehicleNo) return vehicleNo;
    return String(vehicleNo).replace(/\s+/g, '').toUpperCase();
}

/**
 * Get the truck number to display on UI.
 * If a trolley number is provided, returns the corresponding truck number.
 * 
 * @param {string} vehicleNo - Vehicle number from API
 * @returns {string} Truck number for display
 * 
 * @example
 * getDisplayVehicleNumber("MH18BZ2653")  // Returns "MH18BZ2647"
 * getDisplayVehicleNumber("MH18BZ2647")  // Returns "MH18BZ2647"
 * getDisplayVehicleNumber("MH 18 BZ 2653")  // Returns "MH18BZ2647"
 */
export function getDisplayVehicleNumber(vehicleNo) {
    if (!vehicleNo) return vehicleNo;
    
    const normalized = normalizeVehicleNumber(vehicleNo);
    
    // Check if it's a trolley number, return corresponding truck
    if (normalized in TROLLEY_TO_TRUCK_MAPPING) {
        return TROLLEY_TO_TRUCK_MAPPING[normalized];
    }
    
    // If it's already a truck number or unmapped, return as-is
    return normalized;
}

/**
 * Check if a vehicle number exists in our mapping.
 * 
 * @param {string} vehicleNo - Vehicle number to check
 * @returns {boolean} True if vehicle is mapped
 */
export function isMappedVehicle(vehicleNo) {
    if (!vehicleNo) return false;
    
    const normalized = normalizeVehicleNumber(vehicleNo);
    return normalized in TRUCK_TO_TROLLEY_MAPPING || normalized in TROLLEY_TO_TRUCK_MAPPING;
}

/**
 * Get complete mapping information for a vehicle.
 * 
 * @param {string} vehicleNo - Vehicle number to look up
 * @returns {Object} Mapping information
 */
export function getVehicleMappingInfo(vehicleNo) {
    const normalized = normalizeVehicleNumber(vehicleNo);
    
    if (!normalized) {
        return {
            input: vehicleNo,
            normalized: null,
            truckNumber: null,
            trolleyNumber: null,
            isMapped: false,
            displayNumber: vehicleNo
        };
    }
    
    // Check if it's a trolley
    if (normalized in TROLLEY_TO_TRUCK_MAPPING) {
        const truck = TROLLEY_TO_TRUCK_MAPPING[normalized];
        return {
            input: vehicleNo,
            normalized,
            truckNumber: truck,
            trolleyNumber: normalized,
            isMapped: true,
            displayNumber: truck
        };
    }
    
    // Check if it's a truck
    if (normalized in TRUCK_TO_TROLLEY_MAPPING) {
        const trolley = TRUCK_TO_TROLLEY_MAPPING[normalized];
        return {
            input: vehicleNo,
            normalized,
            truckNumber: normalized,
            trolleyNumber: trolley,
            isMapped: true,
            displayNumber: normalized
        };
    }
    
    // Unmapped vehicle
    return {
        input: vehicleNo,
        normalized,
        truckNumber: normalized,
        trolleyNumber: normalized,
        isMapped: false,
        displayNumber: normalized
    };
}

// console.log('🚛 Vehicle mapping utility loaded');
