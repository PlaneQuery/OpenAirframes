#!/usr/bin/env node

/**
 * Generate README with fleet statistics
 * 
 * Automatically updates README.md with current fleet data from JSON files.
 * Run this after updating fleet data to keep stats in sync.
 * 
 * Usage:
 *   node generate-readme.js
 */

import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const __dirname = path.dirname(fileURLToPath(import.meta.url));

// Airline display info
const AIRLINE_INFO = {
  AF: { name: 'Air France', flag: '🇫🇷', country: 'France' },
  KL: { name: 'KLM', flag: '🇳🇱', country: 'Netherlands' },
};

// Load all airline data
function loadAirlines() {
  const airlinesDir = path.join(__dirname, 'airlines');
  const files = fs.readdirSync(airlinesDir).filter(f => f.endsWith('.json'));
  
  const airlines = {};
  for (const file of files) {
    const code = file.replace('.json', '');
    const content = fs.readFileSync(path.join(airlinesDir, file), 'utf-8');
    airlines[code] = JSON.parse(content);
  }
  return airlines;
}

// Get fleet breakdown by type
function getFleetBreakdown(aircraft) {
  const breakdown = {};
  
  for (const a of aircraft) {
    const typeName = a.aircraft_type?.full_name || 'Unknown';
    // Simplify type name
    let simpleType = typeName
      .replace('AIRBUS ', '')
      .replace('BOEING ', '')
      .replace(' (WINGLETS) PASSENGER/BBJ1', '')
      .replace(' (WINGLETS) PASSENGER/BBJ2', '')
      .replace(' (WINGLETS) PASSENGER/BBJ3', '')
      .replace('/200 ER', '-200ER')
      .replace('-200/200 ER', '-200ER')
      .trim();
    
    breakdown[simpleType] = (breakdown[simpleType] || 0) + 1;
  }
  
  // Sort by count descending
  return Object.entries(breakdown)
    .sort((a, b) => b[1] - a[1]);
}

// Get WiFi stats
function getWifiStats(aircraft) {
  const stats = { none: 0, 'low-speed': 0, 'high-speed': 0 };
  
  for (const a of aircraft) {
    const wifi = a.connectivity?.wifi || 'none';
    stats[wifi] = (stats[wifi] || 0) + 1;
  }
  
  const total = aircraft.length;
  return {
    total,
    none: stats.none,
    lowSpeed: stats['low-speed'],
    highSpeed: stats['high-speed'],
    nonePercent: total ? Math.round(stats.none / total * 100) : 0,
    lowSpeedPercent: total ? Math.round(stats['low-speed'] / total * 100) : 0,
    highSpeedPercent: total ? Math.round(stats['high-speed'] / total * 100) : 0,
  };
}

// Generate markdown table for fleet breakdown
function generateFleetTable(airlines) {
  let md = '';
  
  for (const [code, data] of Object.entries(airlines)) {
    const info = AIRLINE_INFO[code] || { name: code, flag: '✈️' };
    const breakdown = getFleetBreakdown(data.aircraft);
    const wifi = getWifiStats(data.aircraft);
    
    md += `### ${info.flag} ${info.name} (${code})\n\n`;
    md += `| Aircraft Type | Count |\n`;
    md += `|---------------|-------|\n`;
    
    for (const [type, count] of breakdown) {
      md += `| ${type} | ${count} |\n`;
    }
    
    md += `| **Total** | **${wifi.total}** |\n\n`;
  }
  
  return md;
}

// Get detailed breakdown by type and config
function getDetailedBreakdown(aircraft) {
  const breakdown = {};
  
  for (const a of aircraft) {
    const typeName = a.aircraft_type?.full_name || 'Unknown';
    // Simplify type name
    let simpleType = typeName
      .replace('AIRBUS ', '')
      .replace('BOEING ', '')
      .replace(' (WINGLETS) PASSENGER/BBJ1', '')
      .replace(' (WINGLETS) PASSENGER/BBJ2', '')
      .replace(' (WINGLETS) PASSENGER/BBJ3', '')
      .replace('/200 ER', '-200ER')
      .replace('-200/200 ER', '-200ER')
      .trim();
    
    const config = a.cabin?.physical_configuration || '-';
    const wifi = a.connectivity?.wifi || 'none';
    const seats = a.cabin?.total_seats || 0;
    
    const key = `${simpleType}|||${config}`;
    
    if (!breakdown[key]) {
      breakdown[key] = {
        type: simpleType,
        config,
        seats,
        wifi,
        count: 0,
        highSpeed: 0,
      };
    }
    
    breakdown[key].count++;
    if (wifi === 'high-speed') {
      breakdown[key].highSpeed++;
    }
  }
  
  // Sort by type name, then by config (to group similar aircraft together)
  return Object.values(breakdown)
    .sort((a, b) => {
      const typeCompare = a.type.localeCompare(b.type);
      if (typeCompare !== 0) return typeCompare;
      return a.config.localeCompare(b.config);
    });
}

