# ✈️ AF-KLM Fleet Catalog

Open source, community-maintained catalog of **Air France** and **KLM** fleets with real-time tracking of aircraft properties, WiFi connectivity, and historical changes.

---

## 📊 Fleet Overview

| Airline | Total | 📶 WiFi | 🛜 High-Speed | % Starlink |
|---------|-------|---------|---------------|------------|
| 🇫🇷 Air France | 220 | 220 (100%) | 41 | **19%** |
| 🇳🇱 KLM | 117 | 94 (80%) | 0 | **0%** |
| **Combined** | **337** | **314 (93%)** | **41** | **12%** |


> 🛜 **High-Speed** = Starlink satellite internet (50+ Mbps)  
> 📶 **WiFi** = Any WiFi connectivity (low-speed or high-speed)

*Last updated: 2026-02-04*

---

## 🛫 Fleet Breakdown

### 🇫🇷 Air France (AF)

| Aircraft Type | Count |
|---------------|-------|
| A220-300 PASSENGER | 46 |
| 777-300ER | 43 |
| A350-900 | 41 |
| A320 | 29 |
| 777-200-200ER | 18 |
| A321 | 12 |
| 787-9 | 10 |
| A330-200 | 8 |
| A320 (SHARKLETS) | 6 |
| A318 | 4 |
| A319 | 3 |
| **Total** | **220** |

### 🇳🇱 KLM (KL)

| Aircraft Type | Count |
|---------------|-------|
| 737-800 | 29 |
| 777-300ER | 15 |
| 787-10 | 15 |
| 777-200-200ER | 14 |
| A321NEO | 12 |
| 787-9 | 12 |
| A330-200 | 5 |
| A330-300 | 5 |
| 737-900 | 5 |
| 737-700 | 5 |
| **Total** | **117** |



---

## 📋 Detailed Configuration

### 🇫🇷 Air France — Detailed Configuration

| Aircraft | Config | Seats | Count | 🛜 Starlink |
|----------|--------|-------|-------|-------------|
| 777-200-200ER | `J028W032Y268` | 328 | 18 | - |
| 777-300ER | `J014W028Y430` | 472 | 12 | - |
| 777-300ER | `J048W048Y273` | 369 | 8 | - |
| 777-300ER | `P004J058W028Y206` | 296 | 14 | 1/14 (7%) |
| 777-300ER | `P004J060W044Y204` | 312 | 9 | 1/9 (11%) |
| 787-9 | `J030W021Y228` | 279 | 10 | - |
| A220-300 PASSENGER | `Y148` | 148 | 46 | 12/46 (26%) |
| A318 | `Y131` | 131 | 4 | - |
| A319 | `C072Y071` | 143 | 2 | - |
| A319 | `Y142` | 142 | 1 | - |
| A320 | `C108Y066` | 174 | 22 | 2/22 (9%) |
| A320 | `Y178` | 178 | 7 | - |
| A320 (SHARKLETS) | `C108Y066` | 174 | 6 | - |
| A321 | `C082Y130` | 212 | 8 | - |
| A321 | `Y212` | 212 | 4 | - |
| A330-200 | `J036W021Y167` | 224 | 8 | 1/8 (13%) |
| A350-900 | `J034W024Y266` | 324 | 20 | 10/20 (50%) |
| A350-900 | `J048W032Y210` | 290 | 1 | 1/1 (100%) |
| A350-900 | `J048W032Y212` | 292 | 20 | 13/20 (65%) |

### 🇳🇱 KLM — Detailed Configuration

| Aircraft | Config | Seats | Count | 🛜 Starlink |
|----------|--------|-------|-------|-------------|
| 737-700 | `C036M106` | 142 | 5 | - |
| 737-800 | `C036M150` | 186 | 29 | - |
| 737-900 | `C056M132` | 188 | 5 | - |
| 777-200-200ER | `C035W024M229` | 288 | 12 | - |
| 777-200-200ER | `C035W032M219` | 286 | 2 | - |
| 777-300ER | `C035W024M322` | 381 | 15 | - |
| 787-10 | `C038W028M252` | 318 | 15 | - |
| 787-9 | `C030W021M224` | 275 | 12 | - |
| A321NEO | `C030M197` | 227 | 12 | - |
| A330-200 | `C018M246` | 264 | 5 | - |
| A330-300 | `C030M262` | 292 | 5 | - |



---

## 🚀 Quick Start

### Update the Catalog

```bash
# Set your API key
export AFKLM_API_KEY=your_api_key_here

# Update Air France
node fleet-update.js --airline AF

# Update KLM  
node fleet-update.js --airline KL

# Preview changes without saving
node fleet-update.js --airline KL --dry-run

# Regenerate this README with latest stats
node generate-readme.js
```

### Using the Data

```javascript
// Load Air France fleet
const response = await fetch('https://raw.githubusercontent.com/.../airlines/AF.json');
const fleet = await response.json();

// Find all Starlink aircraft
const starlink = fleet.aircraft.filter(a => a.connectivity.wifi === 'high-speed');
console.log(`${starlink.length} aircraft with Starlink`);

// Get aircraft by type
const a350s = fleet.aircraft.filter(a => a.aircraft_type.full_name?.includes('A350'));
```

---

## 📁 Data Structure

```
af-klm/
├── airlines/
│   ├── AF.json         # Air France fleet
│   └── KL.json         # KLM fleet
├── schema/
│   └── aircraft.schema.json
├── fleet-update.js     # Update script
└── generate-readme.js  # This stats generator
```

### Aircraft Schema

```json
{
  "registration": "F-HTYA",
  "aircraft_type": {
    "iata_code": "359",
    "manufacturer": "Airbus",
    "model": "A350",
    "full_name": "AIRBUS A350-900"
  },
  "cabin": {
    "physical_configuration": "J034W024Y266",
    "total_seats": 324,
    "classes": { "business": 34, "premium_economy": 24, "economy": 266 }
  },
  "connectivity": {
    "wifi": "high-speed",
    "wifi_provider": "Starlink",
    "satellite": true
  },
  "tracking": {
    "first_seen": "2025-01-15",
    "last_seen": "2026-02-04",
    "total_flights": 1250
  },
  "history": [
    {
      "timestamp": "2026-01-20",
      "property": "connectivity.wifi",
      "old_value": "low-speed",
      "new_value": "high-speed",
      "source": "airline_api"
    }
  ]
}
```

---

## 🤝 Contributing

### Daily Updates

Community members are encouraged to run the update script daily:

1. Fork this repo
2. Set your `AFKLM_API_KEY` 
3. Run `node fleet-update.js --airline AF` and `--airline KL`
4. Run `node generate-readme.js` to update stats
5. Submit a PR

### API Key

Get a free API key at [developer.airfranceklm.com](https://developer.airfranceklm.com)

---

## 📋 Schema Version

Current: **1.0.0**

---

## 📄 License

Data under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/)

---

Made with ✈️ by the aviation community
