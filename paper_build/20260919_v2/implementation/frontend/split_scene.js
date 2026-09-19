const fs = require('fs');

const classFile = fs.readFileSync('src/WorldScene.js', 'utf8');
const lines = classFile.split('\n');

const modules = {
  CameraController: {
    methods: [
      '#installCameraControls', '#setViewMode', '#applyPresenceFocus', 
      '#focusSelectedAgent', '#previewMoveForAgent'
    ],
    imports: 'import { safeArray } from "./utils.js";\n\n'
  },
  ExportRenderer: {
    methods: [
      '#isExportCaptureMode', '#primeExportFallbackAssets', '#ensureExportFallbackCanvas', 
      '#scheduleExportFallbackRender', '#renderExportFallbackCanvas', '#kickHeadlessRender',
      '#loadExportMapImage', '#loadExportFrame'
    ],
    imports: 'import { firstNonEmpty, safeArray } from "./utils.js";\n\n'
  },
  PovController: {
    methods: [
      '#initializeLocalPovModules', '#localPovEnabled', '#protagonistAgentId', 
      '#bindLocalMovementKeys', '#attemptLocalMove', '#refreshLocalInteractionPanels', 
      '#logLocalAction', '#ensureProtagonistWalkableSpawn', '#povConfig', 
      '#inventoryExchangeConfig', '#negotiationConfig', '#presentAgentExchange',
      '#handleLocalPlayerDeath', '#submitLocalTradeQuote', '#applyLocalDeathSnapshot',
      '#localTraderAgents', '#inventoryTotalMass', '#activeAgentRecords'
    ],
    imports: 'import { firstNonEmpty, safeArray } from "./utils.js";\n\n'
  }
};

let currentMethod = null;
let currentMethodLines = [];
let braceCount = 0;
let inMethod = false;

const parsedMethods = new Map();

for (let i = 0; i < lines.length; i++) {
  const line = lines[i];
  
  if (!inMethod) {
    const match = line.match(/^  (async )?([#a-zA-Z0-9_]+)\s*\(/);
    if (match && !['if', 'for'].includes(match[2])) {
      inMethod = true;
      currentMethod = match[2];
      currentMethodLines = [line];
      braceCount = (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
      
      if (braceCount === 0 && line.includes('{') && line.includes('}')) {
        parsedMethods.set(currentMethod, [...currentMethodLines]);
        inMethod = false;
        currentMethod = null;
      }
    }
  } else {
    currentMethodLines.push(line);
    braceCount += (line.match(/\{/g) || []).length - (line.match(/\}/g) || []).length;
    
    if (braceCount <= 0) {
      parsedMethods.set(currentMethod, [...currentMethodLines]);
      inMethod = false;
      currentMethod = null;
    }
  }
}

for (const [modName, modConfig] of Object.entries(modules)) {
  const out = [modConfig.imports];
  out.push(`export class ${modName} {\n  constructor(worldScene) {\n    this.scene = worldScene;\n  }\n\n`);
  
  for (const m of modConfig.methods) {
    const methodLines = parsedMethods.get(m);
    if (methodLines) {
      for (let i = 0; i < methodLines.length; i++) {
        let line = methodLines[i];
        line = line.replace(/this\.#/g, 'this.');
        if (line.trim().startsWith('#')) {
          line = line.replace('#', '');
        }
        out.push(line + '\n');
      }
      out.push('\n');
    }
  }
  out.push('}\n');
  fs.writeFileSync(`src/${modName}.js`, out.join(''));
  console.log(`Created ${modName}.js`);
}