// Generate detailed fleet table per airline
function generateDetailedFleetTable(airlines) {
  let md = '';
  
  for (const [code, data] of Object.entries(airlines)) {
    const info = AIRLINE_INFO[code] || { name: code, flag: '✈️' };
    const breakdown = getDetailedBreakdown(data.aircraft);
    
    md += `### ${info.flag} ${info.name} — Detailed Configuration\n\n`;
    md += `| Aircraft | Config | Seats | Count | 🛜 Starlink |\n`;
    md += `|----------|--------|-------|-------|-------------|\n`;
    
    for (const item of breakdown) {
      const starlinkInfo = item.highSpeed > 0 
        ? `${item.highSpeed}/${item.count} (${Math.round(item.highSpeed / item.count * 100)}%)`
        : '-';
      md += `| ${item.type} | \`${item.config}\` | ${item.seats || '-'} | ${item.count} | ${starlinkInfo} |\n`;
    }
    
    md += `\n`;
  }
  
  return md;
}

// Generate WiFi summary table
function generateWifiSummary(airlines) {
  let md = '| Airline | Total | 📶 WiFi | 🛜 High-Speed | % Starlink |\n';
  md += '|---------|-------|---------|---------------|------------|\n';
  
  let grandTotal = 0;
  let grandWifi = 0;
  let grandHighSpeed = 0;
  
  for (const [code, data] of Object.entries(airlines)) {
    const info = AIRLINE_INFO[code] || { name: code, flag: '✈️' };
    const wifi = getWifiStats(data.aircraft);
    
    const wifiTotal = wifi.lowSpeed + wifi.highSpeed;
    const wifiPercent = wifi.total ? Math.round(wifiTotal / wifi.total * 100) : 0;
    
    md += `| ${info.flag} ${info.name} | ${wifi.total} | ${wifiTotal} (${wifiPercent}%) | ${wifi.highSpeed} | **${wifi.highSpeedPercent}%** |\n`;
    
    grandTotal += wifi.total;
    grandWifi += wifiTotal;
    grandHighSpeed += wifi.highSpeed;
  }
  
  const grandWifiPercent = grandTotal ? Math.round(grandWifi / grandTotal * 100) : 0;
  const grandHighSpeedPercent = grandTotal ? Math.round(grandHighSpeed / grandTotal * 100) : 0;
  
  md += `| **Combined** | **${grandTotal}** | **${grandWifi} (${grandWifiPercent}%)** | **${grandHighSpeed}** | **${grandHighSpeedPercent}%** |\n`;
  
  return md;
}

// Generate the full README
function generateReadme(airlines) {
  const now = new Date().toISOString().split('T')[0];
  
  return `# ✈️ AF-KLM Fleet Catalog

Open source, community-maintained catalog of **Air France** and **KLM** fleets with real-time tracking of aircraft properties, WiFi connectivity, and historical changes.

---

## 📊 Fleet Overview

${generateWifiSummary(airlines)}

> 🛜 **High-Speed** = Starlink satellite internet (50+ Mbps)  
> 📶 **WiFi** = Any WiFi connectivity (low-speed or high-speed)

*Last updated: ${now}*

---

## 🛫 Fleet Breakdown

${generateFleetTable(airlines)}

---

## 📋 Detailed Configuration

${generateDetailedFleetTable(airlines)}

---

## 🚀 Quick Start

### Update the Catalog

\`\`\`bash
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
\`\`\`

### Using the Data

\`\`\`javascript
// Load Air France fleet
const response = await fetch('https://raw.githubusercontent.com/.../airlines/AF.json');
const fleet = await response.json();

// Find all Starlink aircraft
const starlink = fleet.aircraft.filter(a => a.connectivity.wifi === 'high-speed');
console.log(\`\${starlink.length} aircraft with Starlink\`);

// Get aircraft by type
const a350s = fleet.aircraft.filter(a => a.aircraft_type.full_name?.includes('A350'));
\`\`\`

---

## 📁 Data Structure

\`\`\`
af-klm/
├── airlines/
│   ├── AF.json         # Air France fleet
│   └── KL.json         # KLM fleet
├── schema/
│   └── aircraft.schema.json
├── fleet-update.js     # Update script
└── generate-readme.js  # This stats generator
\`\`\`

### Aircraft Schema

\`\`\`json
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
\`\`\`

---

## 🤝 Contributing

### Daily Updates

Community members are encouraged to run the update script daily:

1. Fork this repo
2. Set your \`AFKLM_API_KEY\` 
3. Run \`node fleet-update.js --airline AF\` and \`--airline KL\`
4. Run \`node generate-readme.js\` to update stats
5. Submit a PR

### API Key

Get a free API key at [developer.airfranceklm.com](https://developer.airfranceklm.com)

---

## 📋 Schema Version

Current: **1.0.0**

---

## 📄 License

Under MIT License

---

Made with ✈️  by the aviation community
`;
}

// Main
function main() {
  console.log('📊 Generating README with fleet statistics...\n');
  
  const airlines = loadAirlines();
  
  // Show summary
  for (const [code, data] of Object.entries(airlines)) {
    const info = AIRLINE_INFO[code] || { name: code };
    const wifi = getWifiStats(data.aircraft);
    console.log(`${info.name}: ${wifi.total} aircraft, ${wifi.highSpeed} Starlink (${wifi.highSpeedPercent}%)`);
  }
  
  // Generate and save README
  const readme = generateReadme(airlines);
  const readmePath = path.join(__dirname, 'README.md');
  fs.writeFileSync(readmePath, readme);
  
  console.log(`\n✅ README.md updated!`);
}

main();

